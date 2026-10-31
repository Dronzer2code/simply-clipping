"""Energy-spreading MGU-K allocation (owner round 14, T-02A Change 2).

The lap's energy budget goes to the acceleration runs (corner exits at full
throttle, from the speed profile) in order of lap-time gain per MJ: the slowest
exits first, where a joule buys the most speed. Each run draws from its start
(the lowest speed) until its share is spent, so the battery lasts the lap
instead of emptying in the first sectors.

Used by the calibration deploy policy (budgets per run, super-clip at the zone
ends) and by the AI Driver's PUSH mode (a deploy level fills the same order).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pitwall_sim.car.powertrain import PowertrainParams

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
type IntArray = npt.NDArray[np.int64]

#: Shortest full-throttle run worth deploying in, m.
MIN_RUN_M = 20.0


@dataclass(frozen=True)
class DeployAllocation:
    """Acceleration runs ranked by gain per MJ, and each point's place in that order."""

    rank: IntArray
    """Run rank per point (0 = first to get energy), -1 outside full-throttle runs."""
    run_demand_j: FloatArray
    """Battery energy each run (by rank) draws at full deployment."""
    priority: FloatArray
    """Share of the ranked demand before each point (0 first .. 1 last); 1 outside runs."""

    def run_budgets(self, budget_j: float) -> FloatArray:
        """Battery energy per run (by rank) for a lap budget: fill runs in rank order."""
        before = np.concatenate(([0.0], np.cumsum(self.run_demand_j)[:-1]))
        return np.clip(max(budget_j, 0.0) - before, 0.0, self.run_demand_j)

    def deploy_fraction(self, level: float) -> FloatArray:
        """1 where the first ``level`` share (0..1) of the ranked demand is deployed, else 0."""
        return (self.priority < min(max(level, 0.0), 1.0)).astype(np.float64)


def full_throttle_runs(full: BoolArray, ds_m: float) -> list[IntArray]:
    """Contiguous full-throttle runs in lap order.

    A run that crosses the timing line is split there: a lap is driven (and its
    battery spent) from s = 0, so each part is planned where it happens.
    """
    n = full.size
    edges = np.flatnonzero(np.diff(np.concatenate(([0], full.astype(np.int8), [0]))))
    runs = [np.arange(a, b) for a, b in zip(edges[::2], edges[1::2], strict=True)]
    return [r for r in runs if r.size * ds_m >= MIN_RUN_M and r[-1] < n]


def deploy_demand_j(
    v_ms: FloatArray, accel_zone: BoolArray, ds_m: float, pt: PowertrainParams, discharge_eff: float
) -> FloatArray:
    """Battery energy per point at full deployment along a speed trace (no Overtake, no boost)."""
    v = np.maximum(v_ms, 1.0)
    span = max(pt.boost_taper_end_ms - pt.boost_taper_start_ms, 1e-9)
    taper = np.clip((pt.boost_taper_end_ms - v) / span, 0.0, 1.0)
    cap = np.where(accel_zone, pt.zone_cap_acceleration_w, pt.zone_cap_other_w)
    p_k = np.minimum(cap, pt.p_k_max_w * taper)
    return p_k * (ds_m / v) / discharge_eff


def allocate(
    v_ref_ms: FloatArray,
    full_throttle: BoolArray,
    accel_zone: BoolArray,
    ds_m: float,
    pt: PowertrainParams,
    discharge_eff: float,
) -> DeployAllocation:
    """Rank the full-throttle runs by entry speed (slowest first) and order their points."""
    n = v_ref_ms.size
    runs = sorted(full_throttle_runs(full_throttle, ds_m), key=lambda r: float(v_ref_ms[r[0]]))
    demand = deploy_demand_j(v_ref_ms, accel_zone, ds_m, pt, discharge_eff)
    rank = np.full(n, -1, dtype=np.int64)
    priority = np.ones(n, dtype=np.float64)
    run_demand = np.array([float(demand[r].sum()) for r in runs], dtype=np.float64)
    total = float(run_demand.sum())
    done = 0.0
    for k, run in enumerate(runs):
        rank[run] = k
        if total > 0.0:
            priority[run] = (done + np.concatenate(([0.0], np.cumsum(demand[run])[:-1]))) / total
        done += run_demand[k]
    return DeployAllocation(rank, run_demand, priority)


def profile_full_throttle(
    v_accel: FloatArray, v_brake: FloatArray, v_corner: FloatArray
) -> BoolArray:
    """Points where the speed profile is power-limited (accelerating at full throttle)."""
    return (v_accel <= np.minimum(v_brake, v_corner) + 1e-6) & (np.roll(v_accel, -1) > v_accel)
