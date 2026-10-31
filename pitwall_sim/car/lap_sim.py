"""Single-car lap simulation with energy limits (T-025, PF-02).

The speed profile (T-024) assumes the MGU-K can deploy whatever the zone cap
and taper allow all lap. A real lap has a 4 MJ battery window and a per-lap
harvest limit, so this steps metre by metre along the same track grid:

- the speed cap at each point is ``min(v_corner, v_brake)`` from the profile
  (braking does not depend on power);
- accelerating: ICE at full power plus the MGU-K power the battery can supply
  this step (``battery.available_deploy_w``), limited by the friction ellipse;
- where the cap binds while still accelerating: part throttle, ICE first, then
  MGU-K, just enough to reach the cap;
- braking: the brake force needed to follow the cap, of which the MGU-K
  harvests its share (``battery.braking_harvest_w``), up to the per-lap limit;
- battery, per-lap counters and fuel are integrated with the T-022 / T-023
  functions; time with the trapezoid rule on ``ds / v``.

With unlimited energy the result equals the speed profile. Without a
deploy plan, deployment is greedy (deploy whenever accelerating). A deploy plan
(``deploy_zone`` + ``zone_budget_j``, e.g. from
``calibration.deploy_policy``) restricts deployment to numbered zones, each
with an energy budget, and ``superclip`` marks points where the car harvests at
the Rule Set super-clip power at full throttle, giving up that much wheel power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pitwall_sim.car.aero import CORNER_MODE, STRAIGHT_MODE, cda, cla
from pitwall_sim.car.battery import (
    BatteryParams,
    available_deploy_w,
    braking_harvest_w,
    step,
    superclip_harvest_w,
)
from pitwall_sim.car.dynamics import resistance_n
from pitwall_sim.car.fuel import FuelParams, burn
from pitwall_sim.car.powertrain import mgu_k_allowed_w
from pitwall_sim.car.speed_profile import (
    ProfileParams,
    accel_at_power_ms2,
    backward_pass,
    corner_limits,
    forward_pass,
)

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
type IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class LapResult:
    """One simulated lap on the track grid."""

    s_m: FloatArray
    v_ms: FloatArray
    t_s: FloatArray
    """Time at each point since the timing line."""
    battery_j: FloatArray
    """Battery energy at each point."""
    lap_time_s: float
    harvested_j: float
    drawn_j: float
    fuel_used_kg: float
    battery_end_j: float
    zone_drawn_j: FloatArray | None = None
    """Battery energy drawn per deploy-plan zone (``None`` without a plan)."""
    superclip_j: float = 0.0
    """Energy harvested by super-clipping."""
    unmet_deploy_j: float = 0.0
    """Battery energy full-throttle deployment wanted but the battery could not supply."""
    harvest_offered_j: FloatArray | None = None
    """Per point: energy braking (or super-clip) offered the MGU-K, before the
    battery's room and the lap limit (deploy planning, owner round 14)."""


def simulate_lap(
    s_m: FloatArray,
    kappa: FloatArray,
    straight_mode: BoolArray,
    accel_zone: BoolArray,
    length_m: float,
    prof: ProfileParams,
    batt: BatteryParams,
    fuel: FuelParams,
    *,
    battery_start_j: float,
    fuel_kg: float,
    deploy_zone: IntArray | None = None,
    zone_budget_j: FloatArray | None = None,
    superclip: BoolArray | None = None,
) -> LapResult:
    """Simulate one flying lap from the timing line.

    The lap starts at the speed the reference profile has at the timing line
    (as after a preceding lap) with ``battery_start_j`` stored and counters at 0.

    Args:
        s_m: Centre-line distances (track model grid, equally spaced).
        kappa: Curvature per point, 1/m.
        straight_mode: Points inside ``straight_mode_allowed`` zones.
        accel_zone: Points inside ``acceleration_zone`` zones (MGU-K zone cap).
        length_m: Lap length.
        prof: Car, tyre and air parameters for the lap.
        batt: Battery limits for the lap.
        fuel: Fuel conversion and flow limit.
        battery_start_j: Battery energy at the timing line.
        fuel_kg: Fuel on board at the timing line.
        deploy_zone: Optional deploy plan: zone index per point, -1 where the
            MGU-K must not deploy. Requires ``zone_budget_j``.
        zone_budget_j: Battery energy each zone may draw.
        superclip: Optional points where the car super-clips at full throttle.

    """
    n = s_m.size
    ds = length_m / n
    v_corner = corner_limits(kappa, straight_mode, prof)
    cap = np.minimum(v_corner, backward_pass(kappa, v_corner, ds, prof))
    v_start = forward_pass(kappa, straight_mode, accel_zone, v_corner, ds, prof)[0]
    v = min(v_start, cap[0]) if math.isfinite(cap[0]) else v_start

    v_out = np.empty(n, dtype=np.float64)
    t_out = np.empty(n, dtype=np.float64)
    e_out = np.empty(n, dtype=np.float64)
    offered = np.zeros(n, dtype=np.float64)
    battery, harvest_lap, deploy_lap = battery_start_j, 0.0, 0.0
    harvested = drawn = clipped = unmet = t = 0.0
    fuel_now = fuel_kg
    planned = deploy_zone is not None and zone_budget_j is not None
    zone_drawn = np.zeros(0 if zone_budget_j is None else zone_budget_j.size, dtype=np.float64)

    for i in range(n):
        j = (i + 1) % n
        v_out[i], t_out[i], e_out[i] = v, t, battery
        sm = bool(straight_mode[i])

        dt_est = ds / max(v, prof.v_min_ms)
        p_k_allowed = prof.deploy_fraction * mgu_k_allowed_w(
            v, bool(accel_zone[i]), False, False, 0.0, 0.0, prof.powertrain
        )
        p_k_target = p_k_allowed  # what the rules and the deploy plan allow here
        zone = -1
        if planned:
            assert deploy_zone is not None and zone_budget_j is not None
            zone = int(deploy_zone[i])
            if zone < 0:
                p_k_target = 0.0
            else:
                left_j = max(zone_budget_j[zone] - zone_drawn[zone], 0.0)
                p_k_target = min(p_k_target, left_j * batt.discharge_efficiency / dt_est)
        p_k_avail = min(p_k_target, available_deploy_w(battery, deploy_lap, dt_est, batt))
        clip_w = superclip_harvest_w(batt) if superclip is not None and superclip[i] else 0.0
        if clip_w > 0.0:
            p_k_target = p_k_avail = 0.0  # the MGU-K harvests instead of deploying
        wheel_power = max(prof.p_ice_w + p_k_avail - clip_w, 0.0)
        a_full = accel_at_power_ms2(v, kappa[i], sm, wheel_power, prof)
        v_full = math.sqrt(max(v * v + 2.0 * a_full * ds, 0.0))

        p_ice = p_k = p_harvest = 0.0
        if v_full <= cap[j]:
            v_next, p_ice, p_k, p_harvest = v_full, prof.p_ice_w, p_k_avail, clip_w
            dt_full = 2.0 * ds / (v + v_next) if v + v_next > 0.0 else dt_est
            unmet += (p_k_target - p_k_avail) * dt_full / batt.discharge_efficiency
        else:
            v_next = cap[j]
            a_need = (v_next * v_next - v * v) / (2.0 * ds)
            if a_need >= 0.0:  # part throttle up to the cap
                mode = STRAIGHT_MODE if sm else CORNER_MODE
                cd, cl = cda(mode, prof.aero), cla(mode, prof.aero)
                drive = prof.mass_kg * a_need + resistance_n(
                    prof.c_rr, prof.mass_kg, prof.rho, cd, cl, v
                )
                power = drive * max(v, prof.v_min_ms) / prof.driveline_efficiency
                p_ice = min(max(power, 0.0), prof.p_ice_w)
                p_k = min(max(power - p_ice, 0.0), p_k_avail)
            else:  # braking to follow the cap; the MGU-K harvests its share
                cd, cl = cda(CORNER_MODE, prof.aero), cla(CORNER_MODE, prof.aero)
                brake_n = -prof.mass_kg * a_need - resistance_n(
                    prof.c_rr, prof.mass_kg, prof.rho, cd, cl, v
                )
                p_harvest = braking_harvest_w(brake_n * v, batt) if brake_n > 0.0 else 0.0

        dt = 2.0 * ds / (v + v_next) if v + v_next > 0.0 else dt_est
        offered[i] = p_harvest * dt
        r = step(battery, harvest_lap, deploy_lap, p_harvest, p_k, False, dt, batt)
        battery, harvest_lap, deploy_lap = r.battery_j, r.harvest_lap_j, r.deploy_lap_j
        harvested += r.harvested_j
        drawn += r.drawn_j
        if zone >= 0:
            zone_drawn[zone] += r.drawn_j
        if p_harvest > 0.0 and p_harvest == clip_w:
            clipped += r.harvested_j
        fuel_now = burn(fuel_now, p_ice, dt, fuel)
        t += dt
        v = v_next

    return LapResult(
        s_m=s_m,
        v_ms=v_out,
        t_s=t_out,
        battery_j=e_out,
        lap_time_s=t,
        harvested_j=harvested,
        drawn_j=drawn,
        fuel_used_kg=fuel_kg - fuel_now,
        battery_end_j=battery,
        zone_drawn_j=zone_drawn if planned else None,
        superclip_j=clipped,
        unmet_deploy_j=unmet,
        harvest_offered_j=offered,
    )
