"""Hackathon E1: forced rain onset and the Rivals' wet crossover rules (T-062 weather)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app, load_track, load_tyres
from pitwall_sim.config.models import Compound
from pitwall_sim.race import rival_strategy as RS
from pitwall_sim.race import weather as W

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TYRES = load_tyres(CONFIG_DIR)
CFG = load_app(CONFIG_DIR).rival_strategy


def _book(n: int) -> RS.RivalBook:
    plans = {f"C{k}": RS.RivalPlan(f"C{k}", 5, Compound.HARD, 0.5) for k in range(n)}
    return RS.RivalBook.from_plans(plans, tuple(plans))


def test_best_compound_follows_the_grip_curves() -> None:
    cross = W.crossover_wetness(TYRES, Compound.MEDIUM, Compound.INTERMEDIATE)
    assert cross is not None and 0.0 < cross < 1.0
    assert W.best_compound(TYRES, 0.0, Compound.MEDIUM) == Compound.MEDIUM
    assert W.best_compound(TYRES, cross - 0.02, Compound.MEDIUM) == Compound.MEDIUM
    assert W.best_compound(TYRES, cross + 0.02, Compound.MEDIUM) in W.WET_COMPOUNDS
    wet = W.best_compound(TYRES, 1.0, Compound.MEDIUM)
    assert wet == max(W.WET_COMPOUNDS, key=lambda c: W.absolute_grip(TYRES, c, 1.0))


def test_crosses_over_only_between_tyre_classes() -> None:
    assert RS.crosses_over(Compound.MEDIUM, Compound.INTERMEDIATE)
    assert RS.crosses_over(Compound.INTERMEDIATE, Compound.HARD)
    assert RS.crosses_over(Compound.INTERMEDIATE, Compound.WET)
    assert not RS.crosses_over(Compound.MEDIUM, Compound.HARD)  # a dry stop, not this branch
    assert not RS.crosses_over(Compound.INTERMEDIATE, Compound.INTERMEDIATE)


def test_wet_box_waits_each_cars_delay() -> None:
    book = _book(3)
    book.wet_delay_laps[:] = [0, 1, 2]
    due = [RS.wet_box_due(book, k, Compound.MEDIUM, Compound.INTERMEDIATE, 5, 20) for k in range(3)]
    assert due == [True, False, False]
    assert RS.wet_box_due(book, 1, Compound.MEDIUM, Compound.INTERMEDIATE, 6, 20)
    assert not RS.wet_box_due(book, 2, Compound.MEDIUM, Compound.INTERMEDIATE, 6, 20)
    # The track dries back before the third car's lap: its call is dropped.
    assert not RS.wet_box_due(book, 2, Compound.MEDIUM, Compound.MEDIUM, 7, 20)
    assert book.wet_due_lap[2] == -1
    # Never on the last lap.
    assert not RS.wet_box_due(book, 0, Compound.MEDIUM, Compound.INTERMEDIATE, 19, 20)


def test_wet_delays_are_drawn_in_range_and_repeatable() -> None:
    a, b = _book(21), _book(21)
    RS.draw_wet_delays(a, CFG, np.random.default_rng(7))
    RS.draw_wet_delays(b, CFG, np.random.default_rng(7))
    assert a.wet_delay_laps.tolist() == b.wet_delay_laps.tolist()
    assert 0 <= a.wet_delay_laps.min() and a.wet_delay_laps.max() <= CFG.wet_delay_max_laps
    assert len(set(a.wet_delay_laps.tolist())) > 1  # spread: not every car on one lap
    assert (a.wet_due_lap == -1).all()


def test_forced_rain_starts_and_holds() -> None:
    app, track = load_app(CONFIG_DIR), load_track("suzuka", CONFIG_DIR)
    always_dry = [[1.0, 0.0, 0.0, 0.0]] * 4  # the chain would end the rain at once
    track = track.model_copy(
        update={"weather": track.weather.model_copy(update={"transition_matrix": always_dry})}
    )
    m = W.WeatherModel.for_race(app.weather, track, np.random.default_rng(1), "dry")
    m.rain_pending = True
    for _ in range(10):
        m.step(60.0, 1.0)
    assert m.state.condition == "DRY" and m.state.track_wetness == 0.0
    m.start_rain()
    assert m.rainy and not m.rain_pending
    assert m.state.condition == app.weather.forced_rain_condition
    hold_steps = int(app.weather.forced_rain_hold_s // app.weather.step_s)
    for _ in range(hold_steps - 1):
        m.step(app.weather.step_s, 1.0)
    assert m.state.condition == app.weather.forced_rain_condition
    assert m.state.track_wetness > 0.5
    for _ in range(3):
        m.step(app.weather.step_s, 1.0)
    assert m.state.condition == "DRY"  # after the hold the track's chain takes over


def test_contact_shares_must_sum_to_one() -> None:
    events = load_app(CONFIG_DIR).race_events
    with pytest.raises(ValueError, match="contact_shares"):
        events.model_validate({**events.model_dump(), "contact_shares": {"LIGHT": 0.5}})
