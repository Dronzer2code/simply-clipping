"""AP-04 EngineerView builder: the only object in-race UI receives (T-052, PF-06).

:class:`EngineerViewBuilder` turns the running race into an
:class:`EngineerView` (TRD DATA CONTRACTS):

- ``our_car``: Our Car's full Ground Truth (``CarState``);
- ``timing``: public timing for every car (positions, gaps, laps, sectors,
  compound, tyre age, pit stops, penalties);
- ``rival_feed``: each Rival's Public Feed frames of the last ``view_window_s``;
- ``radar``: each Rival's Radar Estimate, from that Rival's feed only (the
  engine's ``RadarBank``, updated with every feed frame);
- ``flag``, ``weather_public``, ``radio_log`` (R3) and ``predictor`` (R2);
- hackathon: ``track_status`` (SC / VSC, public), ``strategy`` (the strategy
  panel's plans, from Radar Estimates and public tyre data only) and the radio
  log as :class:`RadioEvent`.

Information barrier (HR-02 / HR-03, PF-06): no Rival Ground Truth
(``battery_mj``, ``energy_mode``, ``tyre_wear``, ``fuel_kg``, plans) and no
reference to the engine, the kernel state or ``RaceState`` ever reaches the
view; ``ui/`` may not import ``race.state`` (import-linter ``ui-info-barrier``).
Rival Ground Truth is released only in the debrief, after the chequered flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pitwall_sim.engineer.predictor import PredictorOutput
from pitwall_sim.engineer.records import RadioEvent, StrategyResult
from pitwall_sim.observe.frames import PublicFeedFrame
from pitwall_sim.observe.radar.energy import RadarEstimate
from pitwall_sim.race.state import CarState, TimingState, TrackStatus

if TYPE_CHECKING:
    from pitwall_sim.race.engine import RaceEngine

#: Rival feed shown in the view, seconds (STRUCTURAL; the feed keeps more for the Radar).
VIEW_WINDOW_S = 30.0


@dataclass(frozen=True)
class PublicWeather:
    """Weather everyone can see (T-039 adds the noisy rain forecast)."""

    condition: Literal["DRY", "DAMP", "WET", "HEAVY_WET"] = "DRY"
    rain_forecast_p: float | None = None
    """Chance of rain in the next 10 min, as published (T-039); ``None`` until then."""


@dataclass(frozen=True)
class EngineerView:
    """The ONLY object the in-race UI receives (TRD DATA CONTRACTS)."""

    t_s: float
    our_car: CarState
    """Full Ground Truth for Our Car."""
    timing: TimingState
    """Public timing for all cars."""
    rival_feed: dict[str, list[PublicFeedFrame]]
    """Recent window per Rival."""
    radar: dict[str, RadarEstimate]
    flag: str
    weather_public: PublicWeather
    radio_log: list[RadioEvent]
    predictor: PredictorOutput | None
    track_status: TrackStatus = field(default_factory=TrackStatus)
    """Safety Car / VSC (public)."""
    strategy: tuple[StrategyResult, ...] | None = None
    """Strategy panel plans (H5), or None until computed."""


class EngineerViewBuilder:
    """Builds EngineerViews for one race and one Our Car."""

    def __init__(
        self, engine: RaceEngine, our_driver_id: str, view_window_s: float = VIEW_WINDOW_S
    ):
        """Build views of ``engine`` for Our Car ``our_driver_id``."""
        if our_driver_id not in engine.driver_ids:
            raise ValueError(f"{our_driver_id} is not in this race")
        self._engine = engine
        self.our_index = engine.driver_ids.index(our_driver_id)
        self.view_window_s = view_window_s
        self.rivals = tuple(d for d in engine.driver_ids if d != our_driver_id)
        self.radio_log: list[RadioEvent] = []
        self.strategy: tuple[StrategyResult, ...] | None = None
        """Set by the strategy worker (H5); built from public data and Radar Estimates."""

    def build(self) -> EngineerView:
        """Build the view of the race now (call at the UI rate)."""
        engine = self._engine
        index = {d: i for i, d in enumerate(engine.driver_ids)}
        radar = {d: engine.radar_estimate(index[d]) for d in self.rivals}
        feed = engine.feed.recent(since_s=engine.t - self.view_window_s)
        return EngineerView(
            t_s=engine.t,
            our_car=engine.car_state(self.our_index),
            timing=engine.timing_state(),
            rival_feed={d: feed.get(d, []) for d in self.rivals},
            radar=radar,
            flag=engine.flag,
            weather_public=PublicWeather(engine.weather.condition, engine.weather_model.forecast_p),
            radio_log=list(self.radio_log),
            predictor=None,
            track_status=engine.track_status,
            strategy=self.strategy,
        )
