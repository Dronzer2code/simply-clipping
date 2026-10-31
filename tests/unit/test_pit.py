"""T-035: pit lane state machine (PF-12), stop times, tyre change on exit.

Coefficients come from config at test time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.pit_stops import pit_stop_stats
from pitwall_sim.car.tyres import tyre_params
from pitwall_sim.config.models import Compound
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.pit import PitLane, PitPhase
from pitwall_sim.race.snapshot import make_rngs

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DRIVER = "ANT"


def _race_with_stop(box: bool) -> tuple[RaceEngine, int, list[tuple[float, float, bool, float]]]:
    """Three laps; with ``box`` the car is called in on lap 1 for HARD tyres."""
    engine = RaceEngine(RaceSetup(laps=3), CONFIG_DIR)
    i = engine.driver_ids.index(DRIVER)
    trace = []  # (t, s, in_pit, v)
    called = False
    while not engine.finished:
        if box and not called and engine.st.lap[i] == 1:
            called = engine.box(i, Compound.HARD)
        engine.tick()
        trace.append(
            (engine.t, float(engine.st.s_m[i]), bool(engine.st.in_pit[i]), float(engine.st.v_ms[i]))
        )
    return engine, i, trace


@pytest.fixture(scope="module")
def with_stop() -> tuple[RaceEngine, int, list[tuple[float, float, bool, float]]]:
    return _race_with_stop(True)


@pytest.fixture(scope="module")
def without_stop() -> RaceEngine:
    return _race_with_stop(False)[0]


# --------------------------------------------------------------------------- #
# Acceptance: PF-12 transitions tested; tyre reset on exit
# --------------------------------------------------------------------------- #


def test_pf12_transitions_in_order(with_stop) -> None:  # type: ignore[no-untyped-def]
    engine, i, _ = with_stop
    phases = [e.phase for e in engine.pit.events if e.car == i]
    assert phases == [
        PitPhase.BOX_PENDING,
        PitPhase.PIT_LANE_IN,
        PitPhase.STATIONARY,
        PitPhase.PIT_LANE_OUT,
        PitPhase.RUNNING,
    ]
    assert engine.pit.phase[i] == PitPhase.RUNNING
    assert engine.status[i] == "FINISHED"


def test_tyres_reset_on_exit(with_stop) -> None:  # type: ignore[no-untyped-def]
    engine, i, _ = with_stop
    exit_event = [e for e in engine.pit.events if e.car == i][-1]
    assert exit_event.compound == Compound.HARD
    assert engine.compounds[i] == Compound.HARD
    hard = tyre_params(engine.tyres, Compound.HARD)
    assert engine.cars.mu_base[i] == hard.mu_base and engine.cars.k_wear[i] == hard.k_wear
    # Fresh at the exit: the wear and age since are the laps after the stop only.
    laps_after = engine.st.lap[i] - exit_lap(engine, i)
    assert engine.tyre_laps[i] == laps_after
    assert engine.st.tyre_wear[i] < 0.05 * max(laps_after, 1)


def exit_lap(engine: RaceEngine, i: int) -> int:
    exit_t = [e.t_s for e in engine.pit.events if e.car == i][-1]
    crossings = np.cumsum(engine.timing.lap_times[i])
    return int(np.searchsorted(crossings, exit_t))


def test_stationary_at_the_box_for_the_drawn_time(with_stop) -> None:  # type: ignore[no-untyped-def]
    engine, i, trace = with_stop
    events = {e.phase: e for e in engine.pit.events if e.car == i}
    stop = events[PitPhase.STATIONARY]
    assert stop.stationary_s is not None and stop.stationary_s >= engine.app.pit.stop_min_s
    released = events[PitPhase.PIT_LANE_OUT].t_s
    assert released - stop.t_s == pytest.approx(
        stop.stationary_s, abs=engine.dt * engine.chunk_steps
    )
    still = [(s, v) for t, s, _, v in trace if stop.t_s <= t < released]
    assert len({s for s, _ in still}) == 1 and all(v == 0.0 for _, v in still)


def test_pit_lane_speed_limit_and_isolation(with_stop) -> None:  # type: ignore[no-untyped-def]
    engine, i, trace = with_stop
    limit = engine.glb.pit_speed_ms
    start, end = engine.glb.pit_limit_start_m, engine.glb.pit_limit_end_m

    def limited(s: float) -> bool:
        return start <= s < end if start <= end else (s >= start or s < end)

    in_lane = [(s, v) for _, s, pit, v in trace if pit]
    assert in_lane
    # Inside the limit (allowing the braking step into it) the car is at the limit.
    assert max(v for s, v in in_lane if limited(s) and limited(s - 30.0)) <= limit + 0.5


def test_a_stop_costs_about_the_real_pit_loss(with_stop, without_stop) -> None:  # type: ignore[no-untyped-def]
    engine, i, _ = with_stop
    loss = engine.timing.finish_t[i] - without_stop.timing.finish_t[i]
    # MultiViewer pitLoss.normal at Suzuka 22.8 s (track config note).
    assert 15.0 < loss < 30.0


# --------------------------------------------------------------------------- #
# State machine without a race
# --------------------------------------------------------------------------- #


def test_box_and_cancel_rules() -> None:
    engine = RaceEngine(RaceSetup(laps=1), CONFIG_DIR)
    pit = PitLane(engine.track.pit, engine.app.pit, 2, engine.trk.length_m, make_rngs(1)["pit"])
    assert pit.request_box(0, Compound.SOFT)
    assert not pit.request_box(0, Compound.HARD)  # already pending
    assert pit.cancel_box(0) and pit.phase[0] == PitPhase.RUNNING
    assert not pit.cancel_box(1)  # nothing to cancel
    pit.request_box(1, Compound.SOFT)
    st = engine.st
    s_before = st.s_m.copy()
    s_before[1] = (pit.entry_s_m - 10.0) % engine.trk.length_m
    st.s_m[1] = (pit.entry_s_m + 10.0) % engine.trk.length_m
    pit.step(1.0, s_before[:2], _first_two(st))
    assert pit.phase[1] == PitPhase.PIT_LANE_IN
    assert not pit.cancel_box(1)  # too late after the entry


def _first_two(st):  # type: ignore[no-untyped-def]
    return type(st)(*(a[:2] for a in st))


def test_stop_time_distribution_follows_config() -> None:
    engine = RaceEngine(RaceSetup(laps=1), CONFIG_DIR)
    cfg = engine.app.pit
    pit = PitLane(engine.track.pit, cfg, 1, engine.trk.length_m, make_rngs(3)["pit"])
    draws = np.array([pit.stationary_time_s() for _ in range(4000)])
    assert draws.min() >= cfg.stop_min_s
    expected = cfg.stop_mean_s + cfg.slow_stop_p * cfg.slow_stop_extra_s
    assert draws.mean() == pytest.approx(expected, abs=0.1)
    again = PitLane(engine.track.pit, cfg, 1, engine.trk.length_m, make_rngs(3)["pit"])
    assert again.stationary_time_s() == draws[0]


def test_pit_stop_stats_split_slow_stops() -> None:
    rows = [{"stop_duration": d, "lane_duration": 20.0 + d} for d in (2.0, 2.2, 2.4, 2.6, 2.8, 9.0)]
    stats = pit_stop_stats(rows)
    assert stats.n_stops == 6 and stats.slow_stop_p == pytest.approx(1 / 6)
    assert stats.stop_mean_s == pytest.approx(2.4) and stats.stop_min_s == 2.0
    assert stats.slow_stop_extra_s == pytest.approx(9.0 - 2.4)
