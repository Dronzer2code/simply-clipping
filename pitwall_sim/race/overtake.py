"""F05 overtake model (T-034; TRD OVERTAKE MODEL, PF-11).

Cars cannot drive through each other: the step kernel holds a car
``overtake.follow_gap_m`` behind the car ahead. Passes happen here. When an
attacker within ``trigger_gap_m`` of the car ahead enters a braking zone or an
overtaking zone (a *trigger point*), it attempts a pass::

    x = w_dv dv_braking + w_grip dgrip + w_overtake_mode OT_active
        + w_racecraft (racecraft_att - racecraft_def) + w_attack ATTACK
        - w_defend DEFEND - w_difficulty zone_difficulty
    p_pass = sigmoid(x);  success ~ Bernoulli(p_pass) on RNG stream "overtake"

Success swaps the two cars on the road (PF-11 "swap order"); failure sets the
attacker back by its speed x ``fail_time_loss_s`` (PF-11 "attacker loses
dt_fail"; contact and incidents are T-038). A car a lap ahead passes a
backmarker without an attempt (blue flag). A car under HOLD_POSITION makes no
attempt (TRD AI DRIVER; owner, sprint day 5 follow-up); blue flags still apply.
Every weight and difficulty is a
``# PLACEHOLDER: calibrate (F20)`` value in ``app.yaml`` (the TRD marks them
UNKNOWN). ``w_attack`` (sprint day 4) mirrors ``w_defend``: an attacker under an
ATTACK instruction commits to the move; without it an engineer's ATTACK call
would change nothing the AI does not already do on its own.

Braking-zone trigger points come from the speed profile: where the reference
speed starts to fall by at least ``braking_trigger_min_drop_kmh``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from numba import njit

from pitwall_sim.config.models import OvertakeConfig, TrackConfig
from pitwall_sim.race import step_kernel as K

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]

#: The config keys the TRD marks UNKNOWN (placeholders until F20 calibration).
PLACEHOLDER_KEYS = (
    "trigger_gap_m",
    "w_dv_per_ms",
    "w_grip",
    "w_overtake_mode",
    "w_racecraft",
    "w_defend",
    "w_difficulty",
    "zone_difficulty_default",
    "braking_zone_difficulty",
    "fail_time_loss_s",
)


@dataclass(frozen=True)
class TriggerPoint:
    """Where attempts happen: a braking-zone or overtaking-zone entry."""

    s_m: float
    difficulty: float
    zone_id: str | None
    """Overtaking zone id, ``None`` for a braking zone."""


@dataclass(frozen=True)
class OvertakeEvent:
    """One attempt (or blue-flag pass)."""

    t_s: float
    attacker: int
    defender: int
    s_m: float
    p_pass: float
    success: bool
    blue_flag: bool = False


def p_pass(
    cfg: OvertakeConfig,
    dv_ms: float,
    dgrip: float,
    overtake_active: bool,
    racecraft_diff: float,
    defend: bool,
    difficulty: float,
    attack: bool = False,
) -> float:
    """Pass probability of one attempt (TRD OVERTAKE MODEL)."""
    x = (
        cfg.w_dv_per_ms * dv_ms
        + cfg.w_grip * dgrip
        + cfg.w_overtake_mode * float(overtake_active)
        + cfg.w_racecraft * racecraft_diff
        + cfg.w_attack * float(attack)
        - cfg.w_defend * float(defend)
        - cfg.w_difficulty * difficulty
    )
    return 1.0 / (1.0 + math.exp(-x))


def trigger_points(
    track: TrackConfig, cfg: OvertakeConfig, s_m: FloatArray, v_ref_ms: FloatArray
) -> list[TriggerPoint]:
    """Overtaking-zone entries and the braking-zone entries of a speed profile."""
    points = []
    for zone in track.zones:
        if zone.type == "overtaking":
            value = track.zone_difficulty.get(zone.zone_id)
            difficulty = (
                cfg.zone_difficulty_default
                if value is None or isinstance(value, str)
                else float(value)
            )
            points.append(TriggerPoint(zone.s_start_m, difficulty, zone.zone_id))
    n = v_ref_ms.size
    falling = v_ref_ms < np.roll(v_ref_ms, 1) - 1e-6
    for start in np.flatnonzero(falling & ~np.roll(falling, 1)):
        end = start
        while falling[(end + 1) % n] and end - start < n:
            end += 1
        drop_kmh = (v_ref_ms[(start - 1) % n] - v_ref_ms[end % n]) * 3.6
        s = float(s_m[start])
        near_zone = any(abs(s - p.s_m) < cfg.trigger_gap_m for p in points if p.zone_id)
        if drop_kmh >= cfg.braking_trigger_min_drop_kmh and not near_zone:
            points.append(TriggerPoint(s, cfg.braking_zone_difficulty, None))
    return sorted(points, key=lambda p: p.s_m)


def crossed(s_before: float, s_after: float, point: float) -> bool:
    """``point`` lies in ``(s_before, s_after]`` along the lap (wrap-aware)."""
    if s_after >= s_before:
        return s_before < point <= s_after
    return point > s_before or point <= s_after


@njit(cache=True)
def _close_hits(
    s_before: FloatArray, s_after: FloatArray, running: npt.NDArray[np.bool_],
    ahead_idx: npt.NDArray[np.int64], gap_m: FloatArray, trigger_gap_m: float,
    points: FloatArray,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:  # fmt: skip
    """``(car, point)`` pairs, car-major: a close car passed the point (see :func:`crossed`)."""
    cars, ks = [], []
    for i in range(s_before.size):
        if not running[i] or ahead_idx[i] < 0 or gap_m[i] > trigger_gap_m:
            continue
        b, a = s_before[i], s_after[i]
        for k in range(points.size):
            p = points[k]
            if (b < p <= a) if a >= b else (p > b or p <= a):
                cars.append(i)
                ks.append(k)
    return np.array(cars, dtype=np.int64), np.array(ks, dtype=np.int64)


class OvertakeModel:
    """Attempts at trigger points, swaps and set-backs on the kernel state."""

    def __init__(
        self,
        cfg: OvertakeConfig,
        triggers: list[TriggerPoint],
        trk: K.KernelTrack,
        rng: np.random.Generator,
        racecraft: FloatArray,
    ) -> None:
        """Set up the model for one race (``racecraft`` per car, grid order)."""
        self.cfg = cfg
        self.triggers = triggers
        self.length_m = trk.length_m
        self.loops_m = trk.loops_m
        self._trigger_s = np.array([p.s_m for p in triggers], dtype=np.float64)
        self.rng = rng
        self.racecraft = racecraft
        self.events: list[OvertakeEvent] = []
        logger.info(
            "overtake weights are placeholders until F20 calibration: %s",
            ", ".join(PLACEHOLDER_KEYS),
        )

    def resolve(
        self,
        t_s: float,
        s_before: FloatArray,
        car: K.KernelCars,
        ctl: K.KernelControls,
        st: K.KernelState,
        defending: npt.NDArray[np.bool_],
        attacking: npt.NDArray[np.bool_] | None = None,
        holding: npt.NDArray[np.bool_] | None = None,
    ) -> list[OvertakeEvent]:
        """Resolve an attempt for every close car that passed a trigger point since ``s_before``.

        ``holding``: cars under HOLD_POSITION, which only pass lapped cars (blue flags).
        """
        cars, points = _close_hits(
            s_before, st.s_m, st.running, st.ahead_idx, st.gap_ahead_m,
            self.cfg.trigger_gap_m, self._trigger_s,
        )  # fmt: skip
        if cars.size == 0:
            return []
        new: list[OvertakeEvent] = []
        mu = K.grip_mu(car, st, ctl)
        for i, k in zip(cars.tolist(), points.tolist(), strict=True):
            d = int(st.ahead_idx[i])
            if not st.running[d] or st.ahead_idx[i] < 0:
                continue
            event = self._attempt(
                t_s, int(i), d, self.triggers[k], mu, ctl, st, defending,
                bool(attacking[i]) if attacking is not None else False,
                bool(holding[i]) if holding is not None else False,
            )  # fmt: skip
            if event is not None:
                new.append(event)
        self.events.extend(new)
        return new

    def _attempt(
        self,
        t_s: float,
        a: int,
        d: int,
        point: TriggerPoint,
        mu: FloatArray,
        ctl: K.KernelControls,
        st: K.KernelState,
        defending: npt.NDArray[np.bool_],
        attack: bool = False,
        hold: bool = False,
    ) -> OvertakeEvent | None:
        length = self.length_m
        progress_a = st.lap[a] * length + st.s_m[a]
        progress_d = st.lap[d] * length + st.s_m[d]
        if progress_a > progress_d + 0.5 * length:  # a lap ahead: blue flag
            if self._swap(a, d, st, t_s):
                return OvertakeEvent(t_s, a, d, point.s_m, 1.0, True, blue_flag=True)
            return None
        if hold:  # HOLD_POSITION: no overtake attempts
            return None
        p = p_pass(
            self.cfg,
            float(st.v_ms[a] - st.v_ms[d]),
            float(mu[a] - mu[d]),
            bool(ctl.overtake_active[a]),
            float(self.racecraft[a] - self.racecraft[d]),
            bool(defending[d]),
            point.difficulty,
            attack,
        )
        success = bool(self.rng.random() < p)
        if success:
            if not self._swap(a, d, st, t_s):
                return None
        else:
            self._set_back(a, st, float(st.v_ms[a]) * self.cfg.fail_time_loss_s)
        return OvertakeEvent(t_s, a, d, point.s_m, p, success)

    # ------------------------------------------------------------------ #
    # Moving cars on the road
    # ------------------------------------------------------------------ #

    def _swap(self, a: int, d: int, st: K.KernelState, t_s: float) -> bool:
        """Swap attacker ``a`` (behind) and defender ``d`` on the road.

        Positions and speeds are exchanged; a swap across the timing line is
        skipped (each car keeps its own lap count).
        """
        s_a, s_d = float(st.s_m[a]), float(st.s_m[d])
        if s_d < s_a:  # the line lies between them
            return False
        st.s_m[a], st.s_m[d] = s_d, s_a
        st.v_ms[a], st.v_ms[d] = st.v_ms[d], st.v_ms[a]
        self._resync_loops(a, st, t_s)
        self._resync_loops(d, st, t_s)
        return True

    def _set_back(self, a: int, st: K.KernelState, metres: float) -> None:
        """Move ``a`` back by up to ``metres``: not past the line or the car behind."""
        s = float(st.s_m[a])
        behind = s - metres
        others = st.running & ~st.in_pit
        others[a] = False
        rear = st.s_m[others & (st.s_m < s)]
        if rear.size:  # never back past (or into the follow gap of) the car behind
            behind = max(behind, min(s, float(rear.max()) + self.cfg.follow_gap_m))
        st.s_m[a] = max(behind, 0.0)
        self._resync_loops(a, st, None)

    def _resync_loops(self, i: int, st: K.KernelState, t_s: float | None) -> None:
        """Point car ``i``'s next timing loop at its new position.

        Loops it jumped forward over are stamped at ``t_s``; loops it moved back
        behind are passed again later.
        """
        if self.loops_m.size == 0:
            return
        old_next = int(st.next_loop[i])
        new_next = int(np.searchsorted(self.loops_m, st.s_m[i], side="right"))
        if t_s is not None:
            for j in range(old_next, new_next):
                st.loop_time_s[i, j] = t_s
                st.loop_lap[i, j] = st.lap[i]
        st.next_loop[i] = new_next
