"""T-033: race engine loop, timing, standing start, finish (PF-04).

One full Suzuka race (config race distance) is run once per module; the other
tests use short races. Coefficients come from config at test time.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.engineer.commands import CommandType, EngineerCommand
from pitwall_sim.race.engine import STAGES, RaceEngine, RaceResult, RaceSetup
from pitwall_sim.race.state import from_arrays, to_arrays

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
#: Enough fuel for 53 laps until T-02B calibrates fuel_start_kg (the 70 kg
#: placeholder runs out near lap 44, and a car at 0 kg retires).
FULL_RACE_FUEL_KG = 110.0


@pytest.fixture(scope="module")
def full_race() -> tuple[RaceEngine, RaceResult]:
    engine = RaceEngine(RaceSetup(fuel_kg=FULL_RACE_FUEL_KG), CONFIG_DIR)
    return engine, engine.run()


def _short(laps: int = 2) -> RaceEngine:
    return RaceEngine(RaceSetup(laps=laps), CONFIG_DIR)


# --------------------------------------------------------------------------- #
# Acceptance: a 22-car race completes
# --------------------------------------------------------------------------- #


def test_full_race_completes(full_race) -> None:  # type: ignore[no-untyped-def]
    engine, result = full_race
    assert engine.n == 22
    assert result.finished
    assert engine.flag == "CHEQUERED"
    assert set(engine.status) == {"FINISHED"}
    winner = result.classification[0]
    assert result.laps_completed[winner] == engine.laps == engine.track.race_laps
    win_t = result.finish_time_s[winner]
    assert win_t is not None
    for driver in result.classification:
        finish = result.finish_time_s[driver]
        assert finish is not None and finish >= win_t
        assert result.laps_completed[driver] <= engine.laps


# --------------------------------------------------------------------------- #
# Acceptance: laps, sectors and gaps consistent
# --------------------------------------------------------------------------- #


def test_lap_times_add_up_to_the_finish_time(full_race) -> None:  # type: ignore[no-untyped-def]
    _, result = full_race
    for driver, laps in result.lap_times_s.items():
        assert len(laps) == result.laps_completed[driver]
        assert sum(laps) == pytest.approx(result.finish_time_s[driver], abs=1e-6)
        assert all(lap > 0.0 for lap in laps)


def test_sectors_add_up_to_the_last_lap(full_race) -> None:  # type: ignore[no-untyped-def]
    engine, _ = full_race
    timing = engine.timing_state()
    for driver in timing.order:
        sectors = timing.sector_s[driver]
        assert all(s is not None and s > 0.0 for s in sectors)
        assert sum(s for s in sectors if s is not None) == pytest.approx(timing.last_lap_s[driver])


def test_classification_and_gaps_at_the_flag(full_race) -> None:  # type: ignore[no-untyped-def]
    engine, result = full_race
    timing = engine.timing_state()
    assert timing.order == result.classification
    winner = timing.order[0]
    assert timing.gap_to_leader_s[winner] == 0.0
    win_t = result.finish_time_s[winner]
    assert win_t is not None
    previous_gap = 0.0
    for ahead, driver in zip(timing.order, timing.order[1:], strict=False):
        down = timing.laps_down[driver]
        assert down == engine.laps - result.laps_completed[driver]
        finish = result.finish_time_s[driver]
        assert finish is not None
        if down == 0:  # same lap: gaps are finish-time differences
            assert timing.gap_to_leader_s[driver] == pytest.approx(finish - win_t)
            assert timing.gap_to_leader_s[driver] >= previous_gap
            previous_gap = timing.gap_to_leader_s[driver]
        if timing.laps_down[ahead] == down:
            ahead_finish = result.finish_time_s[ahead]
            assert ahead_finish is not None
            assert timing.interval_s[driver] == pytest.approx(finish - ahead_finish)


def test_gaps_mid_race_are_consistent() -> None:
    engine = _short(3)
    engine.run(max_t_s=150.0)
    timing = engine.timing_state()
    leader = timing.order[0]
    assert timing.gap_to_leader_s[leader] == 0.0
    for ahead, driver in zip(timing.order, timing.order[1:], strict=False):
        gap = timing.gap_to_leader_s[driver]
        assert gap >= 0.0
        assert timing.interval_s[driver] >= -1e-9
        # Gaps are measured at each car's latest loop, so they agree to within
        # the time between loops.
        assert gap == pytest.approx(
            timing.gap_to_leader_s[ahead] + timing.interval_s[driver], abs=2.0
        )


# --------------------------------------------------------------------------- #
# Acceptance: PF-04 order
# --------------------------------------------------------------------------- #


def test_pf04_stage_order() -> None:
    engine = _short()
    engine.trace = []
    ticks = 2 * engine.decision_steps // engine.chunk_steps
    for _ in range(ticks):
        engine.tick()
    trace = engine.trace
    decision = list(STAGES)
    other = [s for s in STAGES if s not in ("rival_strategy", "ai_driver")]
    i = 0
    n_decisions = 0
    while i < len(trace):
        expected = decision if trace[i + 1] == "rival_strategy" else other
        assert trace[i : i + len(expected)] == expected
        n_decisions += expected is decision
        i += len(expected)
    assert n_decisions == 2
    assert trace[1] == "rival_strategy"  # the first tick is a decision tick


def test_commands_apply_at_their_effective_time() -> None:
    engine = _short()
    applied: list[tuple[float, str]] = []
    engine.command_handler = lambda eng, cmd: applied.append((eng.t, cmd.command_id))
    command = EngineerCommand(
        command_id="c1", issued_at_s=0.0, source="UI", type=CommandType.PUSH_LAP,
        params={}, effective_at_s=2.0,
    )  # fmt: skip
    engine.submit(command)
    while engine.t < 1.99:
        engine.tick()
    assert not applied
    while engine.t < 3.0:
        engine.tick()
    assert [c for _, c in applied] == ["c1"]
    assert applied[0][0] >= 2.0
    assert engine.applied_commands == [command]


# --------------------------------------------------------------------------- #
# Standing start, state mirror, determinism
# --------------------------------------------------------------------------- #


def test_standing_start_from_a_staggered_grid() -> None:
    engine = _short()
    st = engine.st
    spacing = engine.app.race_engine.grid_slot_spacing_m
    assert (st.v_ms == 0.0).all()
    assert (st.lap == -1).all()
    assert np.allclose(np.diff(st.s_m), -spacing)
    assert st.s_m[0] == pytest.approx(engine.trk.length_m - engine.app.race_engine.pole_offset_m)
    # Sector 1 of lap 1 starts from rest; on lap 2 it is flown (energy effects
    # come later in the lap, so the first sector isolates the start).
    sector1: list[list[float]] = [[] for _ in range(engine.n)]
    previous = np.full(engine.n, np.nan)
    while not engine.finished:
        engine.tick()
        current = engine.timing.sectors[:, 0].copy()
        for i in np.flatnonzero(~np.isnan(current) & (current != previous)):
            sector1[i].append(float(current[i]))
        previous = current
    for times in sector1:
        assert times[0] > times[1]


def test_race_state_mirrors_the_kernel() -> None:
    engine = _short()
    engine.run(max_t_s=60.0)
    state = engine.race_state()
    assert [c.driver_id for c in state.cars] == list(engine.driver_ids)
    assert state.track_id == "suzuka" and state.flag == "GREEN"
    for i, car in enumerate(state.cars):
        assert car.battery_mj == pytest.approx(engine.st.battery_j[i] / 1e6)
        assert car.s_m == engine.st.s_m[i] and car.lap == engine.st.lap[i]
        assert car.status == "RUNNING"
    assert from_arrays(to_arrays(state.cars)) == state.cars
    assert state.timing.order == engine.timing_state().order


def test_same_setup_same_race() -> None:
    first, second = _short().run(), _short().run()
    assert first.classification == second.classification
    assert first.lap_times_s == second.lap_times_s


def test_overtake_mode_detection_uses_the_rule_gap() -> None:
    engine = _short(3)
    seen = np.zeros(engine.n, dtype=bool)
    while not engine.finished:
        engine.tick()
        seen |= engine.overtake_available
    assert seen.any()
    assert engine.detection_loops
    assert math.isclose(engine.activation_gap_s, float(engine.rules.overtake.activation_gap_s))


# --------------------------------------------------------------------------- #
# Out of fuel (owner round 13: a car at 0 kg stops, DNF "out of fuel")
# --------------------------------------------------------------------------- #


def test_a_car_out_of_fuel_retires() -> None:
    engine = _short(2)
    i = engine.driver_ids.index("VER")
    engine.st.fuel_kg[i] = 0.05  # a few seconds of fuel
    engine.run(max_t_s=30.0)
    assert engine.status[i] == "DNF"
    assert engine.retired == {i: "out of fuel"}
    assert not engine.st.running[i] and engine.st.v_ms[i] == 0.0
    s_stopped = float(engine.st.s_m[i])
    result = engine.run()
    assert result.finished
    assert engine.st.s_m[i] == s_stopped  # it never moves again
    assert result.classification[-1] == "VER"
    assert result.retired == {"VER": "out of fuel"}
    assert result.finish_time_s["VER"] is None
    assert all(engine.status[k] == "FINISHED" for k in range(engine.n) if k != i)
    assert engine.timing_state().laps_down["VER"] == 0


def test_no_ice_power_without_fuel() -> None:
    engine = _short(1)
    st, ctl = engine.st, engine.ctl
    st.v_ms[:] = 50.0
    st.battery_j[:] = 0.0  # no MGU-K either
    ctl.throttle[:] = 1.0
    st.fuel_kg[0], st.fuel_kg[1] = 0.0, 10.0
    from pitwall_sim.race import step_kernel as K

    K.step(engine.dt, engine.trk, engine.glb, engine.cars, ctl, st)
    assert st.power_w[0] == 0.0 and st.power_w[1] > 0.0
