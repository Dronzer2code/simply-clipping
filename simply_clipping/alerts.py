"""P9 alerts: ATTACK, DEFEND, RE-PASS RISK, CLOSING-SPEED RISK from Our Car's point of view.

One :class:`Engine` serves the bench and the pit wall. It is evaluated on a fixed
grid of moments (``alerts.tick_s``): offline every tick of the race, live every
tick up to ``alerts.latency_s`` before now (so every car's smoothed points exist
for it). Same data in, same alerts out (owner SC-3).

Rules (owner SC-3; thresholds in ``alerts.*``):

- ATTACK, the car ahead within ``attack_gap_s``: (a) ``energy``: its estimate at
  least ``attack_margin_mj`` below our exact battery, its confidence at least
  ``min_confidence``; (b) ``observed clip``: on its last pass of the straight we
  are on (or coming to) it showed a CLIP of ``long_clip_s``; the confidence is
  the detection share (feed samples present on that pass), at least
  ``detection_min_share``.
- DEFEND, the car behind within ``defend_gap_s``: (a) ``energy``: its estimate at
  least ``defend_margin_mj`` above ours, confidence at least ``min_confidence``;
  (b) ``own battery``: our battery is below what full deploy on the coming
  straight needs (``need_share`` of it), and the car behind was not seen clipping
  there last lap (detection share at least ``detection_min_share``).
- RE-PASS RISK: we passed a car in the last ``repass_window_s``, our battery is
  below ``repass_our_max_mj`` and the coming straight is longer than
  ``repass_straight_m``.
- CLOSING-SPEED RISK, Our Car involved: a rival within ``closing_range_m`` closes
  (or is closed on) faster than ``closing_dv_kmh``, one car CLIP / LIFT and the
  other DEPLOY. One alert per episode, for the biggest-closing rival; an episode
  ends after ``closing_episode_gap_s`` without one (lesson L-f).

The same pair and type is suppressed for ``suppress_laps`` laps of our progress.
Every alert carries its evidence, confidence and branch.
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from simply_clipping.battles import (
    History,
    Neighbour,
    battles,
    neighbours,
    straight_pass,
    zone_ahead,
)
from simply_clipping.energy import CLIP, DEPLOY, LIFT, STATES
from simply_clipping.loader import Config, Track, const

ALERT_TYPES = ("ATTACK", "DEFEND", "REPASS_RISK", "CLOSING_SPEED_RISK")
ALERT_COLUMNS = ("time_s", "lap", "type", "car_a", "car_b", "confidence", "branch")
KMH = 3.6


def no_alerts() -> pd.DataFrame:
    """Return an empty ``alerts.parquet`` table with the contract's columns."""
    return pd.DataFrame(
        {
            "time_s": pd.Series(dtype="float64"),
            "lap": pd.Series(dtype="int64"),
            "type": pd.Series(dtype="str"),
            "car_a": pd.Series(dtype="str"),
            "car_b": pd.Series(dtype="str"),
            "confidence": pd.Series(dtype="float64"),
            "branch": pd.Series(dtype="str"),
        }
    )


@dataclass(frozen=True)
class Us:
    """Our Car at one moment (exact own data)."""

    t_s: float
    progress_m: float
    lap: int
    v_ms: float
    battery_mj: float
    throttle_pct: float
    brake: bool
    p_elec_kw: float
    """From our own battery's rate of change (exact): + deploying, - harvesting."""
    a_ms2: float


@dataclass(frozen=True)
class AlertRow:
    """One alert as it fired (``alerts.parquet`` row plus evidence)."""

    time_s: float
    lap: int
    type: str
    car_a: str
    car_b: str
    confidence: float
    branch: str
    corner_id: str | None
    our_mj: float
    rival_mj: float | None
    dv_kmh: float | None
    gap_s: float | None
    rival_state: str | None
    last_clip_s_m: float | None
    detection_share: float | None
    need_mj: float | None
    radio: str = ""
    """One-line radio call (:func:`radio_line`)."""


def radio_line(row: AlertRow) -> str:
    """Return the engineer's call: at most ``alerts.radio_max_words`` words, evidence only.

    Template-based (owner SC-6: Gemma only if set up; it is not, so templates).
    """
    corner = row.corner_id or "the next corner"
    rival, our = row.car_b, row.our_mj
    their = row.rival_mj if row.rival_mj is not None else 0.0
    if row.type == "ATTACK":
        if row.branch.startswith("energy"):
            return f"{rival} has {their:.1f} MJ, we have {our:.1f}. Attack into {corner}."
        return f"{rival} clipped here last lap. Attack into {corner}."
    if row.type == "DEFEND":
        if row.branch.startswith("energy"):
            return f"{rival} behind has {their:.1f} MJ, we have {our:.1f}. Defend {corner}."
        need = row.need_mj if row.need_mj is not None else 0.0
        return f"We have {our:.1f} MJ, straight needs {need:.1f}. Defend {corner}."
    if row.type == "REPASS_RISK":
        return f"Only {our:.1f} MJ, long straight ahead. {rival} can re-pass."
    dv = abs(row.dv_kmh) if row.dv_kmh is not None else 0.0
    return f"Closing {dv:.0f} km/h on {rival}. Careful into {corner}."


def our_state(us: Us, cfg: Config) -> int:
    """Our Car's state from exact own data (same thresholds as the rivals')."""
    if us.brake:
        return 2  # HARVEST
    if us.throttle_pct < float(const(cfg, "states.lift_throttle_pct")):
        return LIFT
    if us.throttle_pct >= float(const(cfg, "states.full_throttle_pct")):
        if us.p_elec_kw > float(const(cfg, "states.deploy_min_kw")):
            return DEPLOY
        if us.p_elec_kw < float(const(cfg, "states.clip_max_kw")) and us.a_ms2 <= float(
            const(cfg, "states.clip_max_accel_ms2")
        ):
            return CLIP
    return 4  # CRUISE


class Engine:
    """The four rules, suppression, passes and closing-speed episodes for one Our Car."""

    def __init__(self, our: str, track: Track, cfg: Config) -> None:
        """Rules from ``alerts.*``."""
        self.our, self.track, self.cfg = our, track, cfg
        self.c = {k: const(cfg, f"alerts.{k}") for k in const(cfg, "alerts")}
        self.suppressed: dict[tuple[str, str], float] = {}
        self.last_ahead: set[str] = set()
        self.passed_at: dict[str, float] = {}
        self.closing_last_t = -np.inf
        self.closing_open = False

    def evaluate(self, us: Us, cars: dict[str, History]) -> list[AlertRow]:
        """Alerts that fire at ``us.t_s``."""
        cfg, lap_m = self.cfg, self.track.length_m
        rivals = {d: h for d, h in cars.items() if d != self.our}
        nbrs = neighbours(us.progress_m, us.v_ms, us.t_s, rivals, cfg, lap_m)
        out: list[AlertRow] = []
        s_now = us.progress_m % lap_m
        zone = zone_ahead(self.track, s_now)
        corner = self.track.next_corner(s_now)
        ahead, behind = battles(nbrs, cfg)

        def row(kind: str, n: Neighbour, conf: float, branch: str, **ev: float | None) -> None:
            key = (kind, n.driver)
            if self.suppressed.get(key, -np.inf) > us.progress_m:
                return
            self.suppressed[key] = us.progress_m + float(self.c["suppress_laps"]) * lap_m
            fired = AlertRow(
                us.t_s,
                us.lap,
                kind,
                self.our,
                n.driver,
                float(np.clip(conf, 0.0, 1.0)),
                branch,
                corner,
                us.battery_mj,
                n.energy_mj,
                (us.v_ms - n.v_ms) * KMH,
                n.gap_s,
                STATES[n.state],
                ev.get("clip_s"),
                ev.get("share"),
                ev.get("need"),
            )
            out.append(dataclasses.replace(fired, radio=radio_line(fired)))

        if ahead is not None and ahead.gap_s <= float(self.c["attack_gap_s"]):
            branches, conf, ev = [], 0.0, {}
            if ahead.energy_mj <= us.battery_mj - float(
                self.c["attack_margin_mj"]
            ) and ahead.confidence >= float(self.c["min_confidence"]):
                branches.append("energy")
                conf = ahead.confidence
            seen = (
                straight_pass(
                    rivals[ahead.driver],
                    zone,
                    float(
                        rivals[ahead.driver].col("progress_m")[
                            rivals[ahead.driver].at(us.t_s, np.inf)
                        ]
                    ),
                    self.track,
                    cfg,
                )
                if zone
                else None
            )
            if (
                seen is not None
                and seen.longest_clip_s >= float(self.c["long_clip_s"])
                and seen.detection_share >= float(self.c["detection_min_share"])
            ):
                branches.append("observed clip")
                conf = max(conf, seen.detection_share)
                ev = {"clip_s": seen.clip_start_s_m, "share": seen.detection_share}
            if branches:
                row("ATTACK", ahead, conf, " + ".join(branches), **ev)
        if behind is not None and -behind.gap_s <= float(self.c["defend_gap_s"]):
            branches, conf, ev = [], 0.0, {}
            if behind.energy_mj >= us.battery_mj + float(
                self.c["defend_margin_mj"]
            ) and behind.confidence >= float(self.c["min_confidence"]):
                branches.append("energy")
                conf = behind.confidence
            if zone is not None:
                need = self._need_mj(zone, us)
                if us.battery_mj < float(self.c["need_share"]) * need:
                    hist = rivals[behind.driver]
                    seen = straight_pass(
                        hist,
                        zone,
                        float(hist.col("progress_m")[hist.at(us.t_s, np.inf)]),
                        self.track,
                        cfg,
                    )
                    if (
                        seen is not None
                        and seen.longest_clip_s < float(self.c["long_clip_s"])
                        and seen.detection_share >= float(self.c["detection_min_share"])
                    ):
                        branches.append("own battery")
                        conf = max(conf, seen.detection_share)
                        ev = {"need": need}  # the share is "seen not clipping": confidence only
            if branches:
                row("DEFEND", behind, conf, " + ".join(branches), **ev)
        # Passes: a rival that was ahead (within the battle range) and is now just behind.
        now_ahead = {n.driver for n in nbrs if 0 < n.distance_m < lap_m / 4}
        for n in nbrs:
            if n.driver in self.last_ahead and n.distance_m <= 0 and -n.distance_m < lap_m / 4:
                self.passed_at[n.driver] = us.t_s
        self.last_ahead = now_ahead
        if zone is not None and zone.length_m(lap_m) > float(self.c["repass_straight_m"]):
            if us.battery_mj < float(self.c["repass_our_max_mj"]):
                within = float(const(cfg, "battles.within_s"))
                for n in nbrs:
                    t_pass = self.passed_at.get(n.driver)
                    if (
                        t_pass is not None
                        and us.t_s - t_pass <= float(self.c["repass_window_s"])
                        and n.distance_m <= 0
                        and -n.gap_s <= within
                    ):
                        row("REPASS_RISK", n, 1.0, "repass")
        self._closing(us, nbrs, row)
        return out

    def _need_mj(self, zone: object, us: Us) -> float:
        """Energy full deploy needs on the coming straight (its length at straight speed)."""
        length = zone.length_m(self.track.length_m)  # type: ignore[attr-defined]
        v = float(self.c["straight_speed_kmh"]) / KMH
        return float(length / v * float(const(self.cfg, "car.p_elec_max_kw")) / 1e3)

    def _we_no_deploy(self, us: Us) -> bool:
        """Our Car at full throttle without deploy (exact own data)."""
        return us.throttle_pct >= float(const(self.cfg, "states.full_throttle_pct")) and (
            us.p_elec_kw < float(const(self.cfg, "anchor.no_deploy_kw"))
        )

    def _closing(self, us: Us, nbrs: list[Neighbour], row: object) -> None:
        """One CLOSING-SPEED RISK per episode, for the biggest-closing rival (L-f)."""
        mine = our_state(us, self.cfg)
        best, best_dv = None, 0.0
        s_now = us.progress_m % self.track.length_m
        on_straight = bool(self.track.zone_index(np.array([s_now]), "acceleration_zone")[0] >= 0)
        if bool(self.c["closing_on_straight"]) and not on_straight:
            nbrs = []  # corner entries: the car ahead lifts while we are still on power
        v_min = float(self.c["closing_min_speed_kmh"]) / KMH
        for n in nbrs:
            if abs(n.distance_m) > float(self.c["closing_range_m"]):
                continue
            if min(n.v_ms, us.v_ms) < v_min:  # a car at pit-limiter speed is in the pit lane
                continue
            closing = (us.v_ms - n.v_ms) if n.distance_m > 0 else (n.v_ms - us.v_ms)
            dv = closing * KMH
            slow, fast = (n.state, mine) if n.distance_m > 0 else (mine, n.state)
            slow_empty = n.no_deploy if n.distance_m > 0 else self._we_no_deploy(us)
            slow_ok = STATES[slow] in self.c["closing_slow_states"] or (
                bool(self.c["closing_counts_no_deploy"]) and slow_empty
            )
            fast_ok = STATES[fast] in self.c["closing_fast_states"]
            if dv > float(self.c["closing_dv_kmh"]) and slow_ok and fast_ok:
                if dv > best_dv:
                    best, best_dv = n, dv
        if best is None:
            if us.t_s - self.closing_last_t > float(self.c["closing_episode_gap_s"]):
                self.closing_open = False
            return
        self.closing_last_t = us.t_s
        if not self.closing_open:
            self.closing_open = True
            row("CLOSING_SPEED_RISK", best, best.confidence, "closing")  # type: ignore[operator]


def ticks(t0: float, t1: float, cfg: Config) -> np.ndarray:
    """Return the evaluation moments in [t0, t1]: multiples of ``alerts.tick_s``."""
    step = float(const(cfg, "alerts.tick_s"))
    return np.arange(np.ceil(t0 / step - 1e-9), np.floor(t1 / step + 1e-9) + 1) * step


class OwnTrack:
    """Our exact own samples (trimmed to ``keep_s``); :meth:`at` gives Our Car at a moment."""

    COLS = ("t", "prog", "lap", "v", "e", "thr", "brk")

    def __init__(self, cfg: Config, lap_m: float, keep_s: float = np.inf) -> None:
        """Empty."""
        self.cfg, self.lap_m, self.keep_s = cfg, lap_m, keep_s
        self._rows: list[tuple[float, ...]] = []
        self._arr: np.ndarray | None = None

    def add(
        self,
        t_s: float,
        lap: int,
        s_m: float,
        v_ms: float,
        battery_mj: float,
        throttle_pct: float,
        brake: bool,
    ) -> None:
        """One own sample (time ordered; repeats and older samples are ignored)."""
        if self._rows and t_s <= self._rows[-1][0]:
            return
        self._rows.append(
            (
                t_s,
                (lap - 1) * self.lap_m + s_m,
                float(lap),
                v_ms,
                battery_mj,
                throttle_pct,
                float(brake),
            )
        )
        if np.isfinite(self.keep_s) and t_s - self._rows[0][0] > 2 * self.keep_s:
            self._rows = [r for r in self._rows if r[0] >= t_s - self.keep_s]
        self._arr = None

    @property
    def times(self) -> np.ndarray:
        """Sample times."""
        return self._table()[:, 0]

    def _table(self) -> np.ndarray:
        if self._arr is None:
            self._arr = np.array(self._rows, dtype=np.float64).reshape(-1, len(self.COLS))
        return self._arr

    def at(self, t_s: float) -> Us | None:
        """Our Car at ``t_s``: the last sample at or before it; rates over ``own_rate_s``."""
        arr = self._table()
        k = int(np.searchsorted(arr[:, 0], t_s, side="right")) - 1
        if k < 0:
            return None
        t, prog, lap, v, e, thr, brk = arr[k]
        back = float(const(self.cfg, "alerts.own_rate_s"))
        j = min(int(np.searchsorted(arr[:, 0], t - back, side="left")), k)
        dt = t - arr[j, 0]
        p_elec = (arr[j, 4] - e) / dt * 1e3 if dt > 0 else 0.0
        acc = (v - arr[j, 3]) / dt if dt > 0 else 0.0
        return Us(
            t_s,
            float(prog),
            int(lap),
            float(v),
            float(e),
            float(thr),
            bool(brk > 0.5),
            float(p_elec),
            float(acc),
        )


def offline_alerts(
    histories: dict[str, History], own: OwnTrack, our: str, track: Track, cfg: Config
) -> list[AlertRow]:
    """Every alert for ``our`` over the race, ticking like the pit wall would."""
    times = own.times
    if times.size == 0:
        return []
    engine = Engine(our, track, cfg)
    out: list[AlertRow] = []
    for t in ticks(float(times[0]), float(times[-1]), cfg):
        us = own.at(float(t))
        if us is not None:
            out += engine.evaluate(us, histories)
    return out


def alerts_frame(rows: list[AlertRow]) -> pd.DataFrame:
    """``alerts.parquet``: the contract columns plus the evidence."""
    if not rows:
        return no_alerts()
    return pd.DataFrame([asdict(r) for r in rows])
