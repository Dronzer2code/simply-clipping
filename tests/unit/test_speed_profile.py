"""T-024: force laws and the reference speed profile (QSS forward/backward pass)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.car.aero import CORNER_MODE, cda, cla
from pitwall_sim.car.dynamics import (
    G_MS2,
    air_density,
    car_mass_kg,
    corner_speed_ms,
    drag_n,
    drive_force_n,
    ellipse_long_fraction,
    resistance_n,
    rolling_n,
    track_air_density,
    wheel_power_required_w,
)
from pitwall_sim.car.powertrain import mgu_k_allowed_w
from pitwall_sim.car.speed_profile import (
    ProfileParams,
    local_minima_s,
    reference_params,
    reference_profile,
    speed_profile,
)
from pitwall_sim.config.loader import (
    ConfigError,
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def _params(rule_set_id: str = "2026_pre_miami", **overrides: float) -> ProfileParams:
    p = reference_params(
        load_rule_set(rule_set_id, CONFIG_DIR),
        load_team_performance(CONFIG_DIR).teams["mercedes"],
        load_tyres(CONFIG_DIR),
        Compound.SOFT,
        load_app(CONFIG_DIR),
        load_track("suzuka", CONFIG_DIR),
        70.0,
    )
    return p._replace(**overrides)


def _loop(kappa: np.ndarray, length_m: float, p: ProfileParams):  # type: ignore[no-untyped-def]
    n = kappa.size
    s = np.arange(n, dtype=np.float64) * (length_m / n)
    none = np.zeros(n, dtype=np.bool_)
    return speed_profile(s, kappa, none, none, length_m, p)


# --------------------------------------------------------------------------- #
# TRD test_constant_speed_power
# --------------------------------------------------------------------------- #


def test_constant_speed_power() -> None:
    """At constant v, wheel power = drag + rolling only."""
    p = _params()
    cd, cl = cda(CORNER_MODE, p.aero), cla(CORNER_MODE, p.aero)
    for v in (10.0, 50.0, 80.0):
        power = wheel_power_required_w(0.0, p.c_rr, p.mass_kg, p.rho, cd, cl, v)
        expected = (drag_n(p.rho, cd, v) + rolling_n(p.c_rr, p.mass_kg, p.rho, cl, v)) * v
        assert power == pytest.approx(expected, rel=1e-12)
        # Accelerating needs exactly m * a * v more.
        accel = wheel_power_required_w(1.0, p.c_rr, p.mass_kg, p.rho, cd, cl, v)
        assert accel - power == pytest.approx(p.mass_kg * 1.0 * v)


def test_top_speed_is_where_power_meets_drag_and_rolling() -> None:
    """On a long straight the forward pass settles where wheel power = resistance * v."""
    p = _params()
    profile = _loop(np.zeros(20_000), 20_000.0, p)
    v_top = float(profile.v_ref_ms.max())

    p_k = p.deploy_fraction * mgu_k_allowed_w(v_top, False, False, False, 0.0, 0.0, p.powertrain)
    supplied = p.driveline_efficiency * (p.p_ice_w + p_k)
    cd, cl = cda(CORNER_MODE, p.aero), cla(CORNER_MODE, p.aero)
    needed = resistance_n(p.c_rr, p.mass_kg, p.rho, cd, cl, v_top) * v_top
    assert supplied == pytest.approx(needed, rel=0.01)
    assert np.allclose(profile.v_ref_ms, v_top, rtol=1e-3)  # flat: no corners, no braking


# --------------------------------------------------------------------------- #
# Force laws
# --------------------------------------------------------------------------- #


def test_air_density_and_fallback() -> None:
    app = load_app(CONFIG_DIR)
    track = load_track("suzuka", CONFIG_DIR)

    assert air_density(20.0, 1013.0) == pytest.approx(101300 / (287.05 * 293.15))
    assert track_air_density(track, app.physics) == pytest.approx(1.2038, abs=1e-4)
    no_air = track.model_copy(update={"air_temp_c": None})
    assert track_air_density(no_air, app.physics) == app.physics.rho_fallback == 1.20


def test_mass_includes_driver_and_fuel_only() -> None:
    """Owner round 9: 768 kg includes the driver, excludes fuel; no ballast."""
    assert car_mass_kg(768.0, 70.0) == 838.0
    assert car_mass_kg(768.0, -1.0) == 768.0
    assert _params().mass_kg == 838.0


def test_corner_speed_formula() -> None:
    m, rho, mu, cl = 838.0, 1.2, 1.6, 4.0
    kappa = 1.0 / 100.0
    v = corner_speed_ms(kappa, mu, m, rho, cl)

    # Lateral force at that speed exactly uses the grip from weight + downforce.
    assert m * v * v * kappa == pytest.approx(mu * (m * G_MS2 + 0.5 * rho * cl * v * v))
    assert corner_speed_ms(0.0, mu, m, rho, cl) == math.inf
    assert corner_speed_ms(1e-5, mu, m, rho, cl) == math.inf  # downforce outgrows the need


def test_friction_ellipse_and_drive_force() -> None:
    assert ellipse_long_fraction(0.0, 20.0) == 1.0
    assert ellipse_long_fraction(12.0, 20.0) == pytest.approx(0.8)
    assert ellipse_long_fraction(20.0, 20.0) == 0.0
    assert ellipse_long_fraction(25.0, 20.0) == 0.0
    # Power-limited above, grip-limited below; v_min keeps P / v finite.
    assert drive_force_n(500e3, 50.0, 1.0, 1e9) == pytest.approx(10e3)
    assert drive_force_n(500e3, 0.0, 1.0, 8e3) == pytest.approx(8e3)
    assert drive_force_n(500e3, 0.0, 1.0, 1e9) == pytest.approx(500e3)


# --------------------------------------------------------------------------- #
# Profile behaviour
# --------------------------------------------------------------------------- #


def test_constant_radius_circle_runs_at_the_corner_speed() -> None:
    p = _params()
    radius = 60.0  # slow enough to stay below the MGU-K taper
    length = 2 * math.pi * radius
    profile = _loop(np.full(int(length), 1.0 / radius), length, p)
    v = corner_speed_ms(
        1.0 / radius, p.mu_lat, p.mass_kg, p.rho, cla(CORNER_MODE, p.aero), p.n_ref_n, p.k_load
    )

    # Steady state: at the corner limit all grip is lateral, so the friction
    # ellipse leaves none to push against drag; the car settles just below it,
    # where the remaining longitudinal grip exactly balances the resistance.
    v_ss = profile.v_ref_ms[0]
    assert np.allclose(profile.v_ref_ms, v_ss)
    assert 0.95 * v < v_ss < v
    assert profile.lap_time_s == pytest.approx(length / v_ss)


def test_stadium_brakes_into_each_corner() -> None:
    p = _params()
    straight, radius = 600.0, 40.0  # hairpin-like
    arc = math.pi * radius
    length = 2 * straight + 2 * arc
    s = np.arange(int(length), dtype=np.float64)
    in_arc = ((s >= straight) & (s < straight + arc)) | (s >= 2 * straight + arc)
    profile = _loop(np.where(in_arc, 1.0 / radius, 0.0), length, p)

    minima = local_minima_s(profile)
    assert len(minima) == 2
    assert all(in_arc[int(m)] for m in minima)
    # From the braking point (fastest point of the straight) speed only falls
    # until the corner.
    braking_point = int(np.argmax(profile.v_ref_ms[: int(straight)]))
    braking = profile.v_ref_ms[braking_point : int(straight)]
    assert braking.size > 20
    assert np.all(np.diff(braking) <= 1e-9)
    assert profile.v_ref_ms[: int(straight)].max() > 1.5 * profile.v_ref_ms[int(straight) + 10]


@pytest.fixture(scope="module")
def suzuka_model():  # type: ignore[no-untyped-def]
    return read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")


@pytest.mark.parametrize("rule_set_id", ["2026_pre_miami", "2026_post_miami"])
def test_suzuka_profile_never_exceeds_corner_speed(rule_set_id: str, suzuka_model) -> None:  # type: ignore[no-untyped-def]
    track = load_track("suzuka", CONFIG_DIR)
    profile = reference_profile(suzuka_model, track, _params(rule_set_id))

    assert np.all(profile.v_ref_ms <= profile.v_corner_ms + 1e-9)
    assert np.all(profile.v_ref_ms > 0.0)
    # Periodic: continuous across the timing line.
    assert abs(profile.v_ref_ms[0] - profile.v_ref_ms[-1]) < 0.5
    # Uncalibrated placeholders: a plausible, not yet calibrated, lap (real pole 88.8 s).
    assert 80.0 < profile.lap_time_s < 115.0


def test_suzuka_minima_sit_at_corners(suzuka_model) -> None:  # type: ignore[no-untyped-def]
    """Known issue check: curvature overshoot must not add minima at straight/corner joins."""
    track = load_track("suzuka", CONFIG_DIR)
    profile = reference_profile(suzuka_model, track, _params())
    corners = np.array([c.s_m for c in track.corners])
    length = suzuka_model.length_m

    for s in local_minima_s(profile):
        gap = np.min(np.minimum(np.abs(corners - s), length - np.abs(corners - s)))
        assert gap < 160.0, s
    straight_mode_ends = [594.0, 4866.0]  # SM1 / SM2 end: where a join overshoot would show
    for s in local_minima_s(profile):
        assert all(abs(s - end) > 50.0 for end in straight_mode_ends)


def test_less_power_is_slower(suzuka_model) -> None:  # type: ignore[no-untyped-def]
    track = load_track("suzuka", CONFIG_DIR)
    full = reference_profile(suzuka_model, track, _params())
    ice_only = reference_profile(suzuka_model, track, _params(deploy_fraction=0.0))
    post = reference_profile(suzuka_model, track, _params("2026_post_miami"))

    assert ice_only.lap_time_s > full.lap_time_s
    # Post-Miami 250 kW outside acceleration zones costs time vs pre-Miami 350 kW.
    assert post.lap_time_s > full.lap_time_s


def test_placeholders_are_refused() -> None:
    tyres = load_tyres(CONFIG_DIR)
    soft = tyres.compounds[Compound.SOFT].model_copy(update={"c_rr": "UNKNOWN"})
    broken = tyres.model_copy(update={"compounds": {**tyres.compounds, Compound.SOFT: soft}})

    with pytest.raises(ConfigError, match="c_rr"):
        reference_params(
            load_rule_set("2026_pre_miami", CONFIG_DIR),
            load_team_performance(CONFIG_DIR).teams["mercedes"],
            broken,
            Compound.SOFT,
            load_app(CONFIG_DIR),
            load_track("suzuka", CONFIG_DIR),
            70.0,
        )


# --------------------------------------------------------------------------- #
# T-036: the compiled passes give the Python formulas' result
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_set_id", ["2026_pre_miami", "2026_post_miami"])
def test_compiled_passes_match_the_python_formulas(rule_set_id: str, suzuka_model) -> None:  # type: ignore[no-untyped-def]
    import math

    from pitwall_sim.car import speed_profile as sp
    from pitwall_sim.car.dynamics import corner_speed_ms
    from pitwall_sim.track.zones import zone_mask

    p = _params(rule_set_id)
    track = load_track("suzuka", CONFIG_DIR)
    kappa = suzuka_model.curvature_per_m
    straight = zone_mask(track, suzuka_model.s_m, tag="straight_mode_allowed")
    accel = zone_mask(track, suzuka_model.s_m, tag="acceleration_zone")
    ds = suzuka_model.length_m / kappa.size
    v_corner = sp.corner_limits(kappa, straight, p)
    for i in range(0, kappa.size, 97):
        mode = sp.STRAIGHT_MODE if straight[i] else sp.CORNER_MODE
        expected = corner_speed_ms(
            kappa[i], p.mu_lat, p.mass_kg, p.rho, sp.cla(mode, p.aero), p.n_ref_n, p.k_load
        )
        assert v_corner[i] == pytest.approx(expected)

    # Python reference passes, step by step, as before T-036.
    n = kappa.size
    i0 = int(np.argmin(v_corner))
    fwd = np.empty(n)
    v = v_corner[i0]
    for k in range(2 * n):
        i = (i0 + k) % n
        fwd[i] = v
        a = sp._accel_ms2(v, kappa[i], bool(straight[i]), bool(accel[i]), p)
        v = min(math.sqrt(max(v * v + 2.0 * a * ds, 0.0)), v_corner[(i + 1) % n])
    np.testing.assert_allclose(
        sp.forward_pass(kappa, straight, accel, v_corner, ds, p), fwd, rtol=1e-9
    )
    bwd = np.empty(n)
    v = v_corner[i0]
    for k in range(2 * n):
        j = (i0 - k) % n
        bwd[j] = v
        i = (j - 1) % n
        v = (
            v_corner[i]
            if math.isinf(v)
            else min(math.sqrt(v * v + 2.0 * sp.brake_decel_ms2(v, kappa[j], p) * ds), v_corner[i])
        )
    np.testing.assert_allclose(sp.backward_pass(kappa, v_corner, ds, p), bwd, rtol=1e-9)
