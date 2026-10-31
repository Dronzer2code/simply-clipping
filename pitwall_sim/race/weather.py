"""F07 weather: rain, track wetness, grip, track evolution, public forecast (T-039).

TRD WEATHER, PF-14. A race is rainy with probability ``rain_p_per_race`` (track
config; RaceSetup may force dry or rain). In a rainy race the condition (DRY,
DAMP, WET, HEAVY_WET) follows a Markov chain stepped every ``weather.step_s``
(the track's per-minute ``transition_matrix``); a dry race stays DRY. Each step
of length ``dt``:

- ``track_wetness`` rises with the rain intensity of the condition towards 1
  and falls with base drying plus drying by the cars on track:
  ``dw = (wetting x I x (1 - w) - (drying + car_drying x share_on_track) x w) dt``;
- ``track_evolution`` (grip from rubber) gains ``evolution_per_lap`` x (1 - w)
  at each lap of the leader and is washed away by rain at
  ``evolution_wash_per_min`` x w.

Grip: every compound's grip moves linearly from its dry value to
``wet_grip_factor`` x dry on a fully wet track (``tyres.yaml``), times
``1 + track_evolution``. The slick / intermediate / wet crossover is where two
compounds' curves cross; nothing here names a crossover wetness.

Forecast (everyone sees the same): the chance of rain within
``forecast_horizon_s``, from the chain, plus Gaussian noise of
``forecast_noise_sd``, clipped to 0..1, renewed every step.

Forced rain (hackathon E1, "Rain from lap N" on the setup screen): the race starts
dry with the rain *pending* (the forecast already follows the chain); the engine
calls :meth:`WeatherModel.start_rain` when the leader starts lap N. The condition
jumps to ``forced_rain_condition`` and holds there ``forced_rain_hold_s`` before
the track's chain moves it on; the wetness then rises as usual, so the slick /
intermediate crossover comes a lap or two later.

All randomness comes from the RNG stream ``weather`` (HR-04).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

from pitwall_sim.config.models import Compound, TrackConfig, TyreConfig, WeatherConfig
from pitwall_sim.race.state import WeatherCondition, WeatherState

logger = logging.getLogger(__name__)

CONDITIONS: tuple[WeatherCondition, ...] = ("DRY", "DAMP", "WET", "HEAVY_WET")
RainMode = Literal["auto", "dry", "rain"]


def compound_grip(tyres: TyreConfig, compound: Compound, wetness: float) -> float:
    """Grip of ``compound`` relative to its own dry grip at ``wetness`` (0..1)."""
    factor = tyres.compounds[compound].wet_grip_factor
    if isinstance(factor, str):
        return 1.0  # placeholder string: no wet model for this compound
    w = min(max(wetness, 0.0), 1.0)
    return 1.0 + (float(factor) - 1.0) * w


def absolute_grip(tyres: TyreConfig, compound: Compound, wetness: float) -> float:
    """``mu_base`` x :func:`compound_grip`: compares compounds (the crossover)."""
    mu = tyres.compounds[compound].mu_base
    return (float(mu) if not isinstance(mu, str) else 0.0) * compound_grip(tyres, compound, wetness)


def crossover_wetness(tyres: TyreConfig, a: Compound, b: Compound) -> float | None:
    """Wetness at which ``b`` becomes grippier than ``a`` (``None``: never in 0..1).

    Read off the two compounds' grip curves (the lines cross once at most).
    """
    ga0, ga1 = absolute_grip(tyres, a, 0.0), absolute_grip(tyres, a, 1.0)
    gb0, gb1 = absolute_grip(tyres, b, 0.0), absolute_grip(tyres, b, 1.0)
    d0, d1 = gb0 - ga0, gb1 - ga1
    if d0 >= 0.0:
        return 0.0
    if d1 <= 0.0:
        return None
    return d0 / (d0 - d1)


WET_COMPOUNDS: tuple[Compound, ...] = (Compound.INTERMEDIATE, Compound.WET)


def best_compound(tyres: TyreConfig, wetness: float, slick: Compound) -> Compound:
    """Grippiest of ``slick``, INTERMEDIATE and WET at ``wetness`` (ties keep the drier one).

    The crossovers are where this changes; they come from the grip curves only.
    """
    options = [slick, *(c for c in WET_COMPOUNDS if c in tyres.compounds)]
    return max(options, key=lambda c: absolute_grip(tyres, c, wetness))


@dataclass
class WeatherModel:
    """One race's weather (mutates its :class:`WeatherState`)."""

    cfg: WeatherConfig
    state: WeatherState
    matrix: np.ndarray
    """Per-step transition matrix in :data:`CONDITIONS` order."""
    evolution_per_lap: float
    rng: np.random.Generator
    rainy: bool
    forecast_p: float = 0.0
    _since_step_s: float = 0.0
    rain_pending: bool = False
    """Forced rain still to come (dry until :meth:`start_rain`)."""
    _hold_s: float = 0.0

    @classmethod
    def for_race(
        cls,
        cfg: WeatherConfig,
        track: TrackConfig,
        rng: np.random.Generator,
        mode: RainMode = "auto",
        state: WeatherState | None = None,
    ) -> WeatherModel:
        """Draw whether the race is rainy (``auto``) and set up the chain."""
        tw = track.weather
        matrix = (
            np.asarray(tw.transition_matrix, dtype=np.float64)
            if not isinstance(tw.transition_matrix, str)
            else np.eye(len(CONDITIONS))
        )
        if matrix.shape != (len(CONDITIONS), len(CONDITIONS)):
            raise ValueError(f"{track.track_id}: weather.transition_matrix must be 4 x 4")
        rain_p = tw.rain_p_per_race if not isinstance(tw.rain_p_per_race, str) else 0.0
        draw = rng.random()  # always drawn, so the stream does not depend on the mode
        rainy = {"auto": draw < rain_p, "dry": False, "rain": True}[mode]
        evo = track.evolution_per_lap if not isinstance(track.evolution_per_lap, str) else 0.0
        model = cls(cfg, state or WeatherState(), matrix, float(evo), rng, rainy)
        model.forecast_p = model._publish()
        logger.info("weather: %s race (mode %s)", "rainy" if rainy else "dry", mode)
        return model

    @property
    def intensity(self) -> float:
        """Rain intensity of the current condition (0..1)."""
        return float(self.cfg.rain_intensity[self.state.condition])

    def step(self, dt_s: float, share_on_track: float, leader_laps: int = 0) -> bool:
        """Advance ``dt_s``; return whether the condition changed."""
        st, cfg = self.state, self.cfg
        changed = False
        self._since_step_s += dt_s
        self._hold_s = max(self._hold_s - dt_s, 0.0)
        while self._since_step_s >= cfg.step_s:
            self._since_step_s -= cfg.step_s
            if self.rainy and self._hold_s <= 0.0:
                row = self.matrix[CONDITIONS.index(st.condition)]
                new = CONDITIONS[int(np.searchsorted(np.cumsum(row), self.rng.random()))]
                changed |= new != st.condition
                st.condition = new
            self.forecast_p = self._publish()
        minutes = dt_s / 60.0
        w = st.track_wetness
        drying = cfg.drying_per_min + cfg.car_drying_per_min * share_on_track
        w += (cfg.wetting_per_min * self.intensity * (1.0 - w) - drying * w) * minutes
        st.track_wetness = min(max(w, 0.0), 1.0)
        st.track_evolution += leader_laps * self.evolution_per_lap * (1.0 - st.track_wetness)
        st.track_evolution *= max(
            1.0 - cfg.evolution_wash_per_min * st.track_wetness * minutes, 0.0
        )
        return changed

    def true_rain_p(self) -> float:
        """Chance of rain (any condition but DRY) within the forecast horizon."""
        if self.state.condition != "DRY":
            return 1.0
        if not (self.rainy or self.rain_pending):
            return 0.0
        steps = self.cfg.forecast_horizon_s / self.cfg.step_s
        stay = float(self.matrix[0, 0])
        return 1.0 - float(stay**steps)

    def start_rain(self) -> None:
        """Start the forced rain now: ``forced_rain_condition``, held ``forced_rain_hold_s``."""
        self.rainy, self.rain_pending = True, False
        self.state.condition = self.cfg.forced_rain_condition
        self._hold_s = self.cfg.forced_rain_hold_s
        self.forecast_p = self._publish()
        logger.info("weather: forced rain, %s", self.state.condition)

    def _publish(self) -> float:
        noise = float(self.rng.normal(0.0, self.cfg.forecast_noise_sd))
        return min(max(self.true_rain_p() + noise, 0.0), 1.0)

    def grip(self, tyres: TyreConfig, compound: Compound) -> float:
        """Grip factor for a car on ``compound`` now (wetness and track evolution)."""
        return compound_grip(tyres, compound, self.state.track_wetness) * (
            1.0 + self.state.track_evolution
        )
