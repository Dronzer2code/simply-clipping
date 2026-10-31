"""Alert providers (sprint A-1): what the pit wall should warn about, from Our Car's view.

An :class:`AlertProvider` sees :class:`EngineerView` ONLY (information barrier:
Our Car's exact state, the Rivals' Radar Estimates, public timing and feed) and
returns the alerts active now. The built-in ``simply_clipping_lite`` implements
the Rival Battery Radar alert rules (docs/planning/SPRINT.md A-1); a real Simply Clipping
plugs in through ``alerts.provider: external:<module.path>`` (a module with
``create(cfg, track) -> AlertProvider``).

Rules (thresholds in ``app.yaml: alerts``):

- ATTACK: the car ahead within ``attack_gap_s`` and either (a) energy: its
  Radar Estimate at least ``energy_margin_mj`` below our battery (Radar
  confidence), or (b) observed clip: it was seen in CLIP on the coming straight
  last lap, gated by DETECTION confidence, the share of its feed samples present
  on that straight then (at least ``detection_min_share``), not by the energy
  confidence (owner, sprint day 5). "Seen in CLIP" means a Radar CLIP state
  lasting ``clip_min_s`` on a straight zone (single CLIP samples are a car at
  full throttle on partial deployment, not an empty battery);
- DEFEND: the car behind within ``defend_gap_s`` and either (a) energy: its
  estimate at least ``energy_margin_mj`` above our battery, or (b) own battery:
  our exact battery minus ``battery_reserve_mj`` is less than full deployment
  on the coming straight needs (the Rule Set zone cap over the time we took on
  that straight last lap) and the car behind was not seen clipping last lap;
- REPASS_RISK: we passed a car in the last ``repass_window_s``, our battery is
  below ``repass_battery_mj`` and the coming straight is longer than
  ``repass_straight_m``;
- CLOSING_SPEED_RISK: a car within ``closing_range_m`` with more than
  ``closing_dv_kmh`` speed difference, one of the two CLIP / LIFT with at least
  ``closing_min_straight_left_m`` of straight zone ahead of it (not lifting for
  the corner) and the other DEPLOY (Rivals' states from the Radar, ours from our
  exact throttle, brake and battery: full throttle on an empty battery is CLIP).

Rules that read a Radar Estimate need a Radar fit; no alert fires below
``min_confidence`` (the pit wall greys those below ``low_confidence``). The
evidence names the branch that fired.
ATTACK and DEFEND are position fights: the rival must be on our lap (public
``laps_down``), never a lapped car or one lapping us. A condition must hold for
``hold_s`` before its alert fires (hysteresis).
The same type and rival are suppressed for ``suppress_laps`` of our distance.
An alert lives ``expiry_s`` or until its condition clears.
"""

from __future__ import annotations

import importlib
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

from pitwall_sim.config.models import AlertsConfig, PowerRules, TrackConfig
from pitwall_sim.observe.engineer_view import EngineerView

AlertType = Literal["ATTACK", "DEFEND", "REPASS_RISK", "CLOSING_SPEED_RISK"]
ALERT_TYPES: tuple[AlertType, ...] = ("ATTACK", "DEFEND", "REPASS_RISK", "CLOSING_SPEED_RISK")
CarPowerState = Literal["DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE"]
MJ = 1e6
DEFAULT_LAP_S = 100.0
FRESH_FRAME_S = 1.0
"""A Rival's latest feed frame counts for closing speed only if this recent."""
LAST_LAP = 1.3
""""Last lap" for clips: within this many of the rival's last lap times."""
PRIOR_LABEL = "assumed full at start"
CLIP_GAP_S = 0.6
"""A CLIP run survives a gap this long (a dropped feed frame or two)."""


@dataclass(frozen=True)
class AlertEvidence:
    """What the alert is based on (shown when the alert is clicked)."""

    our_mj: float
    rival_mj: float | None
    """Rival's Radar Estimate."""
    dv_kmh: float | None
    """Our speed minus the rival's."""
    gap_s: float | None
    """Public interval to the rival (positive: they are ahead)."""
    rival_state: str | None
    last_clip_s_m: float | None
    branch: str | None = None
    """Which rule fired: ``energy``, ``observed clip``, ``own battery`` (joined by +)."""
    detection_share: float | None = None
    """Observed clip: share of the rival's feed samples present on that straight."""
    need_mj: float | None = None
    """Own battery: energy full deployment on the coming straight needs."""
    rival_basis: str | None = None
    """``assumed full at start`` while the rival's estimate rests on the start prior."""


@dataclass(frozen=True)
class Alert:
    """One pit-wall warning about one rival."""

    alert_id: str
    type: AlertType
    rival: str
    """driver_id."""
    lap: int
    """Our lap when it fired (1-based)."""
    corner_id: str | None
    """Our next corner."""
    evidence: AlertEvidence
    confidence: float
    """From the Radar (1.0 when the rule uses only our own exact data)."""
    created_t: float
    expires_t: float


class _Estimate(Protocol):
    """The Radar Estimate fields the rules read (the EngineerView carries them)."""

    @property
    def energy_mj(self) -> float: ...
    @property
    def state(self) -> str: ...
    @property
    def confidence(self) -> float: ...
    @property
    def last_clip_s_m(self) -> float | None: ...
    @property
    def prior(self) -> bool: ...


class AlertProvider(Protocol):
    """Pit-wall alerts from an :class:`EngineerView` (and nothing else)."""

    def update(self, view: EngineerView) -> list[Alert]:
        """Take the current view; return the alerts active now, newest first."""
        ...


@dataclass
class _Straight:
    zone_id: str
    start_m: float
    length_m: float
    accel_share: float = 0.0
    """Share of the straight inside acceleration zones (their MGU-K cap applies)."""


@dataclass
class SimplyClippingLite:
    """Built-in provider: the Rival Battery Radar alert rules from Our Car's view."""

    cfg: AlertsConfig
    length_m: float
    straights: list[_Straight]
    corners: list[tuple[float, str]]
    """(s_m, corner_id), sorted."""
    _active: dict[tuple[AlertType, str], Alert] = field(default_factory=dict)
    _suppressed_until_m: dict[tuple[AlertType, str], float] = field(default_factory=dict)
    _clips: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    """Rival -> (t_s, lap distance) at the end of each sustained CLIP seen on a straight."""
    _clip_runs: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    """Rival -> (start, last t_s, last distance) of the CLIP run it is in."""
    _last_order: list[str] = field(default_factory=list)
    _passes: list[tuple[float, str]] = field(default_factory=list)
    """(t_s, driver_id) of each car Our Car passed."""
    _ids: itertools.count[int] = field(default_factory=itertools.count)
    _since: dict[tuple[AlertType, str], float] = field(default_factory=dict)
    """When each currently true condition became true (hysteresis)."""
    caps_w: tuple[float, float] | None = None
    """Rule Set MGU-K caps (acceleration zones, elsewhere), W; ``None``: no own-battery DEFEND."""
    _our_time_s: dict[str, float] = field(default_factory=dict)
    """Straight zone -> the time we took on it last time through (our own exact data)."""
    _our_on: tuple[str, float, float] | None = None
    """(zone, entered, last seen) while we are on a straight."""
    feed_rate_hz: float | None = None
    """The Public Feed's nominal rate (public); ``None``: taken from the frame spacing."""

    @classmethod
    def for_track(
        cls, cfg: AlertsConfig, track: TrackConfig, power: PowerRules | None = None,
        feed_rate_hz: float | None = None,
    ) -> SimplyClippingLite:  # fmt: skip
        """Set up with the track's public layout, the Rule Set's caps and the feed rate.

        Straight zones and corners; the MGU-K zone caps for the own-battery DEFEND;
        the Public Feed's nominal rate for the observed-clip detection share.
        """
        length = float(track.official_length_m)
        accel = [(z.s_start_m, (z.s_end_m - z.s_start_m) % length) for z in track.zones
                 if "acceleration_zone" in z.tags]  # fmt: skip
        straights = []
        for z in track.zones:
            if z.type != "straight":
                continue
            span = (z.s_end_m - z.s_start_m) % length
            inside = sum(_overlap_m(z.s_start_m, span, a, n, length) for a, n in accel)
            straights.append(_Straight(z.zone_id, z.s_start_m, span, inside / span if span else 0))
        corners = sorted((c.s_m, c.corner_id) for c in track.corners)
        caps = None
        if power is not None:
            acc, other = power.zone_caps_kw.acceleration_zone, power.zone_caps_kw.other
            if not isinstance(acc, str) and not isinstance(other, str):
                caps = (float(acc) * 1e3, float(other) * 1e3)
        return cls(cfg, length, straights, corners, caps_w=caps, feed_rate_hz=feed_rate_hz)

    # ------------------------------------------------------------------ #
    def update(self, view: EngineerView) -> list[Alert]:
        """Fire, keep and clear alerts for this view; newest first."""
        cfg, me, t = self.cfg, view.our_car, view.t_s
        our_mj = me.battery_mj
        our_d = me.lap * self.length_m + me.s_m  # our race distance (suppression)
        order = view.timing.order
        self._watch_clips(view)
        self._watch_passes(view)
        self._watch_our_straights(view)
        found: dict[tuple[AlertType, str], tuple[AlertEvidence, float]] = {}
        k = order.index(me.driver_id) if me.driver_id in order else -1
        ahead = order[k - 1] if k > 0 else None
        behind = order[k + 1] if 0 <= k < len(order) - 1 else None
        laps_down = view.timing.laps_down
        if ahead is not None and laps_down.get(ahead) != laps_down.get(me.driver_id):
            ahead = None  # not the same lap: no position fight (blue flags)
        if behind is not None and laps_down.get(behind) != laps_down.get(me.driver_id):
            behind = None

        gap = view.timing.interval_s.get(me.driver_id)
        if ahead is not None and gap is not None and gap <= cfg.attack_gap_s:
            est = view.radar.get(ahead)
            branches, confidence = [], 0.0
            if (
                est is not None
                and est.confidence >= cfg.min_confidence
                and our_mj - est.energy_mj >= cfg.energy_margin_mj
            ):
                branches.append("energy")
                confidence = est.confidence
            share = self._clip_detection(ahead, me.s_m, t, view)
            if share is not None and share >= cfg.detection_min_share:
                branches.append("observed clip")
                confidence = max(confidence, share)
            if branches:
                found[("ATTACK", ahead)] = (
                    _evidence(our_mj, est, gap, " + ".join(branches), detection_share=share),
                    confidence,
                )
        gap = view.timing.interval_s.get(behind) if behind is not None else None
        if behind is not None and gap is not None and gap <= cfg.defend_gap_s:
            est = view.radar.get(behind)
            branches, confidence = [], 0.0
            if (
                est is not None
                and est.confidence >= cfg.min_confidence
                and est.energy_mj - our_mj >= cfg.energy_margin_mj
            ):
                branches.append("energy")
                confidence = est.confidence
            need = self._deploy_need_mj(me.s_m)
            if (
                need is not None
                and need > our_mj - cfg.battery_reserve_mj
                and not self._clipped_last_lap(behind, t, view)
            ):
                branches.append("own battery")
                confidence = 1.0  # our own exact battery and the public gap
            if branches:
                found[("DEFEND", behind)] = (
                    _evidence(our_mj, est, -gap, " + ".join(branches), need_mj=need),
                    confidence,
                )
        if our_mj < cfg.repass_battery_mj:
            straight = self._coming_straight(me.s_m)
            if straight is not None and straight.length_m > cfg.repass_straight_m:
                for t_pass, rival in self._passes:
                    if t - t_pass <= cfg.repass_window_s:
                        seen = view.radar.get(rival)
                        found[("REPASS_RISK", rival)] = (
                            AlertEvidence(our_mj, seen.energy_mj if seen else None, None,
                                          view.timing.interval_s.get(rival),
                                          seen.state if seen else None, None),
                            1.0,  # our own exact battery and the public order
                        )  # fmt: skip
        our_state = self._our_state(view)
        for rival, frames in view.rival_feed.items():
            seen = view.radar.get(rival)
            if me.status != "RUNNING" or not frames or seen is None or seen.confidence <= 0.0:
                continue  # in the pit lane, no Radar fit yet, or no feed
            frame = frames[-1]
            if t - frame.t_s > FRESH_FRAME_S:
                continue  # stale: the car is in the pit lane or its frames dropped
            ahead_m = (frame.distance_m - me.s_m + self.length_m / 2) % self.length_m
            ahead_m -= self.length_m / 2
            dv = me.v_ms * 3.6 - frame.speed_kmh
            if abs(ahead_m) > cfg.closing_range_m or abs(dv) <= cfg.closing_dv_kmh:
                continue
            slow = {"CLIP", "LIFT"}
            we_slow = our_state in slow and seen.state == "DEPLOY" and self._on_straight(me.s_m)
            they_slow = (
                seen.state in slow and our_state == "DEPLOY" and self._on_straight(frame.distance_m)
            )
            if we_slow or they_slow:
                found[("CLOSING_SPEED_RISK", rival)] = (
                    AlertEvidence(our_mj, seen.energy_mj, dv, view.timing.interval_s.get(rival),
                                  seen.state, seen.last_clip_s_m),
                    seen.confidence,
                )  # fmt: skip

        # Too unsure to warn at all: drop (no greyed spam).
        found = {k_: v for k_, v in found.items() if v[1] >= cfg.min_confidence}
        # Hysteresis: a condition must hold for hold_s before its alert fires.
        self._since = {k_: self._since.get(k_, t) for k_ in found}
        # Conditions that cleared end their alert; expired ones go too.
        for key in [k_ for k_, a in self._active.items() if k_ not in found or t >= a.expires_t]:
            del self._active[key]
        for key, (evidence, confidence) in found.items():
            if key in self._active or our_d < self._suppressed_until_m.get(key, -1.0):
                continue
            if t - self._since[key] < cfg.hold_s:
                continue
            alert_type, rival = key
            self._active[key] = Alert(
                alert_id=f"{alert_type}-{rival}-{next(self._ids)}",
                type=alert_type, rival=rival, lap=me.lap + 1,
                corner_id=self._next_corner(me.s_m), evidence=evidence,
                confidence=float(min(max(confidence, 0.0), 1.0)),
                created_t=t, expires_t=t + cfg.expiry_s,
            )  # fmt: skip
            self._suppressed_until_m[key] = our_d + cfg.suppress_laps * self.length_m
        for key, (evidence, _) in found.items():  # keep the evidence current
            if key in self._active:
                self._active[key] = replace(self._active[key], evidence=evidence)
        return sorted(self._active.values(), key=lambda a: -a.created_t)

    # ------------------------------------------------------------------ #
    def _watch_clips(self, view: EngineerView) -> None:
        """Record each CLIP that lasted ``clip_min_s`` and ended on a straight zone.

        The Radar's CLIP state also shows a car at full throttle with partial
        deployment (BALANCED), for a sample or two; only a sustained clip on a
        straight (as the Radar's own anchor) counts as "seen clipping".
        """
        for rival, est in view.radar.items():
            frames = view.rival_feed.get(rival)
            if not frames:
                continue
            run = self._clip_runs.get(rival)
            if est.state == "CLIP":
                d = frames[-1].distance_m
                if run is not None and view.t_s - run[1] <= CLIP_GAP_S:
                    self._clip_runs[rival] = (run[0], view.t_s, d)  # the run goes on
                    continue
                self._clip_runs[rival] = (view.t_s, view.t_s, d)  # a new run; any old one ended
            elif run is None:
                continue
            else:
                del self._clip_runs[rival]
            if run is not None and run[1] - run[0] >= self.cfg.clip_min_s:
                straight = self._coming_straight(run[2])
                if straight is not None and (
                    (run[2] - straight.start_m) % self.length_m <= straight.length_m
                ):
                    self._clips.setdefault(rival, []).append((run[1], run[2]))
        horizon = view.t_s - 2.0 * DEFAULT_LAP_S
        for rival in self._clips:
            self._clips[rival] = [c for c in self._clips[rival] if c[0] >= horizon]

    def _watch_our_straights(self, view: EngineerView) -> None:
        """Time each straight we drive through, from entry to exit (our exact data)."""
        me = view.our_car
        on = None
        if me.status == "RUNNING":
            on = next((st for st in self.straights
                       if (me.s_m - st.start_m) % self.length_m <= st.length_m), None)  # fmt: skip
        if self._our_on is not None and (on is None or on.zone_id != self._our_on[0]):
            zone, entered, last = self._our_on
            self._our_time_s[zone] = last - entered
            self._our_on = None
        if on is not None:
            if self._our_on is None:
                # Only a traversal timed from the entry counts (not a pit exit or the start).
                into = (me.s_m - on.start_m) % self.length_m
                if into <= 0.1 * on.length_m:
                    self._our_on = (on.zone_id, view.t_s, view.t_s)
            else:
                self._our_on = (on.zone_id, self._our_on[1], view.t_s)

    def _deploy_need_mj(self, s_m: float) -> float | None:
        """Energy full deployment on the coming straight needs (MJ), at the zone caps."""
        straight = self._coming_straight(s_m)
        if self.caps_w is None or straight is None:
            return None
        time_s = self._our_time_s.get(straight.zone_id)
        if time_s is None:
            return None  # not timed yet (first lap)
        acc, other = self.caps_w
        power_w = straight.accel_share * acc + (1.0 - straight.accel_share) * other
        return power_w * time_s / MJ

    def _clipped_last_lap(self, rival: str, t_s: float, view: EngineerView) -> bool:
        lap_s = view.timing.last_lap_s.get(rival) or DEFAULT_LAP_S
        return any(t_s - t_clip <= LAST_LAP * lap_s for t_clip, _ in self._clips.get(rival, []))

    def _watch_passes(self, view: EngineerView) -> None:
        order, me = view.timing.order, view.our_car.driver_id
        if self._last_order and me in order and me in self._last_order:
            now, before = order.index(me), self._last_order.index(me)
            if now < before:  # we gained places: the cars now just behind us
                for rival in order[now + 1 : before + 1]:
                    if rival in self._last_order[:before]:
                        self._passes.append((view.t_s, rival))
        self._last_order = list(order)
        self._passes = [p for p in self._passes if view.t_s - p[0] <= self.cfg.repass_window_s]

    def _on_straight(self, s_m: float) -> bool:
        """On a straight zone with at least ``closing_min_straight_left_m`` of it left."""
        left = self.cfg.closing_min_straight_left_m
        return any(
            (s_m - st.start_m) % self.length_m <= st.length_m - left for st in self.straights
        )

    def _coming_straight(self, s_m: float) -> _Straight | None:
        """Return the straight we are on, else the next one ahead."""
        best, best_d = None, float("inf")
        for st in self.straights:
            into = (s_m - st.start_m) % self.length_m
            if into <= st.length_m:
                return st
            d = (st.start_m - s_m) % self.length_m
            if d < best_d:
                best, best_d = st, d
        return best

    def _clip_detection(
        self, rival: str, our_s_m: float, t_s: float, view: EngineerView
    ) -> float | None:
        """Return the detection confidence of the rival's CLIP on the coming straight.

        The share of the feed samples expected on that straight during that pass
        (its length over the rival's mean speed there, at the feed rate) that
        arrived; the best pass if it clipped more than once. ``None``: no clip seen.
        """
        straight = self._coming_straight(our_s_m)
        if straight is None:
            return None
        lap_s = view.timing.last_lap_s.get(rival) or DEFAULT_LAP_S
        clips = [
            t_clip
            for t_clip, d in self._clips.get(rival, [])
            if t_s - t_clip <= LAST_LAP * lap_s
            and (d - straight.start_m) % self.length_m <= straight.length_m
        ]
        if not clips:
            return None
        frames = view.rival_feed.get(rival, [])
        start, span = straight.start_m, straight.length_m
        on = [f for f in frames if (f.distance_m - start) % self.length_m <= span]
        if not on:
            return 0.0
        rate_hz = self.feed_rate_hz
        if rate_hz is None:  # no nominal rate given: the median frame spacing
            steps = sorted(b.t_s - a.t_s for a, b in itertools.pairwise(frames) if b.t_s > a.t_s)
            if not steps:
                return 0.0
            rate_hz = 1.0 / steps[len(steps) // 2]
        best = 0.0
        for t_clip in clips:
            near = min(on, key=lambda f: abs(f.t_s - t_clip))
            reach_s = 2.0 * straight.length_m / max(near.speed_kmh / 3.6, 10.0)
            passed = [f for f in on if abs(f.t_s - t_clip) <= reach_s]
            if not passed:
                continue  # that pass has left the feed window: nothing detected
            v_ms = sum(f.speed_kmh for f in passed) / len(passed) / 3.6
            expected = straight.length_m / max(v_ms, 10.0) * rate_hz
            best = max(best, min(len(passed) / expected, 1.0) if expected > 0 else 0.0)
        return best

    def _next_corner(self, s_m: float) -> str | None:
        for s, corner in self.corners:
            if s > s_m:
                return corner
        return self.corners[0][1] if self.corners else None

    @staticmethod
    def _our_state(view: EngineerView) -> CarPowerState:
        me = view.our_car
        if me.brake > 0.0:
            return "HARVEST"
        if me.throttle < 0.2:
            return "LIFT"
        if me.throttle >= 0.95:
            return "CLIP" if me.battery_mj <= 0.05 else "DEPLOY"
        return "CRUISE"


def _overlap_m(a0: float, a_len: float, b0: float, b_len: float, length: float) -> float:
    """Overlap of two stretches of track (start, length), wrap-aware."""
    total = 0.0
    for shift in (-length, 0.0, length):
        lo, hi = max(a0, b0 + shift), min(a0 + a_len, b0 + shift + b_len)
        total += max(hi - lo, 0.0)
    return total


def _evidence(
    our_mj: float, est: _Estimate | None, gap_s: float, branch: str,
    detection_share: float | None = None, need_mj: float | None = None,
) -> AlertEvidence:  # fmt: skip
    """ATTACK / DEFEND evidence; the estimate is shown only if the Radar has one."""
    known = est is not None and est.confidence > 0.0
    return AlertEvidence(
        our_mj,
        est.energy_mj if known and est is not None else None,
        None,
        gap_s,
        est.state if est is not None else None,
        est.last_clip_s_m if est is not None else None,
        branch=branch,
        detection_share=detection_share,
        need_mj=need_mj,
        rival_basis=PRIOR_LABEL if known and est is not None and est.prior else None,
    )


def make_provider(
    cfg: AlertsConfig, track: TrackConfig, power: PowerRules | None = None,
    feed_rate_hz: float | None = None,
) -> AlertProvider:  # fmt: skip
    """Build the provider ``alerts.provider`` names: built-in or ``external:<module.path>``.

    ``power`` (the Rule Set's power limits) and ``feed_rate_hz`` (the Public Feed's
    nominal rate) reach the built-in provider only; an external one is created
    with ``create(cfg, track)``.
    """
    if cfg.provider == "simply_clipping_lite":
        return SimplyClippingLite.for_track(cfg, track, power, feed_rate_hz)
    if cfg.provider.startswith("external:"):
        module = importlib.import_module(cfg.provider.removeprefix("external:"))
        create: Callable[[AlertsConfig, TrackConfig], AlertProvider] = module.create
        return create(cfg, track)
    raise ValueError(f"unknown alerts.provider {cfg.provider!r}")
