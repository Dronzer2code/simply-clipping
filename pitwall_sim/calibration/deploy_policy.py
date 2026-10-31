"""MGU-K deploy policies for calibration laps (T-026, T-028, T-02A).

Default (owner round 14, T-02A Change 2): :func:`settle_spread`, the lap's
energy budget spread over the full-throttle runs by lap-time gain per MJ
(``car.deploy_allocation``: slowest exits first), so the battery lasts the lap,
with super-clip at the ends of the acceleration zones as in T-028. The T-028
policy (:func:`settle_deploy_anywhere`: deploy anywhere, clip the shortfall)
and the T-026 zones-only policy (:func:`settle_plan`) stay available.

T-026 policy (owner round 10):

Part of the calibration harness, not the physics model: it only decides where
the MGU-K deploys and how much, using the lap simulation's deploy-plan inputs.

- Deploy only inside ``acceleration_zone`` zones; harvest under braking everywhere.
- The lap's available energy (battery at the line + the lap's harvest) is split
  across the acceleration zones in proportion to their length.
- The harvest is not known before the lap, so the plan starts from the Rule Set
  harvest limit and is re-run with the harvest actually achieved until it
  settles.
- Super-clip (T-026 rule, default ``superclip="if_empty"``): only if the
  battery would otherwise run empty before the last zone.
- ``superclip="budget"`` (T-028 WIP, literal reading): the lap harvests its
  whole Rule Set allowance; braking supplies part and the rest is super-clipped
  at the end of every acceleration zone, shared by zone length (clip length =
  energy / clip power x speed, capped at the zone). With deployment limited to
  the acceleration zones this wastes energy at Suzuka (battery full, zones
  absorb ~4 MJ); owner decision pending, see docs/planning/TASKS.md T-028.

Written so the AI Driver (T-031) can start Energy Mode PUSH from it: the inputs
are a track config, the track grid and a function that simulates one lap.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from numba import njit
from scipy.optimize import minimize_scalar

from pitwall_sim.car.deploy_allocation import DeployAllocation
from pitwall_sim.car.lap_sim import LapResult
from pitwall_sim.config.models import TrackConfig, Zone

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
type IntArray = npt.NDArray[np.int64]
type SuperclipMode = Literal["budget", "if_empty"]

#: Battery energy below which it counts as empty, J.
EMPTY_J = 1e3
#: Relative change of the harvest estimate at which the plan has settled.
SETTLE_REL = 0.01
MAX_PASSES = 6


@dataclass(frozen=True)
class DeployPlan:
    """A deploy plan for one lap, in the lap simulation's inputs."""

    deploy_zone: IntArray
    """Zone index per point, -1 outside acceleration zones."""
    zone_budget_j: FloatArray
    """Battery energy each zone may draw."""
    superclip: BoolArray
    zone_ids: tuple[str, ...]


@dataclass(frozen=True)
class PolicyResult:
    """The settled plan and the lap it produced."""

    plan: DeployPlan
    lap: LapResult
    passes: int
    used_superclip: bool
    clip_capped_j: float = 0.0
    """Super-clip energy that did not fit in its zone (``budget`` mode)."""


def _in_zone(zone: Zone, s_m: FloatArray) -> BoolArray:
    if zone.s_start_m <= zone.s_end_m:
        return (s_m >= zone.s_start_m) & (s_m < zone.s_end_m)
    return (s_m >= zone.s_start_m) | (s_m < zone.s_end_m)


def acceleration_zone_index(
    track: TrackConfig, s_m: FloatArray
) -> tuple[IntArray, tuple[str, ...]]:
    """Zone index per point for the ``acceleration_zone`` zones, -1 elsewhere."""
    index = np.full(s_m.size, -1, dtype=np.int64)
    ids: list[str] = []
    for zone in track.zones:
        if "acceleration_zone" in zone.tags:
            index[_in_zone(zone, s_m) & (index < 0)] = len(ids)
            ids.append(zone.zone_id)
    return index, tuple(ids)


def split_by_length(zone_index: IntArray, n_zones: int, energy_j: float) -> FloatArray:
    """Share ``energy_j`` across zones in proportion to their length (points)."""
    lengths = np.bincount(zone_index[zone_index >= 0], minlength=n_zones).astype(np.float64)
    total = lengths.sum()
    if total <= 0.0:
        return np.zeros(n_zones, dtype=np.float64)
    return max(energy_j, 0.0) * lengths / total


def _last_zone_start(zone_index: IntArray) -> int:
    """First point of the zone that ends last on the lap (the lap's last deploy)."""
    inside = np.flatnonzero(zone_index >= 0)
    if inside.size == 0:
        return zone_index.size
    last_zone = zone_index[inside[-1]]
    i = inside[-1]
    while i > 0 and zone_index[i - 1] == last_zone:
        i -= 1
    return int(i)


def runs_empty_early(lap: LapResult, zone_index: IntArray) -> bool:
    """Check whether the battery is empty somewhere before the last zone starts."""
    end = _last_zone_start(zone_index)
    return bool(end > 0 and np.min(lap.battery_j[:end]) <= EMPTY_J)


def _zone_end_part(zone_index: IntArray, z: int) -> IntArray:
    """Points of zone ``z`` up to its end, in lap order (a zone crossing s = 0 ends low)."""
    points = np.flatnonzero(zone_index == z)
    gap = np.flatnonzero(np.diff(points) > 1)
    return points[: gap[0] + 1] if gap.size else points


def superclip_by_energy(
    zone_index: IntArray, lap: LapResult, zone_clip_j: FloatArray, clip_power_w: float
) -> tuple[BoolArray, float]:
    """Mark the last metres of each zone so super-clipping harvests ``zone_clip_j[z]``.

    A zone's clip length is ``energy / clip_power * v`` at its end speed, capped
    at the zone. Returns the mask and the energy that did not fit (capped).
    """
    mask = np.zeros(zone_index.size, dtype=np.bool_)
    if clip_power_w <= 0.0:
        return mask, float(np.sum(zone_clip_j))
    ds = float(lap.s_m[1] - lap.s_m[0])
    capped_j = 0.0
    for z, energy_j in enumerate(zone_clip_j):
        if energy_j <= 0.0:
            continue
        end_part = _zone_end_part(zone_index, z)
        v_end = float(lap.v_ms[end_part[-1]])
        wanted = int(math.ceil(energy_j / clip_power_w * v_end / ds))
        n_clip = min(wanted, end_part.size)
        if wanted > n_clip:
            capped_j += energy_j * (wanted - n_clip) / wanted
        mask[end_part[end_part.size - n_clip :]] = True
    return mask, capped_j


def superclip_mask(
    zone_index: IntArray, lap: LapResult, shortfall_j: float, clip_power_w: float
) -> BoolArray:
    """Mark the last metres of each zone, sized so super-clipping covers ``shortfall_j``.

    Each zone gets an equal share of the shortfall; its length in metres is
    ``share / clip_power * v`` at that zone's end speed.
    """
    n_zones = int(zone_index.max()) + 1 if (zone_index >= 0).any() else 0
    if n_zones == 0 or shortfall_j <= 0.0:
        return np.zeros(zone_index.size, dtype=np.bool_)
    shares = np.full(n_zones, shortfall_j / n_zones)
    return superclip_by_energy(zone_index, lap, shares, clip_power_w)[0]


def settle_plan(
    track: TrackConfig,
    s_m: FloatArray,
    battery_start_j: float,
    harvest_limit_j: float,
    clip_power_w: float,
    run_lap: Callable[[DeployPlan], LapResult],
    superclip: SuperclipMode = "if_empty",
) -> PolicyResult:
    """Settle the deploy plan for one lap.

    ``superclip="budget"`` (T-028 WIP, literal reading): the lap
    harvests its whole Rule Set allowance. Braking supplies part; the rest is
    super-clipped at the end of every acceleration zone, shared by zone length,
    and the deploy budget is battery + the whole allowance. The braking share
    is re-measured until it settles.

    ``superclip="if_empty"`` (T-026 behaviour): deploy budget = battery + the
    harvest actually achieved; super-clip only if the battery would run empty
    before the last zone.
    """
    if superclip == "budget":
        return _settle_budget(track, s_m, battery_start_j, harvest_limit_j, clip_power_w, run_lap)
    return _settle_if_empty(track, s_m, battery_start_j, harvest_limit_j, clip_power_w, run_lap)


def _settle_budget(
    track: TrackConfig,
    s_m: FloatArray,
    battery_start_j: float,
    harvest_limit_j: float,
    clip_power_w: float,
    run_lap: Callable[[DeployPlan], LapResult],
) -> PolicyResult:
    zone_index, ids = acceleration_zone_index(track, s_m)
    budget = split_by_length(zone_index, len(ids), battery_start_j + harvest_limit_j)
    plan = DeployPlan(zone_index, budget, np.zeros(s_m.size, dtype=np.bool_), ids)
    lap = run_lap(plan)
    braking_j = lap.harvested_j - lap.superclip_j
    capped_j = 0.0
    passes = 1
    while passes < MAX_PASSES:
        clip_j = split_by_length(zone_index, len(ids), max(harvest_limit_j - braking_j, 0.0))
        mask, capped_j = superclip_by_energy(zone_index, lap, clip_j, clip_power_w)
        plan = DeployPlan(zone_index, budget, mask, ids)
        lap = run_lap(plan)
        passes += 1
        new_braking_j = lap.harvested_j - lap.superclip_j
        settled = abs(new_braking_j - braking_j) <= SETTLE_REL * max(braking_j, 1.0)
        braking_j = new_braking_j
        if settled:
            break
    return PolicyResult(plan, lap, passes, bool(plan.superclip.any()), capped_j)


def _settle_if_empty(
    track: TrackConfig,
    s_m: FloatArray,
    battery_start_j: float,
    harvest_limit_j: float,
    clip_power_w: float,
    run_lap: Callable[[DeployPlan], LapResult],
) -> PolicyResult:
    zone_index, ids = acceleration_zone_index(track, s_m)
    harvest_j = harvest_limit_j
    no_clip = np.zeros(s_m.size, dtype=np.bool_)
    plan = DeployPlan(
        zone_index, split_by_length(zone_index, len(ids), battery_start_j + harvest_j), no_clip, ids
    )
    lap = run_lap(plan)
    passes = 1
    while passes < MAX_PASSES:
        achieved = lap.harvested_j
        if abs(achieved - harvest_j) <= SETTLE_REL * max(harvest_j, 1.0):
            break
        harvest_j = achieved
        budget = split_by_length(zone_index, len(ids), battery_start_j + harvest_j)
        plan = DeployPlan(zone_index, budget, no_clip, ids)
        lap = run_lap(plan)
        passes += 1

    if not runs_empty_early(lap, zone_index):
        return PolicyResult(plan, lap, passes, used_superclip=False)

    assert lap.zone_drawn_j is not None
    shortfall = float(np.sum(np.maximum(plan.zone_budget_j - lap.zone_drawn_j, 0.0)))
    clip = superclip_mask(zone_index, lap, shortfall, clip_power_w)
    plan = DeployPlan(zone_index, plan.zone_budget_j, clip, ids)
    return PolicyResult(plan, run_lap(plan), passes + 1, used_superclip=True)


#: Super-clip energies below this are not worth a clip, J.
MIN_CLIP_J = 5e4
#: Resolution of the clip-energy search, J.
CLIP_TOL_J = 5e4
CLIP_SEARCH_ITER = 8


def settle_deploy_anywhere(
    track: TrackConfig,
    s_m: FloatArray,
    harvest_limit_j: float,
    clip_power_w: float,
    run_lap: Callable[[DeployPlan], LapResult],
) -> PolicyResult:
    """Owner decision for T-028, option (c): deploy anywhere, clip the shortfall.

    The MGU-K deploys wherever the car is at full throttle, within the Rule Set
    caps (one zone with an unlimited budget: the battery is the only limit).
    If that lap is energy-limited, the end of every acceleration zone
    super-clips to fund deployment elsewhere (real 2026 qualifying behaviour).
    The clip energy is at most the shortfall (deployment the battery could not
    supply) and the harvest allowance left after braking; within that range it
    is the amount that gives the fastest lap, shared across the zones by length.
    """
    zone_index, _ = acceleration_zone_index(track, s_m)
    anywhere = np.zeros(s_m.size, dtype=np.int64)
    unlimited = np.array([math.inf])
    no_clip = np.zeros(s_m.size, dtype=np.bool_)
    base_plan = DeployPlan(anywhere, unlimited, no_clip, ("anywhere",))
    base = run_lap(base_plan)
    braking_j = base.harvested_j - base.superclip_j
    max_clip_j = min(base.unmet_deploy_j, max(harvest_limit_j - braking_j, 0.0))
    n_zones = int(zone_index.max()) + 1 if (zone_index >= 0).any() else 0
    if max_clip_j < MIN_CLIP_J or n_zones == 0:
        return PolicyResult(base_plan, base, 1, used_superclip=False)

    tried: dict[float, tuple[DeployPlan, LapResult, float]] = {0.0: (base_plan, base, 0.0)}

    def lap_time(clip_j: float) -> float:
        energies = split_by_length(zone_index, n_zones, clip_j)
        mask, capped = superclip_by_energy(zone_index, base, energies, clip_power_w)
        plan = DeployPlan(anywhere, unlimited, mask, ("anywhere",))
        lap = run_lap(plan)
        tried[clip_j] = (plan, lap, capped)
        return lap.lap_time_s

    minimize_scalar(
        lap_time,
        bounds=(0.0, max_clip_j),
        method="bounded",
        options={"xatol": CLIP_TOL_J, "maxiter": CLIP_SEARCH_ITER},
    )
    best = min(tried, key=lambda e: tried[e][1].lap_time_s)
    plan, lap, capped = tried[best]
    return PolicyResult(plan, lap, len(tried), bool(plan.superclip.any()), capped)


#: Battery kept back until the line while planning (STRUCTURAL, owner round 14:
#: "must not hit 0 before the last acceleration zone"; absorbs harvest estimate error).
PLAN_FLOOR_J = 0.2e6
#: Funding sweeps over the ranked runs (a later sweep re-uses energy that
#: funding earlier runs saved from overflowing a full battery).
FUND_SWEEPS = 2


@njit(cache=True)
def _path_min(
    battery_start_j: float, harvest_j: FloatArray, draw_j: FloatArray, e_max_j: float
) -> tuple[float, float]:
    """Lowest planned battery before the line, and the battery at the line.

    ``B = min(e_max, B + harvest - draw)`` point by point (overflow is lost).
    """
    b = battery_start_j
    lowest = math.inf
    for i in range(harvest_j.size):
        b = min(e_max_j, b + harvest_j[i] - draw_j[i])
        if i < harvest_j.size - 1 and b < lowest:
            lowest = b
    return lowest, b


@njit(cache=True)
def _fund(
    battery_start_j: float,
    harvest_j: FloatArray,
    e_max_j: float,
    first: IntArray,
    demand_j: FloatArray,
    floor_j: float,
    end_target_j: float,
    sweeps: int,
) -> FloatArray:
    budgets = np.zeros(demand_j.size)
    draw = np.zeros(harvest_j.size)
    for _ in range(sweeps):
        for r in range(demand_j.size):
            if first[r] < 0 or budgets[r] >= demand_j[r]:
                continue
            lo, hi = 0.0, demand_j[r] - budgets[r]
            for _ in range(30):  # largest extra share that keeps the path feasible
                mid = 0.5 * (lo + hi)
                draw[first[r]] += mid
                lowest, end = _path_min(battery_start_j, harvest_j, draw, e_max_j)
                draw[first[r]] -= mid
                if lowest >= floor_j and end >= end_target_j:
                    lo = mid
                else:
                    hi = mid
            draw[first[r]] += lo
            budgets[r] += lo
    return budgets


def feasible_budgets(
    alloc: DeployAllocation,
    battery_start_j: float,
    harvest_j: FloatArray,
    e_max_j: float,
    end_target_j: float,
) -> FloatArray:
    """Battery energy per run (by rank) along a feasible battery path.

    Runs are funded in rank order (slowest exits first), each with the most that
    keeps the planned battery (start + harvest so far - deployment so far,
    capped at ``e_max`` where harvest would overflow) above ``PLAN_FLOOR_J``
    until the line and at ``end_target_j`` or more at the line. A run's share
    is drawn at its first point (conservative). ``harvest_j`` is the expected
    harvest per point.
    """
    first = np.array(
        [int(np.flatnonzero(alloc.rank == r).min()) if (alloc.rank == r).any() else -1
         for r in range(alloc.run_demand_j.size)], dtype=np.int64,
    )  # fmt: skip
    return _fund(
        battery_start_j, np.ascontiguousarray(harvest_j, dtype=np.float64), e_max_j, first,
        alloc.run_demand_j, PLAN_FLOOR_J, end_target_j, FUND_SWEEPS,
    )  # fmt: skip


def _harvest_per_point(lap: LapResult, harvest_limit_j: float) -> FloatArray:
    """Return the expected harvest per point: offered energy within the lap limit."""
    offered = lap.harvest_offered_j
    if offered is None:
        return np.zeros(lap.s_m.size, dtype=np.float64)
    capped = np.minimum(np.cumsum(offered), harvest_limit_j)
    return np.diff(capped, prepend=0.0)


def settle_spread(
    track: TrackConfig,
    s_m: FloatArray,
    alloc: DeployAllocation,
    battery_start_j: float,
    end_target_j: float,
    harvest_limit_j: float,
    clip_power_w: float,
    run_lap: Callable[[DeployPlan], LapResult],
    e_max_j: float = math.inf,
) -> PolicyResult:
    """Owner round 14, Change 2: spread the lap's energy over the runs by gain per MJ.

    Budget = battery at the line - ``end_target_j`` + the lap's harvest (braking
    plus super-clip), handed to the full-throttle runs in rank order
    (:func:`feasible_budgets`: never empty before a funded run). The harvest is
    not known before the lap: plan from a lap without deployment, then re-plan
    with each lap's offered harvest until the budgets settle. The super-clip
    energy (at the ends of the acceleration zones, shared by length, at most the
    allowance braking leaves) is the amount that gives the fastest lap.
    """
    zone_index, ids = acceleration_zone_index(track, s_m)
    n_zones = len(ids)
    no_clip = np.zeros(s_m.size, dtype=np.bool_)
    zero = np.zeros(alloc.run_demand_j.size, dtype=np.float64)
    passes = 0

    def settled(clip: BoolArray) -> tuple[DeployPlan, LapResult]:
        nonlocal passes
        lap = run_lap(DeployPlan(alloc.rank, zero, clip, ("spread",)))
        passes += 1
        budgets = zero
        plan = DeployPlan(alloc.rank, zero, clip, ("spread",))
        for _ in range(MAX_PASSES):
            new = feasible_budgets(
                alloc, battery_start_j, _harvest_per_point(lap, harvest_limit_j), e_max_j,
                end_target_j,
            )  # fmt: skip
            if passes > 1 and np.abs(new - budgets).sum() <= SETTLE_REL * max(new.sum(), 1.0):
                break
            budgets = new
            plan = DeployPlan(alloc.rank, budgets, clip, ("spread",))
            lap = run_lap(plan)
            passes += 1
        return plan, lap

    base_plan, base = settled(no_clip)
    braking = base.harvested_j - base.superclip_j
    max_clip_j = max(harvest_limit_j - braking, 0.0)
    if max_clip_j < MIN_CLIP_J or n_zones == 0:
        return PolicyResult(base_plan, base, passes, used_superclip=False)

    tried: dict[float, tuple[DeployPlan, LapResult, float]] = {0.0: (base_plan, base, 0.0)}

    def lap_time(clip_j: float) -> float:
        energies = split_by_length(zone_index, n_zones, clip_j)
        mask, capped = superclip_by_energy(zone_index, base, energies, clip_power_w)
        plan, lap = settled(mask)
        tried[clip_j] = (plan, lap, capped)
        return lap.lap_time_s

    minimize_scalar(
        lap_time,
        bounds=(0.0, max_clip_j),
        method="bounded",
        options={"xatol": CLIP_TOL_J, "maxiter": CLIP_SEARCH_ITER},
    )
    best = min(tried, key=lambda e: tried[e][1].lap_time_s)
    plan, lap, capped = tried[best]
    return PolicyResult(plan, lap, passes, bool(plan.superclip.any()), capped)
