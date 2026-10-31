"""T-030: Numba step kernel for all cars.

Coefficients are loaded from config at test time (owner round 12), so these
tests hold before and after a calibration rewrites the coefficient files.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st_

from pitwall_sim.calibration.compare import rule_set_for_date, track_arrays
from pitwall_sim.car.battery import battery_params
from pitwall_sim.car.fuel import fuel_params
from pitwall_sim.car.lap_sim import simulate_lap
from pitwall_sim.car.powertrain import mgu_k_allowed_w
from pitwall_sim.car.speed_profile import (
    ProfileParams,
    accel_at_power_ms2,
    backward_pass,
    brake_decel_ms2,
    corner_limits,
    reference_params,
)
from pitwall_sim.config.loader import (
    load_app,
    load_grid,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound
from pitwall_sim.race import step_kernel as K
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
QUALI_LIMIT_MJ = 8.0
FUEL_KG = 5.0


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    app = load_app(CONFIG_DIR)
    track = load_track("suzuka", CONFIG_DIR)
    perf = load_team_performance(CONFIG_DIR)
    tyres = load_tyres(CONFIG_DIR)
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    rules = rule_set_for_date(date(2026, 3, 28), CONFIG_DIR)
    return app, track, perf, tyres, model, rules


def _one_car(world, team_id: str = "mercedes", unlimited: bool = False):  # type: ignore[no-untyped-def]
    app, track, perf, tyres, model, rules = world
    trk = K.kernel_track(model, track)
    glb = K.kernel_globals(rules, app, track, tyres, team_id, perf)
    cars = K.kernel_cars([team_id], [Compound.SOFT], rules, app, perf, tyres, QUALI_LIMIT_MJ)
    if unlimited:
        cars = cars._replace(e_usable_max_j=np.array([1e15]), harvest_limit_j=np.array([1e15]))
    return trk, glb, cars


def _profile(world, team_id: str = "mercedes") -> ProfileParams:  # type: ignore[no-untyped-def]
    app, track, perf, tyres, _, rules = world
    return reference_params(rules, perf.teams[team_id], tyres, Compound.SOFT, app, track, FUEL_KG)


# --------------------------------------------------------------------------- #
# Acceptance: one car matches the single-car Python lap simulation within 0.1 %
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("unlimited", [False, True], ids=["4 MJ battery", "unlimited energy"])
def test_single_car_matches_the_lap_simulation(world, unlimited: bool) -> None:  # type: ignore[no-untyped-def]
    app, track, perf, _, model, rules = world
    team = perf.teams["mercedes"]
    prof = _profile(world)
    batt = battery_params(rules, team, QUALI_LIMIT_MJ)
    start_j = batt.e_usable_max_j
    if unlimited:
        batt = batt._replace(e_usable_max_j=1e15, harvest_limit_j=1e15)
        start_j = 1e14
    arr = track_arrays(model, track)
    ref = simulate_lap(arr.s_m, arr.kappa, arr.straight_mode, arr.accel_zone, arr.length_m,
                       prof, batt, fuel_params(rules, team), battery_start_j=start_j,
                       fuel_kg=FUEL_KG)  # fmt: skip

    ds = arr.length_m / arr.s_m.size
    v_corner = corner_limits(arr.kappa, arr.straight_mode, prof)
    cap = np.minimum(v_corner, backward_pass(arr.kappa, v_corner, ds, prof))
    trk, glb, cars = _one_car(world, unlimited=unlimited)
    cars = cars._replace(k_wear=np.zeros(1))  # the lap simulation has no tyre wear
    state = K.initial_state(1, [0.0], [ref.v_ms[0]], [start_j], [FUEL_KG])
    controls = K.default_controls(1)
    dt = app.sim.dt_s

    t = K.advance(1, dt, 0.0, K.flat_plans(cap[None, :]), trk, glb, cars, controls, state)
    while state.lap[0] == 0:
        t = K.advance(1, dt, t, K.flat_plans(cap[None, :]), trk, glb, cars, controls, state)

    assert state.line_time_s[0] == pytest.approx(ref.lap_time_s, rel=0.001)


# --------------------------------------------------------------------------- #
# Acceptance: <= 20 us per 22-car step
# --------------------------------------------------------------------------- #


def test_22_car_step_is_within_budget(world) -> None:  # type: ignore[no-untyped-def]
    app, track, perf, tyres, model, rules = world
    grid = load_grid("real_2026", CONFIG_DIR)
    teams = [t.team_id for t in grid.teams for _ in t.drivers]
    trk = K.kernel_track(model, track)
    glb = K.kernel_globals(rules, app, track, tyres, teams[0], perf)
    cars = K.kernel_cars(teams, [Compound.MEDIUM] * 22, rules, app, perf, tyres, 8.5)
    state = K.initial_state(22, np.linspace(0.0, 400.0, 22), [60.0] * 22, [4e6] * 22, [70.0] * 22)
    controls = K.default_controls(22)
    v_ref = K.flat_plans(np.full((22, model.s_m.size), 70.0))
    t = K.advance(20, app.sim.dt_s, 0.0, v_ref, trk, glb, cars, controls, state)  # compile

    per_step_us = []
    for _ in range(5):
        start = time.perf_counter()
        t = K.advance(2000, app.sim.dt_s, t, v_ref, trk, glb, cars, controls, state)
        per_step_us.append((time.perf_counter() - start) / 2000 * 1e6)

    print(f"\n22-car step: best {min(per_step_us):.1f} us of 5 (budget 20 us)")
    assert min(per_step_us) <= 20.0, per_step_us


# --------------------------------------------------------------------------- #
# The kernel's formulas against the Python ones
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("v_ms", [20.0, 50.0, 75.0])
@pytest.mark.parametrize("s_m", [100.0, 1300.0, 2890.0])
def test_full_throttle_acceleration_matches_python(world, v_ms: float, s_m: float) -> None:  # type: ignore[no-untyped-def]
    _, _, _, _, model, _ = world
    trk, glb, cars = _one_car(world, unlimited=True)
    prof = _profile(world)
    k = int(s_m / trk.ds_m)
    v = min(v_ms, 0.9 * corner_limits(trk.kappa[k : k + 1], trk.straight_mode[k : k + 1], prof)[0])
    state = K.initial_state(1, [s_m], [v], [1e14], [FUEL_KG])
    controls = K.default_controls(1)
    controls.throttle[0] = 1.0
    dt = 1e-4

    K.step(dt, trk, glb, cars, controls, state)

    p_k = mgu_k_allowed_w(v, bool(trk.accel_zone[k]), False, False, 0.0, 0.0, prof.powertrain)
    expected = accel_at_power_ms2(
        v, trk.kappa[k], bool(trk.straight_mode[k]), prof.p_ice_w + p_k, prof
    )
    assert (state.v_ms[0] - v) / dt == pytest.approx(expected, rel=1e-6, abs=1e-6)


@pytest.mark.parametrize("v_ms", [30.0, 60.0, 85.0])
def test_full_braking_matches_python(world, v_ms: float) -> None:  # type: ignore[no-untyped-def]
    trk, glb, cars = _one_car(world)
    prof = _profile(world)
    s_m = 300.0  # on the main straight
    k = int(s_m / trk.ds_m)
    state = K.initial_state(1, [s_m], [v_ms], [0.0], [FUEL_KG])
    controls = K.default_controls(1)
    controls.brake[0] = 1.0
    dt = 1e-4

    K.step(dt, trk, glb, cars, controls, state)

    assert (v_ms - state.v_ms[0]) / dt == pytest.approx(
        brake_decel_ms2(v_ms, trk.kappa[k], prof), rel=1e-6
    )


def test_speed_is_capped_at_the_corner_speed(world) -> None:  # type: ignore[no-untyped-def]
    trk, glb, cars = _one_car(world)
    prof = _profile(world)
    s_hairpin = 2889.0
    k = int(s_hairpin / trk.ds_m)
    v_in = corner_limits(trk.kappa[k : k + 1], trk.straight_mode[k : k + 1], prof)[0] + 15.0
    state = K.initial_state(1, [s_hairpin], [v_in], [4e6], [FUEL_KG])
    controls = K.default_controls(1)

    K.step(0.05, trk, glb, cars, controls, state)

    # Capped at the corner speed of the point the car reaches.
    k_new = int(state.s_m[0] / trk.ds_m)
    v_limit = corner_limits(
        trk.kappa[k_new : k_new + 1], trk.straight_mode[k_new : k_new + 1], prof
    )
    assert state.v_ms[0] == pytest.approx(v_limit[0], rel=1e-9)
    assert state.v_ms[0] < v_in - 10.0


# --------------------------------------------------------------------------- #
# Invariants over random controls, 22 cars
# --------------------------------------------------------------------------- #

_controls = st_.lists(
    st_.tuples(
        st_.floats(0.0, 1.0), st_.floats(0.0, 1.0), st_.booleans(), st_.booleans(),
        st_.floats(0.0, 1.0),
    ),
    min_size=1,
    max_size=60,
)  # fmt: skip


@settings(max_examples=40, deadline=None)
@given(_controls)
def test_invariants_hold_for_random_controls(world, sequence) -> None:  # type: ignore[no-untyped-def]
    app, track, perf, tyres, model, rules = world
    grid = load_grid("real_2026", CONFIG_DIR)
    teams = [t.team_id for t in grid.teams for _ in t.drivers]
    trk = K.kernel_track(model, track)
    glb = K.kernel_globals(rules, app, track, tyres, teams[0], perf)
    cars = K.kernel_cars(teams, [Compound.MEDIUM] * 22, rules, app, perf, tyres, 8.5)
    state = K.initial_state(22, np.linspace(5000.0, 5800.0, 22), [70.0] * 22, [2e6] * 22,
                            [10.0] * 22)  # fmt: skip
    controls = K.default_controls(22)
    t = 0.0
    for throttle, brake, overtake, clip, deploy in sequence:
        controls.throttle[:] = throttle
        controls.brake[:] = brake
        controls.overtake_active[:] = overtake
        controls.superclip[:] = clip
        controls.deploy_fraction[:] = deploy
        fuel_before = state.fuel_kg.copy()
        wear_before = state.tyre_wear.copy()
        laps_before = state.lap.copy()
        K.step(app.sim.dt_s, trk, glb, cars, controls, state, t)

        assert np.all(state.battery_j >= 0.0)
        assert np.all(state.battery_j <= cars.e_usable_max_j + 1e-6)
        limit = cars.harvest_limit_j + (cars.overtake_extra_j if overtake else 0.0)
        assert np.all(state.harvest_lap_j <= limit + 1e-6)
        assert np.all(state.fuel_kg <= fuel_before) and np.all(state.fuel_kg >= 0.0)
        assert np.all(state.tyre_wear >= wear_before) and np.all(state.tyre_wear <= 1.0)
        assert np.all(state.v_ms >= 0.0)
        assert np.all((state.s_m >= 0.0) & (state.s_m < trk.length_m))
        crossed = state.lap > laps_before
        assert np.all(state.harvest_lap_j[crossed] == 0.0)
        assert np.all(
            (state.line_time_s[crossed] >= t) & (state.line_time_s[crossed] <= t + app.sim.dt_s)
        )
        t += app.sim.dt_s


def test_advance_equals_stepping_one_by_one(world) -> None:  # type: ignore[no-untyped-def]
    app, _, _, _, model, _ = world
    trk, glb, cars = _one_car(world)
    v_ref = K.flat_plans(np.full((1, model.s_m.size), 65.0))
    a = K.initial_state(1, [100.0], [40.0], [3e6], [FUEL_KG])
    b = K.initial_state(1, [100.0], [40.0], [3e6], [FUEL_KG])
    ca, cb = K.default_controls(1), K.default_controls(1)
    dt = app.sim.dt_s

    K.advance(40, dt, 0.0, v_ref, trk, glb, cars, ca, a)
    t = 0.0
    for _ in range(40):
        k = int((b.s_m[0] + b.v_ms[0] * dt) / trk.ds_m) % model.s_m.size
        K.track_speed(dt, np.array([v_ref.v_ref[0, k]]), trk, glb, cars, cb, b)
        K.step(dt, trk, glb, cars, cb, b, t)
        t += dt

    for field in ("s_m", "v_ms", "battery_j", "fuel_kg", "tyre_wear"):
        assert np.allclose(getattr(a, field), getattr(b, field)), field


def test_race_order_matches_lexsort() -> None:
    """The compiled classification equals ``lexsort((finish_t, -progress))``, ties included."""
    rng = np.random.default_rng(42)
    length, offset = 5807.0, 1e9
    for _ in range(500):
        n = 22
        lap = rng.integers(-1, 5, n)
        s = rng.uniform(0.0, length, n)
        if rng.random() < 0.5:  # many ties
            lap[:] = 3
            s[:] = 100.0
        finished = rng.random(n) < 0.3
        retired = (rng.random(n) < 0.1) & ~finished
        finish_t = np.where(finished, rng.choice([90.0, 91.0, 92.0], n), np.inf)
        progress = np.where(finished, lap * length, lap * length + s)
        progress = np.where(retired, progress - offset, progress)
        want = np.lexsort((finish_t, -progress))
        got = K.race_order(lap.astype(np.int64), s, length, finished, retired, finish_t, offset)
        np.testing.assert_array_equal(got, want)
