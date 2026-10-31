"""Hackathon E1: a forced rain race, the Rivals' wet crossover, BOX INTER, the rain radio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pitwall_sim.config.models import Compound
from pitwall_sim.engineer.commands import CommandType, EngineerCommand, make_command
from pitwall_sim.engineer.radio_parser import parse
from pitwall_sim.live.session import LiveSession, LiveSetup
from pitwall_sim.live.strategy import plans_for
from pitwall_sim.race import weather as W
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.pit import PitPhase

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
OUR = "GAS"
RAIN_LAP = 3
UNTIL_S = 1000.0
INTER = Compound.INTERMEDIATE


@dataclass
class RainRun:
    """One forced-rain race and when the rain and the crossover came."""

    engine: RaceEngine
    rain_t: float
    leader_lap_at_rain: int
    cross_t: float


def _rain_race(seed: int = 42, until_s: float = UNTIL_S) -> RainRun:
    e = RaceEngine(
        RaceSetup(seed=seed, laps=10, fuel_kg=110.0, our_driver_id=OUR, rain_lap=RAIN_LAP),
        CONFIG_DIR,
    )
    # The field runs MEDIUM, then HARD after a dry stop: the earlier of the two crossovers.
    crossings = [W.crossover_wetness(e.tyres, c, INTER) for c in (Compound.MEDIUM, Compound.HARD)]
    cross = min(c for c in crossings if c is not None)
    rain_t = cross_t = float("nan")
    leader_lap = -1
    while e.t < until_s and not e.finished:
        before = e.weather.condition
        e.tick()
        if before == "DRY" and e.weather.condition != "DRY":
            rain_t, leader_lap = e.t, int(e.st.lap[e.st.running].max()) + 1
        if cross_t != cross_t and e.weather.track_wetness >= cross:  # first time (nan)
            cross_t = e.t
    return RainRun(e, rain_t, leader_lap, cross_t)


@pytest.fixture(scope="module")
def rain() -> RainRun:
    return _rain_race()


def test_forced_rain_starts_on_the_chosen_lap(rain: RainRun) -> None:
    e = rain.engine
    assert rain.leader_lap_at_rain == RAIN_LAP
    assert e.weather.condition == e.app.weather.forced_rain_condition  # held for 10 min
    assert rain.rain_t < rain.cross_t < UNTIL_S  # wetness reaches the crossover after the rain


def test_rivals_box_for_inters_around_the_crossover(rain: RainRun) -> None:
    e = rain.engine
    our = e.our_index
    wet_boxes = [p for p in e.pit.events
                 if p.phase == PitPhase.BOX_PENDING and p.compound == INTER]  # fmt: skip
    assert len(wet_boxes) >= 15  # most of the 21 Rivals
    assert all(p.car != our for p in wet_boxes)  # Our Car stops only when we call it
    assert all(p.t_s >= rain.cross_t for p in wet_boxes)  # never before the crossover
    times = sorted(p.t_s for p in wet_boxes)
    assert times[-1] - times[0] > 150.0  # more than a lap apart: some do "one more lap"
    laps = {lap for lap, _, _ in e.rivals_wet_boxed}
    assert len(laps) >= 2 and all(c == INTER for _, _, c in e.rivals_wet_boxed)
    on_inters = [d for i, d in enumerate(e.driver_ids) if e.compounds[i] == INTER]
    assert len(on_inters) >= 15 and OUR not in on_inters


def test_rain_race_is_deterministic(rain: RainRun) -> None:
    again = _rain_race(until_s=600.0)
    first = _rain_race(until_s=600.0)
    assert again.rain_t == first.rain_t and again.cross_t == first.cross_t
    assert again.engine.rivals_wet_boxed == first.engine.rivals_wet_boxed
    assert again.engine.contacts == first.engine.contacts
    assert again.engine.weather == first.engine.weather


def test_our_car_boxes_for_inters_and_the_panel_offers_them() -> None:
    e = RaceEngine(
        RaceSetup(seed=3, laps=6, fuel_kg=110.0, our_driver_id=OUR, rain_lap=2), CONFIG_DIR
    )
    dry_compounds = {c for _, c in plans_for(e) if c is not None}
    assert INTER not in dry_compounds
    while e.weather.condition == "DRY":
        e.tick()
    while e.weather.track_wetness < 0.1:
        e.tick()
    assert INTER in {c for _, c in plans_for(e) if c is not None}  # strategy panel, wet track
    i = e.our_index
    assert i is not None
    ctx = e.command_context()
    parsed = parse("box box, inters", {}, ctx.lap, "HARD")
    assert parsed.commands[0].params["compound"] == "INTERMEDIATE"
    cmd = make_command(CommandType.BOX, parsed.commands[0].params, ctx, e.app.engineer, e.t,
                       e.app.radio.radio_latency_s)  # fmt: skip
    assert isinstance(cmd, EngineerCommand), cmd  # validated (HR-07)
    e.submit(cmd)
    limit = e.t + 400.0
    while e.compounds[i] != INTER and e.t < limit and not e.finished:
        e.tick()
    assert e.compounds[i] == INTER and e.tyre_laps[i] <= 1


def test_session_rain_radio_and_plain_box_means_inters() -> None:
    s = LiveSession(LiveSetup(our_driver_id=OUR, laps=5, rain_lap=2), CONFIG_DIR)
    try:
        while s.frame().view.weather_public.condition == "DRY" and s.advance(5.0):
            pass
        driver = [line.text for line in s.radio if line.sender == "DRIVER"]
        assert any(t.startswith("Rain at Turn") and t.endswith("slippery.") for t in driver)
        assert s.radio_message("box box") == []
        s.advance(3.0)
        i = s.engine.our_index
        assert i is not None
        planned = s.engine._box_plan.get(i, (0, None))[1]
        assert INTER in (planned, s.engine.pit.next_compound[i])
    finally:
        s.close()
