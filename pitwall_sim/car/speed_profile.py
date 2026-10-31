"""F02 reference speed profile: quasi-steady-state forward/backward pass (TRD, T-024).

``v_ref(s) = min(v_corner(s), v_accel(s), v_brake(s))`` over the built centre line:

- ``v_corner``: grip-limited corner speed at each point's curvature, with the
  aero mode the car would be in there (Straight Mode inside
  ``straight_mode_allowed`` zones, Corner Mode elsewhere).
- ``v_accel`` (forward pass): full throttle, ICE at full power (capped by the
  fuel energy-flow limit) plus MGU-K at ``deploy_fraction`` of what the zone
  cap and taper allow, limited by the friction ellipse; Straight Mode in its
  zones.
- ``v_brake`` (backward pass): braking at the grip left by the friction ellipse,
  drag and rolling resistance helping; Corner Mode (driver off throttle).

The lap is periodic: each pass starts at the slowest corner and runs two laps,
so the result is the flying-lap profile. It is recomputed once per lap per car
(TRD), so falling fuel mass and tyre wear show up lap by lap. The passes are
compiled with Numba (NFR-02, T-036).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
from numba import njit

from pitwall_sim.car.aero import CORNER_MODE, STRAIGHT_MODE, AeroParams, aero_params, cda, cla
from pitwall_sim.car.dynamics import (
    G_MS2,
    car_mass_kg,
    corner_speed_ms,
    drive_force_n,
    ellipse_long_fraction,
    load_factor,
    normal_force_n,
    resistance_n,
    track_air_density,
)
from pitwall_sim.car.fuel import fuel_params, max_ice_power_w
from pitwall_sim.car.powertrain import (
    PowertrainParams,
    ice_power_w,
    mgu_k_allowed_w,
    powertrain_params,
)
from pitwall_sim.car.tyres import mu_tyre, tyre_params, tyre_temp_c
from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import (
    AppConfig,
    Compound,
    RuleSet,
    TeamPerformance,
    TrackConfig,
    TyreConfig,
)
from pitwall_sim.track.builder import TrackModel
from pitwall_sim.track.zones import zone_mask

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]


class ProfileParams(NamedTuple):
    """Everything the profile needs for one car on one lap, SI units."""

    mass_kg: float
    rho: float
    mu_lat: float
    """Tyre grip incl. wear, track grip and dirty air."""
    mu_long: float
    """``mu_lat * long_grip_ratio``."""
    c_rr: float
    driveline_efficiency: float
    p_ice_w: float
    """ICE power at full throttle, already capped by the fuel energy-flow limit."""
    deploy_fraction: float
    """Share of the allowed MGU-K power deployed on the reference lap."""
    v_min_ms: float
    aero: AeroParams
    powertrain: PowertrainParams
    n_ref_n: float = 1.0
    """Tyre load sensitivity reference load (owner round 14)."""
    k_load: float = 0.0
    """Tyre load sensitivity exponent; 0 = none."""


@dataclass(frozen=True)
class SpeedProfile:
    """Reference speeds per centre-line point (same grid as the track model)."""

    s_m: FloatArray
    v_ref_ms: FloatArray
    v_corner_ms: FloatArray
    """``inf`` where the corner does not limit speed."""
    v_accel_ms: FloatArray
    v_brake_ms: FloatArray
    lap_time_s: float


def accel_at_power_ms2(
    v: float, kappa: float, straight_mode: bool, power_w: float, p: ProfileParams
) -> float:
    """Acceleration with ``power_w`` (ICE + MGU-K, before driveline losses) at the engine.

    Drive force is limited by power and by the longitudinal grip the friction
    ellipse leaves after cornering; drag and rolling resistance oppose it.
    """
    mode = STRAIGHT_MODE if straight_mode else CORNER_MODE
    cl, cd = cla(mode, p.aero), cda(mode, p.aero)
    normal = normal_force_n(p.mass_kg, p.rho, cl, v)
    f_load = load_factor(normal, p.n_ref_n, p.k_load)
    lat_grip = p.mu_lat * f_load * normal / p.mass_kg
    grip_long = p.mu_long * f_load * normal * ellipse_long_fraction(v * v * abs(kappa), lat_grip)
    drive = drive_force_n(p.driveline_efficiency * power_w, v, p.v_min_ms, grip_long)
    return (drive - resistance_n(p.c_rr, p.mass_kg, p.rho, cd, cl, v)) / p.mass_kg


def _accel_ms2(
    v: float, kappa: float, straight_mode: bool, in_accel_zone: bool, p: ProfileParams
) -> float:
    p_k = p.deploy_fraction * mgu_k_allowed_w(
        v, in_accel_zone, False, False, 0.0, 0.0, p.powertrain
    )
    return accel_at_power_ms2(v, kappa, straight_mode, p.p_ice_w + p_k, p)


def brake_decel_ms2(v: float, kappa: float, p: ProfileParams) -> float:
    """Deceleration at full braking: ellipse grip plus drag and rolling (Corner Mode)."""
    return _decel_ms2(v, kappa, p)


def _decel_ms2(v: float, kappa: float, p: ProfileParams) -> float:
    cl, cd = cla(CORNER_MODE, p.aero), cda(CORNER_MODE, p.aero)
    normal = normal_force_n(p.mass_kg, p.rho, cl, v)
    f_load = load_factor(normal, p.n_ref_n, p.k_load)
    lat_grip = p.mu_lat * f_load * normal / p.mass_kg
    brake = p.mu_long * f_load * normal * ellipse_long_fraction(v * v * abs(kappa), lat_grip)
    return (brake + resistance_n(p.c_rr, p.mass_kg, p.rho, cd, cl, v)) / p.mass_kg


# --------------------------------------------------------------------------- #
# Compiled passes (NFR-02): the same formulas as the functions above, on scalar
# arguments (``_scalars``); tests check them against the Python versions.
# --------------------------------------------------------------------------- #


def _scalars(p: ProfileParams) -> tuple[float, ...]:
    a, pt = p.aero, p.powertrain
    return (
        p.mass_kg, p.rho, p.mu_lat, p.mu_long, p.c_rr, p.driveline_efficiency, p.p_ice_w,
        p.deploy_fraction, p.v_min_ms, a.cda_straight, a.cda_corner, a.cla_straight,
        a.cla_corner, pt.p_k_max_w, pt.zone_cap_acceleration_w, pt.zone_cap_other_w,
        pt.boost_taper_start_ms, pt.boost_taper_end_ms, p.n_ref_n, p.k_load,
    )  # fmt: skip


@njit(cache=True)
def _long_force(
    v: float, kappa: float, mass: float, rho: float, mu_lat: float, mu_long: float, cl: float,
    n_ref: float, k_load: float,
) -> tuple[float, float]:  # fmt: skip
    """``(normal_n, grip_long_n)``: normal load and the longitudinal grip the ellipse leaves."""
    normal = mass * G_MS2 + 0.5 * rho * cl * v * v
    f_load = load_factor(normal, n_ref, k_load)
    lat_grip = mu_lat * f_load * normal / mass
    frac = 0.0
    if lat_grip > 0.0:
        used = v * v * abs(kappa) / lat_grip
        frac = math.sqrt(1.0 - used * used) if used * used < 1.0 else 0.0
    return normal, mu_long * f_load * normal * frac


@njit(cache=True)
def _corner_limits_jit(
    kappa: FloatArray, straight_mode: BoolArray, sc: tuple[float, ...]
) -> FloatArray:
    mass, rho, mu_lat = sc[0], sc[1], sc[2]
    out = np.empty(kappa.size, dtype=np.float64)
    for i in range(kappa.size):
        cl = sc[11] if straight_mode[i] else sc[12]
        out[i] = corner_speed_ms(kappa[i], mu_lat, mass, rho, cl, sc[18], sc[19])
    return out


@njit(cache=True)
def _accel_jit(
    v: float, kappa: float, straight: bool, in_zone: bool, sc: tuple[float, ...]
) -> float:
    mass, rho, mu_lat, mu_long, c_rr, eta, p_ice, deploy, v_min = sc[:9]
    cd = sc[9] if straight else sc[10]
    cl = sc[11] if straight else sc[12]
    normal, grip_long = _long_force(v, kappa, mass, rho, mu_lat, mu_long, cl, sc[18], sc[19])
    start, end = sc[16], sc[17]
    taper = 1.0 if v <= start else (0.0 if v >= end else (end - v) / (end - start))
    cap = sc[14] if in_zone else sc[15]
    p_k = deploy * min(cap, sc[13] * taper)
    drive = min(max(eta * (p_ice + p_k), 0.0) / max(v, v_min), max(grip_long, 0.0))
    return (drive - (0.5 * rho * cd * v * v + c_rr * normal)) / mass


@njit(cache=True)
def _decel_jit(v: float, kappa: float, sc: tuple[float, ...]) -> float:
    mass, rho, mu_lat, mu_long, c_rr = sc[0], sc[1], sc[2], sc[3], sc[4]
    cd, cl = sc[10], sc[12]  # Corner Mode: the driver is off the throttle
    normal, brake = _long_force(v, kappa, mass, rho, mu_lat, mu_long, cl, sc[18], sc[19])
    return (brake + 0.5 * rho * cd * v * v + c_rr * normal) / mass


@njit(cache=True)
def _forward_jit(
    kappa: FloatArray,
    straight_mode: BoolArray,
    accel_zone: BoolArray,
    v_corner: FloatArray,
    ds_m: float,
    sc: tuple[float, ...],
) -> FloatArray:
    n = kappa.size
    i0 = int(np.argmin(v_corner))
    v = v_corner[i0] if math.isfinite(v_corner[i0]) else 0.0
    out = np.empty(n, dtype=np.float64)
    for k in range(2 * n):  # two laps: the second is the periodic solution
        i = (i0 + k) % n
        out[i] = v
        a = _accel_jit(v, kappa[i], straight_mode[i], accel_zone[i], sc)
        v = min(math.sqrt(max(v * v + 2.0 * a * ds_m, 0.0)), v_corner[(i + 1) % n])
    return out


@njit(cache=True)
def _backward_jit(
    kappa: FloatArray, v_corner: FloatArray, ds_m: float, sc: tuple[float, ...]
) -> FloatArray:
    n = kappa.size
    i0 = int(np.argmin(v_corner))
    v = v_corner[i0] if math.isfinite(v_corner[i0]) else math.inf
    out = np.empty(n, dtype=np.float64)
    for k in range(2 * n):
        j = (i0 - k) % n
        out[j] = v
        i = (j - 1) % n
        if math.isinf(v):
            v = v_corner[i]
            continue
        v = min(math.sqrt(v * v + 2.0 * _decel_jit(v, kappa[j], sc) * ds_m), v_corner[i])
    return out


def corner_limits(kappa: FloatArray, straight_mode: BoolArray, p: ProfileParams) -> FloatArray:
    """``v_corner`` per point with the aero mode used there."""
    return _corner_limits_jit(_f64(kappa), _bool(straight_mode), _scalars(p))


def forward_pass(
    kappa: FloatArray,
    straight_mode: BoolArray,
    accel_zone: BoolArray,
    v_corner: FloatArray,
    ds_m: float,
    p: ProfileParams,
) -> FloatArray:
    """Fastest speed reachable at each point accelerating out of the corners."""
    return _forward_jit(
        _f64(kappa), _bool(straight_mode), _bool(accel_zone), _f64(v_corner), ds_m, _scalars(p)
    )


def backward_pass(
    kappa: FloatArray, v_corner: FloatArray, ds_m: float, p: ProfileParams
) -> FloatArray:
    """Fastest speed at each point that still brakes in time for what follows."""
    return _backward_jit(_f64(kappa), _f64(v_corner), ds_m, _scalars(p))


def _f64(a: npt.ArrayLike) -> FloatArray:
    return np.ascontiguousarray(a, dtype=np.float64)


def _bool(a: npt.ArrayLike) -> BoolArray:
    return np.ascontiguousarray(a, dtype=np.bool_)


def lap_time_s(v_ms: FloatArray, ds_m: float) -> float:
    """Lap time over a closed loop of equally spaced points (trapezoid on 1/v)."""
    v_next = np.roll(v_ms, -1)
    return float(np.sum(2.0 * ds_m / (v_ms + v_next)))


def speed_profile(
    s_m: FloatArray,
    kappa: FloatArray,
    straight_mode: BoolArray,
    accel_zone: BoolArray,
    length_m: float,
    p: ProfileParams,
) -> SpeedProfile:
    """Build the reference speed profile for one car on one lap.

    Args:
        s_m: Centre-line distances (the track model grid, equally spaced).
        kappa: Curvature per point, 1/m (sign ignored).
        straight_mode: Points inside ``straight_mode_allowed`` zones.
        accel_zone: Points inside ``acceleration_zone`` zones (MGU-K zone cap).
        length_m: Lap length (closes the loop).
        p: Car, tyre and air parameters for this lap.

    """
    ds = length_m / s_m.size
    v_corner = corner_limits(kappa, straight_mode, p)
    v_accel = forward_pass(kappa, straight_mode, accel_zone, v_corner, ds, p)
    v_brake = backward_pass(kappa, v_corner, ds, p)
    v_ref = np.minimum(v_accel, v_brake)
    return SpeedProfile(
        s_m=s_m,
        v_ref_ms=v_ref,
        v_corner_ms=v_corner,
        v_accel_ms=v_accel,
        v_brake_ms=v_brake,
        lap_time_s=lap_time_s(v_ref, ds),
    )


def local_minima_s(profile: SpeedProfile, min_drop_ms: float = 2.0) -> list[float]:
    """Distances of the profile's speed minima (corner apexes), wrapping around s = 0.

    A minimum counts when it has at least ``min_drop_ms`` of prominence, which
    skips flat spots and float noise.
    """
    v = profile.v_ref_ms
    n = v.size
    tripled = np.concatenate((v, v, v))
    from scipy.signal import find_peaks  # noqa: PLC0415  (~1.7 s import; not on the race path)

    peaks, _ = find_peaks(-tripled, prominence=min_drop_ms)
    middle = sorted({int(i) - n for i in peaks if n <= i < 2 * n})
    return [float(profile.s_m[i]) for i in middle]


# --------------------------------------------------------------------------- #
# From config
# --------------------------------------------------------------------------- #


def reference_params(
    rules: RuleSet,
    team: TeamPerformance,
    tyres: TyreConfig,
    compound: Compound,
    app: AppConfig,
    track: TrackConfig,
    fuel_kg: float,
    *,
    wear: float = 0.0,
    deploy_fraction: float = 1.0,
    grip_track: float = 1.0,
    dirty_air_factor: float = 1.0,
) -> ProfileParams:
    """Assemble :class:`ProfileParams` for one car from config.

    Raises:
        ConfigError: A value the profile uses is still a placeholder.

    """
    tyre = tyre_params(tyres, compound)
    c_rr = tyres.compounds[compound].c_rr
    min_mass = rules.car.min_mass_kg
    for name, value in (
        (f"tyres {compound}.c_rr", c_rr),
        ("car.min_mass_kg", min_mass),
        ("team long_grip_ratio", team.long_grip_ratio),
        ("team driveline_efficiency", team.driveline_efficiency),
    ):
        if isinstance(value, str):
            raise ConfigError(f"speed profile needs {name}, which is {value}")
    assert not isinstance(c_rr, str) and not isinstance(min_mass, str)
    assert not isinstance(team.long_grip_ratio, str)
    assert not isinstance(team.driveline_efficiency, str)

    powertrain = powertrain_params(rules, team)
    fuel = fuel_params(rules, team)
    mu_lat = mu_tyre(wear, tyre_temp_c(tyre), tyre) * grip_track * dirty_air_factor
    return ProfileParams(
        mass_kg=car_mass_kg(float(min_mass), fuel_kg),
        rho=track_air_density(track, app.physics),
        mu_lat=mu_lat,
        mu_long=mu_lat * float(team.long_grip_ratio),
        c_rr=float(c_rr),
        driveline_efficiency=float(team.driveline_efficiency),
        p_ice_w=min(ice_power_w(1.0, powertrain), max_ice_power_w(fuel)),
        deploy_fraction=deploy_fraction,
        v_min_ms=app.physics.v_min_ms,
        aero=aero_params(team, app.aero),
        powertrain=powertrain,
        n_ref_n=tyres.load_sensitivity.n_ref_n,
        k_load=tyres.load_sensitivity.k_load,
    )


def reference_profile(model: TrackModel, track: TrackConfig, p: ProfileParams) -> SpeedProfile:
    """Speed profile on a built track model, with its Straight Mode and acceleration zones."""
    straight_mode = zone_mask(track, model.s_m, tag="straight_mode_allowed")
    accel_zone = zone_mask(track, model.s_m, tag="acceleration_zone")
    return speed_profile(
        model.s_m, model.curvature_per_m, straight_mode, accel_zone, model.length_m, p
    )
