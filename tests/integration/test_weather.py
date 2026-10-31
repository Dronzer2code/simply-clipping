"""T-039 / MVP-12: weather, track wetness, grip, crossover, forecast (PF-14)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.compare import track_arrays
from pitwall_sim.car.speed_profile import reference_params, speed_profile
from pitwall_sim.config.loader import (
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound, TyreConfig
from pitwall_sim.observe.engineer_view import EngineerViewBuilder
from pitwall_sim.race import weather as W
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.state import WeatherState
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def tyres() -> TyreConfig:
    return load_tyres(CONFIG_DIR)


def _lap_s(tyres: TyreConfig, compound: Compound, wetness: float) -> float:
    app, track = load_app(CONFIG_DIR), load_track("suzuka", CONFIG_DIR)
    model = read_track_model(ROOT / app.paths.tracks / "suzuka.parquet")
    arrays = track_arrays(model, track)
    p = reference_params(
        load_rule_set("2026_post_miami", CONFIG_DIR),
        load_team_performance(CONFIG_DIR).teams["mercedes"], tyres, compound, app, track, 40.0,
        grip_track=W.compound_grip(tyres, compound, wetness),
    )  # fmt: skip
    a = arrays
    return speed_profile(a.s_m, a.kappa, a.straight_mode, a.accel_zone, a.length_m, p).lap_time_s


def test_mvp12_rain_makes_intermediates_faster(tyres: TyreConfig) -> None:
    """The crossover emerges from the tyres.yaml grip curves (none is coded)."""
    w = W.crossover_wetness(tyres, Compound.SOFT, Compound.INTERMEDIATE)
    assert w is not None and 0.0 < w < 1.0
    assert _lap_s(tyres, Compound.SOFT, 0.0) < _lap_s(tyres, Compound.INTERMEDIATE, 0.0)
    assert _lap_s(tyres, Compound.INTERMEDIATE, 1.0) < _lap_s(tyres, Compound.SOFT, 1.0)
    # Just either side of the crossover the faster compound swaps.
    assert _lap_s(tyres, Compound.SOFT, w - 0.05) < _lap_s(tyres, Compound.INTERMEDIATE, w - 0.05)
    assert _lap_s(tyres, Compound.INTERMEDIATE, w + 0.05) < _lap_s(tyres, Compound.SOFT, w + 0.05)
    # Change the curves and the crossover moves with them.
    inter = tyres.compounds[Compound.INTERMEDIATE].model_copy(update={"wet_grip_factor": 1.0})
    moved = tyres.model_copy(
        update={"compounds": {**tyres.compounds, Compound.INTERMEDIATE: inter}}
    )
    w2 = W.crossover_wetness(moved, Compound.SOFT, Compound.INTERMEDIATE)
    assert w2 is not None and w2 < w


def _model(
    mode: W.RainMode, matrix: list[list[float]] | None = None, seed: int = 42
) -> W.WeatherModel:
    track = load_track("suzuka", CONFIG_DIR)
    if matrix is not None:
        weather = track.weather.model_copy(update={"transition_matrix": matrix})
        track = track.model_copy(update={"weather": weather})
    return W.WeatherModel.for_race(
        load_app(CONFIG_DIR).weather, track, np.random.default_rng(seed), mode
    )


def test_wetness_rises_in_rain_and_dries_with_cars() -> None:
    always_wet = [[0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 0.0],
                  [0.0, 0.0, 1.0, 0.0]]  # fmt: skip
    m = _model("rain", always_wet)
    for _ in range(10 * 60):
        m.step(1.0, 1.0)
    assert m.state.condition == "WET" and 0.5 < m.state.track_wetness < 1.0
    wet = m.state.track_wetness
    dry = [[1.0, 0.0, 0.0, 0.0]] * 4
    with_cars, without = _model("rain", dry), _model("rain", dry)
    for model in (with_cars, without):
        model.state.track_wetness = wet
    for _ in range(5 * 60):
        with_cars.step(1.0, 1.0)
        without.step(1.0, 0.0)
    assert with_cars.state.track_wetness < without.state.track_wetness < wet


def test_dry_race_stays_dry_and_the_track_evolves() -> None:
    m = _model("dry")
    for _ in range(20):
        m.step(90.0, 1.0, leader_laps=1)
        assert m.state.condition == "DRY" and m.state.track_wetness == 0.0
    assert m.state.track_evolution == pytest.approx(20 * m.evolution_per_lap)
    assert m.true_rain_p() == 0.0 and 0.0 <= m.forecast_p <= 1.0


def test_forecast_is_noisy_and_follows_the_chain() -> None:
    m = _model("rain")
    stay = float(m.matrix[0, 0])
    assert m.true_rain_p() == pytest.approx(1.0 - stay ** (m.cfg.forecast_horizon_s / m.cfg.step_s))
    seen = set()
    for _ in range(30):
        m.step(m.cfg.step_s, 1.0)
        assert 0.0 <= m.forecast_p <= 1.0
        seen.add(round(m.forecast_p, 6))
    assert len(seen) > 5  # renewed every step, with noise


def test_rain_mode_and_stream() -> None:
    """``auto`` draws from the track's rain probability on stream ``weather`` (HR-04)."""
    cfg, track = load_app(CONFIG_DIR).weather, load_track("suzuka", CONFIG_DIR)
    rainy = [
        W.WeatherModel.for_race(cfg, track, np.random.default_rng(seed), "auto").rainy
        for seed in range(2000)
    ]
    assert sum(rainy) / 2000 == pytest.approx(track.weather.rain_p_per_race, abs=0.03)
    engine = RaceEngine(RaceSetup(laps=2, rain="rain"), CONFIG_DIR)
    assert engine.weather_model.rng is engine.rngs["weather"]
    assert engine.weather_model.state is engine.weather


def test_wet_track_slows_slick_cars_and_replans_them() -> None:
    engine = RaceEngine(RaceSetup(laps=3, rain="rain"), CONFIG_DIR)
    v_ref_dry = engine.plans.v_ref[0].copy()
    engine.weather_model.matrix = np.tile([0.0, 0.0, 0.0, 1.0], (4, 1))  # heavy rain now
    engine.weather.condition = "HEAVY_WET"
    for _ in range(8 * 60 * 4):  # 8 min
        engine.tick()
    slick = W.compound_grip(engine.tyres, engine.compounds[0], engine.weather.track_wetness)
    assert engine.weather.track_wetness > 0.5
    assert engine.ctl.grip_factor[0] == pytest.approx(
        slick * (1 + engine.weather.track_evolution), rel=0.03
    )
    assert engine.plans.v_ref[0].mean() < 0.95 * v_ref_dry.mean()  # PF-14: profiles recomputed
    view = EngineerViewBuilder(engine, engine.driver_ids[0]).build()
    assert view.weather_public.condition == "HEAVY_WET"
    assert view.weather_public.rain_forecast_p == engine.weather_model.forecast_p


def test_weather_state_round_trips_in_a_snapshot() -> None:
    engine = RaceEngine(RaceSetup(laps=3, rain="rain"), CONFIG_DIR)
    engine.weather.condition, engine.weather.track_wetness = "WET", 0.4
    fork = RaceEngine.from_snapshot(engine.snapshot())
    assert fork.weather == WeatherState("WET", 0.4, engine.weather.track_evolution)
    assert fork.weather_model.state is fork.weather  # the model drives the copy
    assert fork.weather_model.rng is fork.rngs["weather"]
