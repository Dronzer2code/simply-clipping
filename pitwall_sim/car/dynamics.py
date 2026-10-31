"""Point-mass force laws (TRD Longitudinal dynamics), shared by the speed profile and kernel.

::

    m * dv/dt = F_drive - F_drag - F_rr - F_brake
    F_drag  = 1/2 rho CdA v^2          F_down = 1/2 rho ClA v^2
    F_rr    = C_rr (m g + F_down)      N      = m g + F_down
    F_drive = min(eta * P / max(v, v_min), mu_long * N)    (friction ellipse below)
    m       = m_car_min + m_fuel       (owner round 9: the 768 kg minimum includes
                                         the driver and excludes fuel; no ballast)
    mu(N)   = mu * (N / N_ref)^(-k_load)   tyre load sensitivity (owner round 14)
    v_corner: m |kappa| v^2 = mu(N) N        (no closed form for k_load > 0: Newton;
                                              k_load = 0: closed form, see corner_speed_ms)

Combined grip is a friction ellipse (owner round 9): ``(a_long / (mu_long N/m))^2 +
(a_lat / (mu_lat N/m))^2 <= 1``, ``mu_long = mu_lat * long_grip_ratio``. Traction
is also power-limited; braking is grip-limited only.

Air density (owner round 9): ``rho = p / (R_specific T)`` from the track's
race-day air, else ``physics.rho_fallback``.

Scalar functions take plain floats so the Numba kernel (T-030) can compile them.
"""

from __future__ import annotations

import math

from numba import njit

from pitwall_sim.config.models import PhysicsConfig, TrackConfig

#: Standard gravity, m/s^2.
G_MS2 = 9.80665
#: Above this the corner speed is treated as unlimited (well past any car's top speed).
V_CORNER_CAP_MS = 150.0
#: Specific gas constant of dry air, J/(kg K) (owner round 9).
R_SPECIFIC_AIR = 287.05
HPA_TO_PA = 100.0
C_TO_K = 273.15


def air_density(temp_c: float, pressure_hpa: float) -> float:
    """``rho = p / (R_specific * T)`` in kg/m^3."""
    return pressure_hpa * HPA_TO_PA / (R_SPECIFIC_AIR * (temp_c + C_TO_K))


def track_air_density(track: TrackConfig, physics: PhysicsConfig) -> float:
    """Race-day air density for a track, or ``physics.rho_fallback`` if its air is not set."""
    temp, pressure = track.air_temp_c, track.air_pressure_hpa
    if temp is None or pressure is None or isinstance(temp, str) or isinstance(pressure, str):
        return physics.rho_fallback
    return air_density(float(temp), float(pressure))


def car_mass_kg(min_mass_kg: float, fuel_kg: float) -> float:
    """``m = m_car_min + m_fuel`` (driver included in the minimum, no ballast)."""
    return min_mass_kg + max(fuel_kg, 0.0)


def drag_n(rho: float, cda_m2: float, v_ms: float) -> float:
    """Aerodynamic drag ``1/2 rho CdA v^2``."""
    return 0.5 * rho * cda_m2 * v_ms * v_ms


def downforce_n(rho: float, cla_m2: float, v_ms: float) -> float:
    """Aerodynamic downforce ``1/2 rho ClA v^2``."""
    return 0.5 * rho * cla_m2 * v_ms * v_ms


def normal_force_n(mass_kg: float, rho: float, cla_m2: float, v_ms: float) -> float:
    """Tyre normal load ``N = m g + F_down``."""
    return mass_kg * G_MS2 + downforce_n(rho, cla_m2, v_ms)


def rolling_n(c_rr: float, mass_kg: float, rho: float, cla_m2: float, v_ms: float) -> float:
    """Return rolling resistance ``C_rr (m g + F_down)``."""
    return c_rr * normal_force_n(mass_kg, rho, cla_m2, v_ms)


def resistance_n(
    c_rr: float, mass_kg: float, rho: float, cda_m2: float, cla_m2: float, v_ms: float
) -> float:
    """Drag plus rolling resistance."""
    return drag_n(rho, cda_m2, v_ms) + rolling_n(c_rr, mass_kg, rho, cla_m2, v_ms)


def wheel_power_required_w(
    accel_ms2: float,
    c_rr: float,
    mass_kg: float,
    rho: float,
    cda_m2: float,
    cla_m2: float,
    v_ms: float,
) -> float:
    """Wheel power to accelerate at ``accel_ms2`` at speed ``v``: ``(m a + F_drag + F_rr) v``.

    At constant speed this is drag plus rolling resistance only (TRD
    ``test_constant_speed_power``).
    """
    return (mass_kg * accel_ms2 + resistance_n(c_rr, mass_kg, rho, cda_m2, cla_m2, v_ms)) * v_ms


@njit(cache=True)
def load_factor(normal_n: float, n_ref_n: float, k_load: float) -> float:
    """Tyre load sensitivity ``(N / N_ref)^(-k_load)`` (owner round 14)."""
    if k_load == 0.0:
        return 1.0
    return float((max(normal_n, 1.0) / n_ref_n) ** (-k_load))


@njit(cache=True)
def corner_speed_ms(
    kappa_per_m: float,
    mu_lat: float,
    mass_kg: float,
    rho: float,
    cla_m2: float,
    n_ref_n: float = 1.0,
    k_load: float = 0.0,
) -> float:
    """Grip-limited cornering speed; ``inf`` where grip does not limit it.

    Solves ``m |kappa| v^2 = mu (N / N_ref)^(-k) N`` with ``N = m g + 1/2 rho ClA v^2``.
    In ``x = v^2`` the left side is linear and the right side concave, so the
    difference is convex with one root: Newton from the speed cap converges from
    the right. ``k_load = 0`` keeps the closed form (no limit when downforce
    outgrows the need, i.e. its denominator is <= 0).
    """
    kappa = abs(kappa_per_m)
    if kappa <= 0.0:
        return math.inf
    c = 0.5 * rho * cla_m2
    if k_load == 0.0:
        denominator = mass_kg * kappa - mu_lat * c
        if denominator <= 0.0:
            return math.inf
        return math.sqrt(mu_lat * mass_kg * G_MS2 / denominator)
    a = mu_lat * n_ref_n**k_load
    x = V_CORNER_CAP_MS * V_CORNER_CAP_MS
    if mass_kg * kappa * x - a * (mass_kg * G_MS2 + c * x) ** (1.0 - k_load) <= 0.0:
        return math.inf
    for _ in range(60):
        n = mass_kg * G_MS2 + c * x
        g = mass_kg * kappa * x - a * n ** (1.0 - k_load)
        dg = mass_kg * kappa - a * (1.0 - k_load) * c * n ** (-k_load)
        step = g / dg
        x -= step
        if abs(step) <= 1e-12 * x:
            break
    return math.sqrt(max(x, 0.0))


def ellipse_long_fraction(lat_accel_ms2: float, lat_grip_ms2: float) -> float:
    """Share of longitudinal grip left after cornering: ``sqrt(1 - (a_lat / a_lat_max)^2)``."""
    if lat_grip_ms2 <= 0.0:
        return 0.0
    used = lat_accel_ms2 / lat_grip_ms2
    return math.sqrt(1.0 - used * used) if used * used < 1.0 else 0.0


def drive_force_n(
    wheel_power_w: float, v_ms: float, v_min_ms: float, long_grip_force_n: float
) -> float:
    """``F_drive = min(P_wheel / max(v, v_min), longitudinal grip)``."""
    return min(max(wheel_power_w, 0.0) / max(v_ms, v_min_ms), max(long_grip_force_n, 0.0))
