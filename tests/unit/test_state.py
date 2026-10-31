"""T-020: CarState / RaceState contracts and the lossless parallel-array mirror."""

from __future__ import annotations

from dataclasses import fields

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from numba import njit

from pitwall_sim.race.state import (
    AERO_MODES,
    COMPOUNDS,
    ENERGY_MODES,
    STATUSES,
    CarArrays,
    CarState,
    RaceState,
    TimingState,
    WeatherState,
    from_arrays,
    to_arrays,
)

_finite = st.floats(allow_nan=False, allow_infinity=False, width=64)
_ints = st.integers(min_value=-(2**62), max_value=2**62)

car_states = st.builds(
    CarState,
    driver_id=st.text(min_size=1, max_size=4),
    team_id=st.text(min_size=1, max_size=12),
    s_m=_finite,
    lap=_ints,
    line=st.integers(0, 2),
    v_ms=_finite,
    throttle=_finite,
    brake=_finite,
    gear=st.integers(0, 8),
    aero_mode=st.sampled_from(AERO_MODES),
    battery_mj=_finite,
    harvest_mj_lap=_finite,
    deploy_mj_lap=_finite,
    overtake_available=st.booleans(),
    overtake_active=st.booleans(),
    energy_mode=st.sampled_from(ENERGY_MODES),
    compound=st.sampled_from(COMPOUNDS),
    tyre_age_laps=_ints,
    tyre_wear=_finite,
    tyre_temp_c=_finite,
    fuel_kg=_finite,
    damage=_finite,
    status=st.sampled_from(STATUSES),
    penalties_s=_finite,
    track_limit_warnings=_ints,
)


@settings(max_examples=200, deadline=None)
@given(st.lists(car_states, max_size=22))
def test_round_trip_is_lossless(cars: list[CarState]) -> None:
    rebuilt = from_arrays(to_arrays(cars))

    assert rebuilt == cars
    for before, after in zip(cars, rebuilt, strict=True):
        for f in fields(CarState):
            # Same Python type back, not a NumPy scalar.
            assert type(getattr(after, f.name)) is type(getattr(before, f.name)), f.name


def _car(i: int) -> CarState:
    return CarState(
        driver_id=f"D{i:02d}",
        team_id="team",
        s_m=10.0 * i,
        lap=1,
        line=0,
        v_ms=80.0,
        throttle=1.0,
        brake=0.0,
        gear=8,
        aero_mode="STRAIGHT_MODE",
        battery_mj=2.0,
        harvest_mj_lap=0.0,
        deploy_mj_lap=0.0,
        overtake_available=False,
        overtake_active=False,
        energy_mode="BALANCED",
        compound=COMPOUNDS[0],
        tyre_age_laps=0,
        tyre_wear=0.0,
        tyre_temp_c=100.0,
        fuel_kg=70.0,
        damage=0.0,
        status="RUNNING",
        penalties_s=0.0,
        track_limit_warnings=0,
    )


def test_arrays_are_contiguous_and_typed_for_numba() -> None:
    arrays = to_arrays([_car(i) for i in range(22)])

    assert arrays.n_cars == 22
    for f in fields(CarArrays):
        value = getattr(arrays, f.name)
        if isinstance(value, np.ndarray):
            assert value.shape == (22,), f.name
            assert value.flags.c_contiguous, f.name
    assert arrays.s_m.dtype == np.float64
    assert arrays.lap.dtype == np.int64
    assert arrays.overtake_active.dtype == np.bool_
    assert arrays.aero_mode.dtype == np.int8


def test_arrays_are_independent_of_the_dataclasses() -> None:
    cars = [_car(i) for i in range(3)]
    arrays = to_arrays(cars)

    arrays.s_m[0] = 999.0
    cars[1].s_m = -1.0

    assert cars[0].s_m == 0.0
    assert arrays.s_m[1] == 10.0


@njit(cache=False)
def _advance(s_m: np.ndarray, v_ms: np.ndarray, running: np.ndarray, dt_s: float) -> None:
    for i in range(s_m.size):
        if running[i]:
            s_m[i] += v_ms[i] * dt_s


def test_numba_kernel_runs_on_the_mirror() -> None:
    cars = [_car(i) for i in range(4)]
    cars[2].status = "PIT"
    arrays = to_arrays(cars)
    running = arrays.status == STATUSES.index("RUNNING")

    _advance(arrays.s_m, arrays.v_ms, running, 0.05)
    moved = from_arrays(arrays)

    assert [c.s_m for c in moved] == [4.0, 14.0, 20.0, 34.0]


def test_race_state_holds_the_contract_fields() -> None:
    state = RaceState(
        t_s=0.0,
        seed=42,
        rule_set_id="2026_post_miami",
        track_id="suzuka",
        grid_id="real_2026",
        cars=[_car(0)],
        flag="GREEN",
        weather=WeatherState(),
        timing=TimingState(),
        pending_commands=[],
    )

    assert [f.name for f in fields(RaceState)] == [
        "t_s", "seed", "rule_set_id", "track_id", "grid_id",
        "cars", "flag", "weather", "timing", "pending_commands", "track_status",
    ]  # fmt: skip
    assert state.weather.condition == "DRY"
