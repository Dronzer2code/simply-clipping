"""F05 Numba per-step physics kernel for all cars (T-030, TRD Per-step order step 4).

One fixed time step (``sim.dt_s``) for every car at once::

    throttle/brake -> aero mode -> forces (friction ellipse, power, drag,
    rolling) -> v, s -> battery (harvest, deploy, per-lap limits) -> fuel -> tyres

The formulas are the ones in ``car/dynamics.py``, ``car/powertrain.py``,
``car/battery.py``, ``car/fuel.py`` and ``car/tyres.py``, re-stated here as
compiled loops over parallel arrays (CLAUDE.md "Hot loop": no Python objects
inside). ``tests/unit/test_step_kernel.py`` checks the kernel against those
Python functions, and a single car driven by :func:`track_speed` against the
T-025 lap simulation.

Inputs are ``NamedTuple``s of arrays (one element per car) built from config by
:func:`build_kernel`. Units are SI throughout.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple, cast

import numpy as np
import numpy.typing as npt
from numba import njit

from pitwall_sim.car.aero import aero_params
from pitwall_sim.car.battery import battery_params, superclip_harvest_w
from pitwall_sim.car.dirty_air import (
    dirty_air_params,
    downforce_scale,
    drag_scale,
    gaps_ahead_m,
    wake_factor,
)
from pitwall_sim.car.dynamics import G_MS2, corner_speed_ms, load_factor, track_air_density
from pitwall_sim.car.fuel import fuel_params
from pitwall_sim.car.powertrain import powertrain_params
from pitwall_sim.car.tyres import tyre_params
from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import (
    AppConfig,
    Compound,
    RuleSet,
    TeamPerformanceConfig,
    TrackConfig,
    TyreConfig,
)
from pitwall_sim.track.builder import TrackModel
from pitwall_sim.track.zones import zone_mask

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
type IntArray = npt.NDArray[np.int64]

#: ``aero_mode`` codes, matching ``race.state.AERO_MODES``.
STRAIGHT_MODE = 0
CORNER_MODE = 1


def jit[F: Callable[..., Any]](func: F) -> F:
    """``numba.njit(cache=True)`` with the function's type kept for mypy."""
    return cast(F, njit(cache=True)(func))


def jit_inline[F: Callable[..., Any]](func: F) -> F:
    """Compile and always inline into the caller.

    The helpers take the ``NamedTuple``s of arrays; an ordinary call passes them
    by value and touches every array's reference count (~50 arrays), which cost
    ~2.7 us per car per step. Inlined, that overhead disappears.
    """
    return cast(F, njit(cache=True, inline="always")(func))


class KernelTrack(NamedTuple):
    """Track grid and zone masks (one element per ``ds`` metres)."""

    kappa: FloatArray
    straight_mode: BoolArray
    accel_zone: BoolArray
    ds_m: float
    length_m: float
    loops_m: FloatArray
    """Timing loops in (0, length), ascending: sector ends, mini-sectors, detection (T-033)."""


class KernelGlobals(NamedTuple):
    """Rule Set, air and structural values shared by every car."""

    rho: float
    v_min_ms: float
    boost_taper_start_ms: float
    boost_taper_end_ms: float
    overtake_taper_start_ms: float
    overtake_taper_end_ms: float
    zone_cap_acceleration_w: float
    zone_cap_other_w: float
    boost_net_cap_w: float
    superclip_w: float
    harvest_max_w: float
    wear_norm_j: float
    abrasiveness: float
    straight_mode_throttle_min: float
    wake_range_m: float
    downforce_loss_max: float
    drag_reduction_max: float
    follow_gap_m: float
    """Closest a car gets to the car ahead without an overtake (T-034)."""
    pit_speed_ms: float
    """Pit-lane speed limit (T-035)."""
    pit_limit_start_m: float
    pit_limit_end_m: float
    """Where the limit applies (may cross s = 0)."""
    pit_entry_decel_ms2: float
    """Braking towards the limit line on the pit entry road."""
    n_ref_n: float
    k_load: float
    """Tyre load sensitivity (owner round 14)."""
    lift_min_speed_share: float
    """The plan's throttle cap applies only at or above this share of ``v_ref`` (T-037)."""


class KernelCars(NamedTuple):
    """Per-car coefficients (team, power unit, battery, fuel, current tyre)."""

    mass_min_kg: FloatArray
    cda_straight: FloatArray
    cda_corner: FloatArray
    cla_straight: FloatArray
    cla_corner: FloatArray
    long_grip_ratio: FloatArray
    driveline_efficiency: FloatArray
    p_ice_max_w: FloatArray
    p_k_max_w: FloatArray
    discharge_efficiency: FloatArray
    brake_harvest_share: FloatArray
    partial_harvest_max_w: FloatArray
    harvest_limit_j: FloatArray
    overtake_extra_j: FloatArray
    e_usable_max_j: FloatArray
    ice_efficiency: FloatArray
    fuel_energy_density_j_per_kg: FloatArray
    max_fuel_flow_w: FloatArray
    mu_base: FloatArray
    k_wear: FloatArray
    cliff_w: FloatArray
    a_wear: FloatArray
    b_wear: FloatArray
    c_rr: FloatArray


class KernelControls(NamedTuple):
    """What each driver asks for this step (set by the AI Driver, T-031)."""

    throttle: FloatArray
    brake: FloatArray
    deploy_fraction: FloatArray
    overtake_active: BoolArray
    boost_active: BoolArray
    boost_total_w: FloatArray
    superclip: BoolArray
    part_harvest: BoolArray
    """Harvest at part throttle and while coasting (not braking), up to ``partial_harvest_max``."""
    mgmt_factor: FloatArray
    grip_factor: FloatArray
    speed_scale: FloatArray
    """Share of the plan's reference speed a car may run (1 = green; SC / VSC lower it)."""


class KernelState(NamedTuple):
    """Ground Truth the kernel advances (SI; ``CarState`` keeps MJ at its boundary)."""

    s_m: FloatArray
    v_ms: FloatArray
    lap: IntArray
    battery_j: FloatArray
    harvest_lap_j: FloatArray
    deploy_lap_j: FloatArray
    tyre_wear: FloatArray
    fuel_kg: FloatArray
    aero_mode: IntArray
    running: BoolArray
    line_time_s: FloatArray
    """Sim time of each car's last timing-line crossing (interpolated within the step)."""
    power_w: FloatArray
    """ICE + MGU-K power in the last step (boost records it at activation)."""
    p_k_w: FloatArray
    """MGU-K deploy power in the last step (Ground Truth export, sprint S-1)."""
    p_harvest_w: FloatArray
    """Power harvested into the battery in the last step (energy / dt)."""
    superclip_on: BoolArray
    """Super-clipping in the last step."""
    taper_limited: BoolArray
    """Deploying with the MGU-K limit set by the speed taper (below the zone cap)."""
    gap_ahead_m: FloatArray
    """Distance to the nearest running car ahead on the road at the step's start (T-032)."""
    ahead_idx: IntArray
    """Index of that car (-1 when alone)."""
    in_pit: BoolArray
    """In the pit lane: speed-limited, ignored by and ignoring cars on track (T-035)."""
    next_loop: IntArray
    """Index of the next timing loop each car will pass this lap (T-033)."""
    loop_time_s: FloatArray
    """(cars, loops): sim time of each car's last pass of each loop (interpolated)."""
    loop_lap: IntArray
    """(cars, loops): the car's ``lap`` at that pass."""


# --------------------------------------------------------------------------- #
# Scalar physics (compiled)
# --------------------------------------------------------------------------- #


@jit_inline
def _taper(v: float, start: float, end: float) -> float:
    if v <= start:
        return 1.0
    if v >= end:
        return 0.0
    return (end - v) / (end - start)


@jit_inline
def _f_wear(wear: float, cliff: float, a: float, b: float) -> float:
    w = min(max(wear, 0.0), 1.0)
    factor = 1.0 - a * w if w < cliff else 1.0 - a * cliff - b * (w - cliff)
    return max(factor, 0.0)


@jit_inline
def _index(s: float, ds: float, n: int) -> int:
    return int(s / ds) % n


@jit_inline
def _corner_speed(
    kappa: float, mu_lat: float, mass: float, rho: float, cl: float, n_ref: float, k_load: float
) -> float:
    """Grip-limited speed (``dynamics.corner_speed_ms``); ``inf`` where unlimited."""
    return corner_speed_ms(kappa, mu_lat, mass, rho, cl, n_ref, k_load)


@jit_inline
def _car_forces(
    dt: float,
    v: float,
    throttle: float,
    kappa: float,
    in_straight_mode_zone: bool,
    in_accel_zone: bool,
    mass: float,
    mu_lat: float,
    long_grip_ratio: float,
    cd_straight: float,
    cd_corner: float,
    cl_straight: float,
    cl_corner: float,
    eta: float,
    p_ice_max: float,
    ice_eff: float,
    fuel_flow_max: float,
    p_k_max: float,
    discharge_eff: float,
    battery_j: float,
    c_rr: float,
    deploy_fraction: float,
    overtake: bool,
    boost: bool,
    boost_total_w: float,
    superclip: bool,
    part_harvest: bool,
    partial_harvest_max_w: float,
    glb: KernelGlobals,
) -> tuple[float, float, float, float, float, float, float, int, float]:
    """Compute forces and power split for one car at one throttle (scalar arguments only).

    Returns ``(drive_n, grip_long_n, resist_n, p_ice_w, p_k_w, p_clip_w, p_part_w,
    mode, cl)``. ``glb`` is a tuple of floats, cheap to pass.

    Part-throttle harvest (TRD Battery, ``part_harvest`` below full throttle): the
    MGU-K takes ``p_part_w``; the ICE's spare power covers it at part throttle,
    the rest comes from the car's motion (a retarding force in ``resist_n``; all
    of it while coasting).
    """
    mode = (
        STRAIGHT_MODE
        if in_straight_mode_zone and throttle >= glb.straight_mode_throttle_min
        else CORNER_MODE
    )
    cd = cd_straight if mode == STRAIGHT_MODE else cd_corner
    cl = cl_straight if mode == STRAIGHT_MODE else cl_corner
    normal = mass * G_MS2 + 0.5 * glb.rho * cl * v * v
    mu_n = mu_lat * load_factor(normal, glb.n_ref_n, glb.k_load)  # load sensitivity
    lat_grip = mu_n * normal / mass
    used = v * v * abs(kappa) / lat_grip if lat_grip > 0.0 else 1.0
    ellipse = math.sqrt(1.0 - used * used) if used < 1.0 else 0.0
    grip_long_n = mu_n * long_grip_ratio * normal * ellipse

    # ICE (fuel-flow capped), then MGU-K within zone cap, taper, boost cap and battery.
    p_ice_full = min(p_ice_max, ice_eff * fuel_flow_max)
    taper = (
        _taper(v, glb.overtake_taper_start_ms, glb.overtake_taper_end_ms)
        if overtake
        else _taper(v, glb.boost_taper_start_ms, glb.boost_taper_end_ms)
    )
    cap = glb.zone_cap_acceleration_w if in_accel_zone else glb.zone_cap_other_w
    p_k_allowed = min(cap, p_k_max * taper)
    if boost:
        p_k_allowed = min(p_k_allowed, max(boost_total_w + glb.boost_net_cap_w - p_ice_full, 0.0))
    p_k_full = min(deploy_fraction * p_k_allowed, max(battery_j, 0.0) * discharge_eff / dt)
    p_clip = glb.superclip_w if superclip else 0.0
    if p_clip > 0.0:
        p_k_full = 0.0  # the MGU-K harvests instead of deploying

    demand = max(throttle, 0.0) * (p_ice_full + p_k_full)
    p_ice = min(demand, p_ice_full)
    p_k = min(max(demand - p_ice, 0.0), p_k_full)
    wheel_w = max(eta * (p_ice + p_k - p_clip), 0.0)
    drive_n = min(wheel_w / max(v, glb.v_min_ms), grip_long_n) if throttle > 0.0 else 0.0
    resist_n = 0.5 * glb.rho * cd * v * v + c_rr * normal
    p_part = 0.0
    if part_harvest and p_clip == 0.0 and throttle < 1.0:
        p_part = min(partial_harvest_max_w, glb.harvest_max_w)
        ice_extra = min(p_ice_full - p_ice, p_part) if throttle > 0.0 else 0.0
        p_ice += ice_extra
        # From the car's motion: never more retarding force than the tyres give.
        resist_n += min((p_part - ice_extra) / max(v, glb.v_min_ms), grip_long_n)
    return drive_n, grip_long_n, resist_n, p_ice, p_k, p_clip, p_part, mode, cl


@jit
def step(
    dt: float,
    trk: KernelTrack,
    glb: KernelGlobals,
    car: KernelCars,
    ctl: KernelControls,
    st: KernelState,
    t_s: float = 0.0,
) -> None:
    """Advance every running car by ``dt`` seconds (arrays in ``st`` updated in place).

    ``t_s`` is the sim time at the start of the step, used to time-stamp
    timing-line crossings in ``st.line_time_s``. A car within the wake range of
    the car ahead (``st.gap_ahead_m``) has less downforce and drag (T-032), and
    cannot close to less than ``follow_gap_m`` behind it (T-034).
    """
    n_pts = trk.kappa.size
    if st.loop_time_s.shape[1] != trk.loops_m.size:
        raise ValueError("KernelState timing loops do not match the track's")
    gaps_ahead_m(st.s_m, st.running, st.in_pit, trk.length_m, st.gap_ahead_m, st.ahead_idx)
    v_start = st.v_ms.copy()
    for i in range(st.s_m.size):
        if not st.running[i]:
            continue
        s, v = st.s_m[i], st.v_ms[i]
        throttle = min(max(ctl.throttle[i], 0.0), 1.0)
        brake = min(max(ctl.brake[i], 0.0), 1.0)
        k = _index(s, trk.ds_m, n_pts)
        mass = car.mass_min_kg[i] + max(st.fuel_kg[i], 0.0)
        mu_lat = (
            car.mu_base[i]
            * _f_wear(st.tyre_wear[i], car.cliff_w[i], car.a_wear[i], car.b_wear[i])
            * ctl.grip_factor[i]
        )
        wake = wake_factor(st.gap_ahead_m[i], glb.wake_range_m)
        drag = drag_scale(wake, glb.drag_reduction_max)
        down = downforce_scale(wake, glb.downforce_loss_max)
        drive_n, brake_max_n, resist_n, p_ice, p_k, p_clip, p_part, mode, cl = _car_forces(
            dt, v, throttle, trk.kappa[k], trk.straight_mode[k], trk.accel_zone[k], mass,
            mu_lat, car.long_grip_ratio[i], car.cda_straight[i] * drag,
            car.cda_corner[i] * drag, car.cla_straight[i] * down, car.cla_corner[i] * down,
            car.driveline_efficiency[i],
            car.p_ice_max_w[i] if st.fuel_kg[i] > 0.0 else 0.0,  # no fuel, no ICE
            car.ice_efficiency[i], car.max_fuel_flow_w[i], car.p_k_max_w[i],
            car.discharge_efficiency[i], st.battery_j[i], car.c_rr[i], ctl.deploy_fraction[i],
            ctl.overtake_active[i], ctl.boost_active[i], ctl.boost_total_w[i],
            ctl.superclip[i], ctl.part_harvest[i] and brake == 0.0, car.partial_harvest_max_w[i],
            glb,
        )  # fmt: skip
        brake_n = brake * brake_max_n
        accel = (drive_n - brake_n - resist_n) / mass
        v_new = max(v + accel * dt, 0.0)
        s_new = s + 0.5 * (v + v_new) * dt
        # No passing without an overtake (T-034): stay follow_gap_m behind the car
        # ahead, at most at its speed. Overtakes swap the cars outside the kernel.
        a = st.ahead_idx[i]
        if a >= 0:
            room = st.gap_ahead_m[i] - glb.follow_gap_m + v_start[a] * dt
            if s_new - s > room:
                s_new = s + max(room, 0.0)
                v_new = min(v_new, v_start[a])
        # A car cannot corner above its grip: at the new point speed is capped at the
        # corner speed (it scrubs off the excess, as the lap simulation's cap does).
        k_new = _index(s_new, trk.ds_m, n_pts)
        v_new = min(
            v_new,
            _corner_speed(trk.kappa[k_new], mu_lat, mass, glb.rho, cl, glb.n_ref_n, glb.k_load),
        )

        # Battery: harvest (super-clip, part throttle / coasting, or braking share) up
        # to the lap allowance and the window's room, then draw P_k / eta (may use
        # this step's harvest).
        if p_clip > 0.0:
            p_harvest = p_clip
        elif p_part > 0.0:
            p_harvest = p_part
        else:
            p_harvest = min(glb.harvest_max_w, brake_n * v * car.brake_harvest_share[i])
        limit = car.harvest_limit_j[i] + (
            car.overtake_extra_j[i] if ctl.overtake_active[i] else 0.0
        )
        battery = min(max(st.battery_j[i], 0.0), car.e_usable_max_j[i])
        harvested = min(
            p_harvest * dt,
            max(limit - st.harvest_lap_j[i], 0.0),
            car.e_usable_max_j[i] - battery,
        )
        drawn = min(p_k * dt / car.discharge_efficiency[i], battery + harvested)
        st.battery_j[i] = min(max(battery + harvested - drawn, 0.0), car.e_usable_max_j[i])
        st.harvest_lap_j[i] += harvested
        st.deploy_lap_j[i] += drawn
        st.p_k_w[i] = p_k
        st.p_harvest_w[i] = harvested / dt
        st.superclip_on[i] = p_clip > 0.0
        taper = (
            _taper(v, glb.overtake_taper_start_ms, glb.overtake_taper_end_ms)
            if ctl.overtake_active[i]
            else _taper(v, glb.boost_taper_start_ms, glb.boost_taper_end_ms)
        )
        zone_cap = glb.zone_cap_acceleration_w if trk.accel_zone[k] else glb.zone_cap_other_w
        st.taper_limited[i] = p_k > 0.0 and car.p_k_max_w[i] * taper < zone_cap

        # Fuel and tyres.
        flow = min(max(p_ice, 0.0) / car.ice_efficiency[i], car.max_fuel_flow_w[i])
        st.fuel_kg[i] = max(st.fuel_kg[i] - flow * dt / car.fuel_energy_density_j_per_kg[i], 0.0)
        f_lat = mass * v * v * abs(trk.kappa[k])
        work_w = (abs(drive_n - brake_n) + f_lat) * v
        rate = car.k_wear[i] * glb.abrasiveness * work_w / glb.wear_norm_j * ctl.mgmt_factor[i]
        st.tyre_wear[i] = min(st.tyre_wear[i] + max(rate, 0.0) * dt, 1.0)

        # Timing loops passed this step, then the line: new lap, per-lap counters reset.
        travelled = s_new - s
        n_loops = trk.loops_m.size
        lap_end = min(s_new, trk.length_m)
        while st.next_loop[i] < n_loops and trk.loops_m[st.next_loop[i]] <= lap_end:
            j = st.next_loop[i]
            frac = (trk.loops_m[j] - s) / travelled if travelled > 0 else 0.0
            st.loop_time_s[i, j] = t_s + dt * frac
            st.loop_lap[i, j] = st.lap[i]
            st.next_loop[i] = j + 1
        if s_new >= trk.length_m:
            st.line_time_s[i] = t_s + dt * (trk.length_m - s) / travelled if travelled > 0 else t_s
            s_new -= trk.length_m
            st.lap[i] += 1
            st.harvest_lap_j[i] = 0.0
            st.deploy_lap_j[i] = 0.0
            st.next_loop[i] = 0
            while st.next_loop[i] < n_loops and trk.loops_m[st.next_loop[i]] <= s_new:
                j = st.next_loop[i]
                frac = (trk.loops_m[j] + trk.length_m - s) / travelled
                st.loop_time_s[i, j] = t_s + dt * frac
                st.loop_lap[i, j] = st.lap[i]
                st.next_loop[i] = j + 1
        st.s_m[i] = s_new
        st.v_ms[i] = v_new
        st.aero_mode[i] = mode
        st.power_w[i] = p_ice + p_k


@jit
def track_speed(
    dt: float,
    v_target: FloatArray,
    trk: KernelTrack,
    glb: KernelGlobals,
    car: KernelCars,
    ctl: KernelControls,
    st: KernelState,
) -> None:
    """Set throttle / brake so each car reaches ``v_target`` (per car) in one step.

    Full throttle if even that is not enough, part throttle in between (solved in
    power terms: throttle scales power, not force), and the brake fraction of the
    grip-limited maximum when slowing down. The AI Driver (T-031) chooses the
    targets; this is its speed-tracking actuator.
    """
    n_pts = trk.kappa.size
    gaps_ahead_m(st.s_m, st.running, st.in_pit, trk.length_m, st.gap_ahead_m, st.ahead_idx)
    for i in range(st.s_m.size):
        if not st.running[i]:
            ctl.throttle[i] = 0.0
            ctl.brake[i] = 0.0
            continue
        v = st.v_ms[i]
        k = _index(st.s_m[i], trk.ds_m, n_pts)
        mass = car.mass_min_kg[i] + max(st.fuel_kg[i], 0.0)
        mu_lat = (
            car.mu_base[i]
            * _f_wear(st.tyre_wear[i], car.cliff_w[i], car.a_wear[i], car.b_wear[i])
            * ctl.grip_factor[i]
        )
        wake = wake_factor(st.gap_ahead_m[i], glb.wake_range_m)
        drag = drag_scale(wake, glb.drag_reduction_max)
        down = downforce_scale(wake, glb.downforce_loss_max)
        drive_n, brake_max_n, resist_n, p_ice, p_k, p_clip, _, _, _ = _car_forces(
            dt, v, 1.0, trk.kappa[k], trk.straight_mode[k], trk.accel_zone[k], mass,
            mu_lat, car.long_grip_ratio[i], car.cda_straight[i] * drag,
            car.cda_corner[i] * drag, car.cla_straight[i] * down, car.cla_corner[i] * down,
            car.driveline_efficiency[i],
            car.p_ice_max_w[i] if st.fuel_kg[i] > 0.0 else 0.0,  # no fuel, no ICE
            car.ice_efficiency[i], car.max_fuel_flow_w[i], car.p_k_max_w[i],
            car.discharge_efficiency[i], st.battery_j[i], car.c_rr[i], ctl.deploy_fraction[i],
            ctl.overtake_active[i], ctl.boost_active[i], ctl.boost_total_w[i],
            ctl.superclip[i], False, 0.0, glb,
        )  # fmt: skip
        a_need = (v_target[i] - v) / dt
        if a_need * mass >= drive_n - resist_n:
            ctl.throttle[i], ctl.brake[i] = 1.0, 0.0
        elif a_need * mass >= -resist_n:
            full_w = car.driveline_efficiency[i] * (p_ice + p_k - p_clip)
            need_n = a_need * mass + resist_n
            ctl.throttle[i] = (
                min(need_n * max(v, glb.v_min_ms) / full_w, 1.0) if full_w > 0.0 else 0.0
            )
            ctl.brake[i] = 0.0
        else:
            ctl.throttle[i] = 0.0
            need = -a_need * mass - resist_n
            ctl.brake[i] = min(need / brake_max_n, 1.0) if brake_max_n > 0.0 else 1.0


class KernelPlans(NamedTuple):
    """Per-car, per-point driving plan set by the AI Driver (T-031); shape (cars, points)."""

    v_ref: FloatArray
    """Reference speed (target where the car will be after the step)."""
    deploy: FloatArray
    """MGU-K deploy fraction at each point (energy mode)."""
    superclip: BoolArray
    """Super-clip at each point when at full throttle."""
    throttle_cap: FloatArray
    """Throttle ceiling at each point (0 = lift and coast)."""
    part_harvest: BoolArray
    """Part-throttle / coasting harvest at each point."""


def flat_plans(v_ref: FloatArray) -> KernelPlans:
    """Plans with only a reference speed: full deployment, no clip, no lift."""
    return KernelPlans(
        v_ref=v_ref,
        deploy=np.ones_like(v_ref),
        superclip=np.zeros(v_ref.shape, dtype=np.bool_),
        throttle_cap=np.ones_like(v_ref),
        part_harvest=np.zeros(v_ref.shape, dtype=np.bool_),
    )


@jit
def advance(
    n_steps: int,
    dt: float,
    t_s: float,
    plans: KernelPlans,
    trk: KernelTrack,
    glb: KernelGlobals,
    car: KernelCars,
    ctl: KernelControls,
    st: KernelState,
    stop_lap: int = 1 << 62,
) -> float:
    """Run ``n_steps`` physics steps in one compiled call; return the new sim time.

    Each step, every car reads its plan at its position: deploy fraction and
    super-clip at the current point, the reference speed where it will be after
    the step (reached with :func:`track_speed`), and the throttle cap (lift and
    coast; not in the pit lane, where the plan's lift and harvest do not apply,
    nor well below the reference speed). An active boost deploys fully. Other
    controls (Overtake, boost, tyre management, grip) stay as set; the engine
    calls this once per decision tick. The call ends early once every running car has reached lap
    ``stop_lap`` (the AI Driver's lap predictions).
    """
    n_cars = st.s_m.size
    n_pts = plans.v_ref.shape[1]
    target = np.empty(n_cars, dtype=np.float64)
    t = t_s
    for _ in range(n_steps):
        for i in range(n_cars):
            k_now = _index(st.s_m[i], trk.ds_m, n_pts)
            ctl.deploy_fraction[i] = 1.0 if ctl.boost_active[i] else plans.deploy[i, k_now]
            ctl.superclip[i] = plans.superclip[i, k_now] and not ctl.boost_active[i]
            ctl.part_harvest[i] = plans.part_harvest[i, k_now] and not ctl.boost_active[i]
            target[i] = plans.v_ref[i, _index(st.s_m[i] + st.v_ms[i] * dt, trk.ds_m, n_pts)]
            if not st.in_pit[i]:
                target[i] *= ctl.speed_scale[i]  # SC / VSC (H4); the pit lane has its limiter
            if st.in_pit[i]:
                # On the pit limiter: the plan's lift and coast and harvest do not apply
                # (a lift point at the box would hold the car at a standstill).
                ctl.superclip[i] = False
                ctl.part_harvest[i] = False
            if st.in_pit[i] and target[i] > glb.pit_speed_ms:
                # At the limit inside the window; before it, brake to reach the line at it.
                pos = (st.s_m[i] + st.v_ms[i] * dt) % trk.length_m
                to_start = (glb.pit_limit_start_m - pos) % trk.length_m
                window_m = (glb.pit_limit_end_m - glb.pit_limit_start_m) % trk.length_m
                if (pos - glb.pit_limit_start_m) % trk.length_m < window_m:
                    cap = glb.pit_speed_ms
                else:
                    cap = math.sqrt(glb.pit_speed_ms**2 + 2.0 * glb.pit_entry_decel_ms2 * to_start)
                if target[i] > cap:
                    target[i] = cap
        track_speed(dt, target, trk, glb, car, ctl, st)
        for i in range(n_cars):
            k = _index(st.s_m[i], trk.ds_m, n_pts)
            cap = plans.throttle_cap[i, k]
            slow = st.v_ms[i] < glb.lift_min_speed_share * plans.v_ref[i, k]
            if ctl.throttle[i] > cap and not st.in_pit[i] and not slow:
                ctl.throttle[i] = cap
        step(dt, trk, glb, car, ctl, st, t)
        t += dt
        done = True
        for i in range(n_cars):
            if st.running[i] and st.lap[i] < stop_lap:
                done = False
                break
        if done:
            break
    return t


# --------------------------------------------------------------------------- #
# Building the inputs from config
# --------------------------------------------------------------------------- #


def kernel_track(
    model: TrackModel, track: TrackConfig, loops_m: Sequence[float] | FloatArray = ()
) -> KernelTrack:
    """Track grid, curvature, zone masks and timing loops (ascending, in (0, length))."""
    loops = np.unique(np.asarray(loops_m, dtype=np.float64))
    if loops.size and (loops[0] <= 0.0 or loops[-1] >= model.length_m):
        raise ValueError(f"timing loops must lie in (0, {model.length_m}) m")
    return KernelTrack(
        kappa=np.ascontiguousarray(model.curvature_per_m, dtype=np.float64),
        straight_mode=zone_mask(track, model.s_m, tag="straight_mode_allowed"),
        accel_zone=zone_mask(track, model.s_m, tag="acceleration_zone"),
        ds_m=model.length_m / model.s_m.size,
        length_m=model.length_m,
        loops_m=loops,
    )


def _float(name: str, value: float | str | None) -> float:
    if value is None or isinstance(value, str):
        raise ConfigError(f"step kernel needs {name}, which is {value}")
    return float(value)


def kernel_globals(
    rules: RuleSet, app: AppConfig, track: TrackConfig, tyres: TyreConfig, any_team: str,
    perf: TeamPerformanceConfig,
) -> KernelGlobals:  # fmt: skip
    """Shared values: air, Rule Set tapers / caps, structural tyre and aero values."""
    pt = powertrain_params(rules, perf.teams[any_team])
    batt = battery_params(rules, perf.teams[any_team], 1.0)
    wake = dirty_air_params(app)
    limit_start, limit_end = pit_limit_window(track, app, model_length_m(track))
    return KernelGlobals(
        rho=track_air_density(track, app.physics),
        v_min_ms=app.physics.v_min_ms,
        boost_taper_start_ms=pt.boost_taper_start_ms,
        boost_taper_end_ms=pt.boost_taper_end_ms,
        overtake_taper_start_ms=pt.overtake_taper_start_ms,
        overtake_taper_end_ms=pt.overtake_taper_end_ms,
        zone_cap_acceleration_w=pt.zone_cap_acceleration_w,
        zone_cap_other_w=pt.zone_cap_other_w,
        boost_net_cap_w=pt.boost_net_cap_w,
        superclip_w=superclip_harvest_w(batt),
        harvest_max_w=batt.harvest_max_w,
        wear_norm_j=tyres.wear_norm_j,
        # Track abrasiveness is UNKNOWN until F20 calibration: neutral 1.0 meanwhile.
        abrasiveness=1.0 if isinstance(track.abrasiveness, str) else float(track.abrasiveness),
        straight_mode_throttle_min=app.aero.straight_mode_throttle_min,
        wake_range_m=wake.range_m,
        downforce_loss_max=wake.downforce_loss_max,
        drag_reduction_max=wake.drag_reduction_max,
        follow_gap_m=app.overtake.follow_gap_m,
        pit_speed_ms=_float("pit.lane_speed_kmh", track.pit.lane_speed_kmh) / 3.6,
        pit_limit_start_m=limit_start,
        pit_limit_end_m=limit_end,
        pit_entry_decel_ms2=app.pit.entry_decel_ms2,
        n_ref_n=tyres.load_sensitivity.n_ref_n,
        k_load=tyres.load_sensitivity.k_load,
        lift_min_speed_share=app.ai_driver.lift_min_speed_share,
    )


def kernel_cars(
    team_ids: Sequence[str],
    compounds: Sequence[Compound],
    rules: RuleSet,
    app: AppConfig,
    perf: TeamPerformanceConfig,
    tyres: TyreConfig,
    harvest_limit_mj: float,
) -> KernelCars:
    """Per-car coefficients, one car per ``team_ids[i]`` on ``compounds[i]``.

    Raises:
        ConfigError: A value the kernel uses is still a placeholder.

    """
    min_mass = _float("car.min_mass_kg", rules.car.min_mass_kg)
    cols: dict[str, list[float]] = {f: [] for f in KernelCars._fields}
    for team_id, compound in zip(team_ids, compounds, strict=True):
        team = perf.teams[team_id]
        pt = powertrain_params(rules, team)
        batt = battery_params(rules, team, harvest_limit_mj)
        fuel = fuel_params(rules, team)
        aero = aero_params(team, app.aero)
        tyre = tyre_params(tyres, compound)
        values = {
            "mass_min_kg": min_mass,
            "cda_straight": aero.cda_straight,
            "cda_corner": aero.cda_corner,
            "cla_straight": aero.cla_straight,
            "cla_corner": aero.cla_corner,
            "long_grip_ratio": _float("team long_grip_ratio", team.long_grip_ratio),
            "driveline_efficiency": _float("team driveline_efficiency", team.driveline_efficiency),
            "p_ice_max_w": pt.p_ice_max_w,
            "p_k_max_w": pt.p_k_max_w,
            "discharge_efficiency": batt.discharge_efficiency,
            "brake_harvest_share": batt.brake_harvest_share,
            "partial_harvest_max_w": batt.partial_harvest_max_w,
            "harvest_limit_j": batt.harvest_limit_j,
            "overtake_extra_j": batt.overtake_extra_j,
            "e_usable_max_j": batt.e_usable_max_j,
            "ice_efficiency": fuel.ice_efficiency,
            "fuel_energy_density_j_per_kg": fuel.energy_density_j_per_kg,
            "max_fuel_flow_w": fuel.max_energy_flow_w,
            "mu_base": tyre.mu_base,
            "k_wear": tyre.k_wear,
            "cliff_w": tyre.cliff_w,
            "a_wear": tyre.a_wear,
            "b_wear": tyre.b_wear,
            "c_rr": _float(f"tyres {compound}.c_rr", tyres.compounds[compound].c_rr),
        }
        for name in KernelCars._fields:
            cols[name].append(values[name])
    return KernelCars(**{k: np.array(v, dtype=np.float64) for k, v in cols.items()})


def model_length_m(track: TrackConfig) -> float:
    """Lap length the built track model is normalized to (``official_length_m``)."""
    return _float("official_length_m", track.official_length_m)


def pit_limit_window(track: TrackConfig, app: AppConfig, length_m: float) -> tuple[float, float]:
    """Start and end ``s`` of the pit-lane speed limit (centred on the box)."""
    pit = track.pit
    lane_m = (pit.exit_s_m - pit.entry_s_m) % length_m
    if pit.limit_length_m is None or pit.limit_length_m >= lane_m:
        return pit.entry_s_m, pit.exit_s_m
    box = pit.entry_s_m + app.pit.box_fraction * lane_m
    half = 0.5 * pit.limit_length_m
    start = min(max(box - half, pit.entry_s_m), pit.entry_s_m + lane_m - pit.limit_length_m)
    return start % length_m, (start + pit.limit_length_m) % length_m


def set_compound(car: KernelCars, i: int, tyres: TyreConfig, compound: Compound) -> None:
    """Fit car ``i`` with ``compound``: its tyre coefficients change in place (T-035)."""
    tyre = tyre_params(tyres, compound)
    car.mu_base[i] = tyre.mu_base
    car.k_wear[i] = tyre.k_wear
    car.cliff_w[i] = tyre.cliff_w
    car.a_wear[i] = tyre.a_wear
    car.b_wear[i] = tyre.b_wear
    car.c_rr[i] = _float(f"tyres {compound}.c_rr", tyres.compounds[compound].c_rr)


def initial_state(
    n_cars: int, s_m: Sequence[float] | FloatArray, v_ms: Sequence[float] | FloatArray,
    battery_j: Sequence[float] | FloatArray, fuel_kg: Sequence[float] | FloatArray,
    loops_m: FloatArray | None = None,
) -> KernelState:  # fmt: skip
    """Kernel state for ``n_cars`` cars at the given positions, speeds, energy and fuel.

    ``loops_m`` (the track's timing loops) sets which loop each car passes next;
    loops at or behind a car count as passed this lap.
    """
    loops = np.zeros(0) if loops_m is None else loops_m
    s = np.array(s_m, dtype=np.float64)
    return KernelState(
        s_m=s,
        v_ms=np.array(v_ms, dtype=np.float64),
        lap=np.zeros(n_cars, dtype=np.int64),
        battery_j=np.array(battery_j, dtype=np.float64),
        harvest_lap_j=np.zeros(n_cars, dtype=np.float64),
        deploy_lap_j=np.zeros(n_cars, dtype=np.float64),
        tyre_wear=np.zeros(n_cars, dtype=np.float64),
        fuel_kg=np.array(fuel_kg, dtype=np.float64),
        aero_mode=np.full(n_cars, CORNER_MODE, dtype=np.int64),
        running=np.ones(n_cars, dtype=np.bool_),
        line_time_s=np.zeros(n_cars, dtype=np.float64),
        power_w=np.zeros(n_cars, dtype=np.float64),
        p_k_w=np.zeros(n_cars, dtype=np.float64),
        p_harvest_w=np.zeros(n_cars, dtype=np.float64),
        superclip_on=np.zeros(n_cars, dtype=np.bool_),
        taper_limited=np.zeros(n_cars, dtype=np.bool_),
        gap_ahead_m=np.full(n_cars, np.inf, dtype=np.float64),
        ahead_idx=np.full(n_cars, -1, dtype=np.int64),
        in_pit=np.zeros(n_cars, dtype=np.bool_),
        next_loop=np.searchsorted(loops, s, side="right").astype(np.int64),
        loop_time_s=np.full((n_cars, loops.size), -1.0, dtype=np.float64),
        loop_lap=np.full((n_cars, loops.size), -(1 << 30), dtype=np.int64),
    )


@njit(cache=True)
def reached(lap: IntArray, s_m: FloatArray, length_m: float, mark_d: FloatArray) -> IntArray:
    """Cars whose race distance ``lap x length + s`` has reached ``mark_d`` (T-037)."""
    out = []
    for i in range(s_m.size):
        if lap[i] * length_m + s_m[i] >= mark_d[i]:
            out.append(i)
    return np.array(out, dtype=np.int64)


@njit(cache=True)
def race_order(
    lap: IntArray, s_m: FloatArray, length_m: float, finished: BoolArray, retired: BoolArray,
    finish_t: FloatArray, dnf_offset_m: float,
) -> IntArray:  # fmt: skip
    """Classification: race distance descending, ties by finish time (``lexsort`` order).

    A finished car counts at its finishing line crossing; a retired car is
    ``dnf_offset_m`` behind everyone, ordered by its distance.
    """
    key = np.empty(s_m.size)
    for i in range(s_m.size):
        d = lap[i] * length_m if finished[i] else lap[i] * length_m + s_m[i]
        key[i] = -(d - dnf_offset_m if retired[i] else d)
    by_time = np.argsort(finish_t, kind="mergesort")
    return by_time[np.argsort(key[by_time], kind="mergesort")]


def grip_mu(car: KernelCars, st: KernelState, ctl: KernelControls) -> FloatArray:
    """Each car's tyre friction coefficient now (``mu_base`` x wear factor x grip factor)."""
    w = np.clip(st.tyre_wear, 0.0, 1.0)
    factor = np.where(
        w < car.cliff_w,
        1.0 - car.a_wear * w,
        1.0 - car.a_wear * car.cliff_w - car.b_wear * (w - car.cliff_w),
    )
    return car.mu_base * np.maximum(factor, 0.0) * ctl.grip_factor


def default_controls(n_cars: int) -> KernelControls:
    """Neutral controls: coasting, full deployment allowed, no Overtake / boost / clip."""
    return KernelControls(
        throttle=np.zeros(n_cars, dtype=np.float64),
        brake=np.zeros(n_cars, dtype=np.float64),
        deploy_fraction=np.ones(n_cars, dtype=np.float64),
        overtake_active=np.zeros(n_cars, dtype=np.bool_),
        boost_active=np.zeros(n_cars, dtype=np.bool_),
        boost_total_w=np.zeros(n_cars, dtype=np.float64),
        superclip=np.zeros(n_cars, dtype=np.bool_),
        part_harvest=np.zeros(n_cars, dtype=np.bool_),
        mgmt_factor=np.ones(n_cars, dtype=np.float64),
        grip_factor=np.ones(n_cars, dtype=np.float64),
        speed_scale=np.ones(n_cars, dtype=np.float64),
    )
