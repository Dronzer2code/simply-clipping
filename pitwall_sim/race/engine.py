"""F05 race engine main loop (T-033; TRD Per-step order, PF-04).

:class:`RaceEngine` runs one race from a standing start to the chequered flag.
Ground Truth lives in the step kernel's arrays (``step_kernel.KernelState``);
:meth:`RaceEngine.race_state` mirrors it into the TRD ``RaceState`` on demand.

Each :meth:`RaceEngine.tick` covers one feed interval (``1 / feed.rate_hz``,
5 physics steps at 20 Hz) and runs the PF-04 stages in order::

    1 commands       queued EngineerCommands with effective_at_s <= t
    2 decision tick  rival_strategy, ai_driver.decide (every sim.decision_tick_s)
    3 weather        (T-039)
    4 kernel         step_kernel.advance: every physics step of the interval
    5 overtake       (T-034)
    6 pit            (T-035)
    7 events         (T-038)
    8 timing         laps, sectors, gaps, finish
    9 public_feed    (T-050)
    10 t += dt       inside the kernel

Stages 1-3 and 5-9 run once per interval, not once per physics step: one
Python pass per 0.05 s step would cost more than the whole kernel. The kernel
records every timing-loop and line crossing at its interpolated step time, so
timing stays exact. Stages owned by later tasks are no-op hooks here.

Timing: the kernel's timing loops are the sector ends, the Overtake detection
points and mini-sector loops every ``race_engine.timing_loop_spacing_m``. A car's
gap to the leader is its time at its latest loop minus the leader's time at the
same loop on the same lap; its interval is the same against the car classified
ahead of it. ``lap`` counts completed laps: the grid is behind the line at lap
-1, the start crossing begins lap 1 (``lap`` 0), and lap 1 is timed from the
start (t = 0). The leader completing ``laps`` laps shows the chequered flag;
every car finishes at its next line crossing after that.
"""

from __future__ import annotations

import argparse
import copy
import logging
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from pitwall_sim.car.speed_profile import reference_params
from pitwall_sim.car.tyres import tyre_params, tyre_temp_c
from pitwall_sim.config.loader import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    load_app,
    load_race_config,
    resolve_harvest_limit_mj,
)
from pitwall_sim.config.models import Compound, ContactSeverity, EnergyMode, MistakeKind
from pitwall_sim.driver import ai_driver as D
from pitwall_sim.engineer.commands import CommandContext, CommandType, EngineerCommand
from pitwall_sim.observe.public_feed import PublicFeed
from pitwall_sim.observe.radar.energy import RadarBank, RadarEstimate
from pitwall_sim.race import rival_strategy as RS
from pitwall_sim.race import step_kernel as K
from pitwall_sim.race import weather as W
from pitwall_sim.race.overtake import OvertakeEvent, OvertakeModel, trigger_points
from pitwall_sim.race.pit import PitEvent, PitLane, PitPhase
from pitwall_sim.race.snapshot import Snapshot, make_rngs, rng_states
from pitwall_sim.race.state import (
    CarState,
    CarStatus,
    Flag,
    RaceState,
    StartState,
    TimingState,
    TrackStatus,
    TrackStatusName,
    WeatherState,
)
from pitwall_sim.race.weather import RainMode, WeatherModel
from pitwall_sim.track.builder import read_track_model
from pitwall_sim.track.zones import zone_ids_mask, zone_mask

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]

#: PF-04 stage names, in order (``RaceEngine.trace`` records them).
STAGES = (
    "commands",
    "rival_strategy",
    "ai_driver",
    "weather",
    "kernel",
    "overtake",
    "pit",
    "events",
    "timing",
    "public_feed",
)
LINE = -1
"""Timing-loop key of the line itself."""
MJ = 1e6
DNF_OFFSET_M = 1e9
NO_LIMIT = 10**9
"""``_attack_until`` / ``_defend_until`` without a lap limit."""
"""Classification offset that puts retired cars behind every car still classified."""
NOMINAL_LAP_S = 120.0
"""Upper bound on a lap for the race time limit (``race_engine.max_race_factor``)."""


def _shape_key(instructions: D.DriverInstructions) -> tuple[object, ...]:
    """Return the instructions that shape a lap's speed profile."""
    i = instructions
    return (
        i.mode, i.push_lap, i.manage_tyres, i.lift_coast, i.let_teammate_by, i.lift_zones,
        i.follow_close,
    )  # fmt: skip


def _plan_key(instructions: D.DriverInstructions) -> tuple[object, ...]:
    """Return the instructions that shape a lap plan (the rest act at decision ticks)."""
    return (*_shape_key(instructions), instructions.keep_deploy)


@dataclass(frozen=True)
class MistakeEvent:
    """One AI Driver mistake (T-037)."""

    t_s: float
    car: int
    kind: MistakeKind
    corner_id: str


@dataclass(frozen=True)
class ContactEvent:
    """Contact in an overtake attempt (T-038): LIGHT, or the attacker out (VSC / SC)."""

    t_s: float
    attacker: int
    defender: int
    severity: ContactSeverity


@dataclass(frozen=True)
class RaceSetup:
    """What the user picks on Race Setup (S1) for one race."""

    track_id: str = "suzuka"
    rule_set_id: str = "2026_post_miami"
    grid_id: str = "real_2026"
    seed: int = 42
    laps: int | None = None
    """Race distance; ``None`` = the track's ``race_laps``."""
    harvest_limit_mj: float | None = None
    """User override of the race harvest limit (S1); ``None`` = track / Rule Set."""
    grid_order: tuple[str, ...] | None = None
    """driver_ids from pole; ``None`` = grid file order."""
    start_compound: Compound | None = None
    """``None`` = ``race_engine.start_compound``."""
    fuel_kg: float | None = None
    """Start fuel per car; ``None`` = the track's ``fuel_start_kg``."""
    our_driver_id: str | None = None
    """The user's car (Rivals see it in the Public Feed); ``None`` in headless runs."""
    rain: RainMode = "auto"
    """``auto``: rainy with the track's ``rain_p_per_race``; ``dry`` / ``rain`` force it."""
    scripted_sc_lap: int | None = None
    """Force a Safety Car when the leader starts this lap; ``None`` = ``demo.scripted_sc_lap``."""
    start: StartState | None = None
    """Pick the race up mid-way (E3 real race moment); ``None`` = standing start.
    ``grid_order`` must then list the cars in ``start.cars`` order."""
    rain_lap: int | None = None
    """Force rain when the leader starts this lap (E1); ``None`` = ``demo.rain_lap``.

    The race is dry until then (``rain`` is ignored unless it is ``dry``, which wins)."""


@dataclass
class RaceResult:
    """Classification and lap times after a race (or when stopped)."""

    finished: bool
    t_s: float
    classification: list[str]
    """driver_ids, winner first (finished, then running, by distance)."""
    laps_completed: dict[str, int]
    finish_time_s: dict[str, float | None]
    lap_times_s: dict[str, list[float]]
    retired: dict[str, str]
    """driver_id -> reason, for every DNF."""


@dataclass
class _Timing:
    """Engine-side timing bookkeeping (arrays per car)."""

    n: int
    gap_s: FloatArray = field(init=False)
    interval_s: FloatArray = field(init=False)
    line_t: FloatArray = field(init=False)
    sector_start_t: FloatArray = field(init=False)
    sectors: FloatArray = field(init=False)
    last_lap_s: FloatArray = field(init=False)
    finish_t: FloatArray = field(init=False)
    lap_battery_j: FloatArray = field(init=False)
    lap_times: list[list[float]] = field(init=False)
    crossings: dict[tuple[int, int], dict[int, float]] = field(default_factory=dict)
    last_pass_t: dict[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.gap_s = np.zeros(self.n)
        self.interval_s = np.zeros(self.n)
        self.line_t = np.zeros(self.n)
        self.sector_start_t = np.zeros(self.n)
        self.sectors = np.full((self.n, 3), np.nan)
        self.last_lap_s = np.full(self.n, np.nan)
        self.finish_t = np.full(self.n, np.inf)
        self.lap_battery_j = np.zeros(self.n)
        self.lap_times = [[] for _ in range(self.n)]


def start_positions(
    start: StartState, order: Sequence[str], length_m: float
) -> tuple[npt.NDArray[np.int64], FloatArray]:
    """``(laps_done, s_m)`` per car of ``order`` at a mid-race start (E3).

    Track position = completed laps x length + lap share x length; a running car
    closer than ``start.min_spacing_m`` to the running car ahead of it is moved back
    to that spacing. Retired cars keep their position (they are off the road).
    """
    by_id = {c.driver_id: c for c in start.cars}
    progress = {c.driver_id: (c.laps_done + c.lap_fraction) * length_m for c in start.cars}
    ahead: float | None = None
    for car in start.cars:  # running order
        if car.retired:
            continue
        if ahead is not None:
            progress[car.driver_id] = min(progress[car.driver_id], ahead - start.min_spacing_m)
        ahead = progress[car.driver_id]
    laps = np.array([math.floor(progress[d] / length_m) for d in order], dtype=np.int64)
    s_m = np.array([progress[d] for d in order], dtype=np.float64) - laps * length_m
    for k, d in enumerate(order):
        if by_id[d].retired:
            laps[k] = by_id[d].laps_done
    return laps, s_m


class RaceEngine:
    """One race: config, kernel arrays, AI Drivers, timing (PF-04)."""

    def __init__(self, setup: RaceSetup, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        """Load config, build the track, cars, grid and the drivers' first plans.

        Raises:
            ConfigError: A value the race needs is missing or still a placeholder.

        """
        cfg = load_race_config(setup.rule_set_id, setup.grid_id, setup.track_id, config_dir)
        assert cfg.track is not None
        self.setup = setup
        self.app, self.rules, self.grid, self.perf, self.tyres = (
            cfg.app, cfg.rules, cfg.grid, cfg.teams, cfg.tyres,
        )  # fmt: skip
        self.track = cfg.track
        eng = self.app.race_engine
        tracks_dir = Path(self.app.paths.tracks)
        if not tracks_dir.is_absolute():
            tracks_dir = config_dir.resolve().parent / tracks_dir
        self.model = read_track_model(tracks_dir / f"{self.track.track_id}.parquet")
        length = self.model.length_m

        laps = setup.laps if setup.laps is not None else self.track.race_laps
        if not isinstance(laps, int) or laps < 1:
            raise ConfigError(f"track {self.track.track_id}: race_laps is {laps}")
        self.laps = laps
        fuel = setup.fuel_kg if setup.fuel_kg is not None else self.track.fuel_start_kg
        if not isinstance(fuel, (int, float)):
            raise ConfigError(f"track {self.track.track_id}: fuel_start_kg is {fuel}")

        # Cars, grid order and team ids (HR-06: ids only).
        team_of = {d.driver_id: t.team_id for t in self.grid.teams for d in t.drivers}
        order = setup.grid_order or tuple(team_of)
        if sorted(order) != sorted(team_of):
            raise ConfigError(f"grid_order must list every driver of grid {setup.grid_id}")
        self.driver_ids: tuple[str, ...] = tuple(order)
        self.team_ids: tuple[str, ...] = tuple(team_of[d] for d in order)
        n = self.n = len(order)
        compound = setup.start_compound or eng.start_compound
        self.compounds = [compound] * n
        start = setup.start
        start_cars = {c.driver_id: c for c in start.cars} if start is not None else {}
        if start is not None:
            if sorted(start_cars) != sorted(order):
                raise ConfigError("start state must list every car on the grid")
            self.compounds = [start_cars[d].compound for d in order]

        # Track with timing loops: sector ends, detection points, mini-sectors.
        mini = np.arange(eng.timing_loop_spacing_m, length - 1.0, eng.timing_loop_spacing_m)
        loops = np.unique(
            np.concatenate([mini, self.track.sector_ends_m, self.track.detection_points_m]).astype(
                np.float64
            )
        )
        loops = loops[(loops > 0.0) & (loops < length)]
        self.sector_loops = [int(np.searchsorted(loops, s)) for s in self.track.sector_ends_m]
        self.detection_loops = {
            int(np.searchsorted(loops, s)) for s in self.track.detection_points_m
        }
        self.trk = K.kernel_track(self.model, self.track, loops)
        self.glb = K.kernel_globals(
            self.rules, self.app, self.track, self.tyres, self.team_ids[0], self.perf
        )
        self.harvest_limit_mj = resolve_harvest_limit_mj(
            self.rules, self.track, setup.harvest_limit_mj
        )
        self.cars = K.kernel_cars(
            self.team_ids, self.compounds, self.rules, self.app, self.perf, self.tyres,
            self.harvest_limit_mj,
        )  # fmt: skip
        self.ot_zone = zone_mask(self.track, self.model.s_m, zone_type="overtaking")
        gap = self.rules.overtake.activation_gap_s
        if isinstance(gap, str):
            raise ConfigError(
                f"rule set {self.rules.rule_set_id}: overtake.activation_gap_s is {gap}"
            )
        self.activation_gap_s = float(gap)

        # Standing start: staggered slots behind the line, lap -1, full battery.
        grid_s = [length - eng.pole_offset_m - k * eng.grid_slot_spacing_m for k in range(n)]
        battery = self.cars.e_usable_max_j * eng.start_battery_fraction
        self.st = K.initial_state(n, grid_s, [0.0] * n, battery, [float(fuel)] * n, loops)
        self.st.lap[:] = -1
        if start is not None:  # mid-race: real positions, laps and tyres (E3)
            laps_done, s_m = start_positions(start, order, length)
            battery = self.cars.e_usable_max_j * start.battery_fraction
            self.st = K.initial_state(n, s_m, [0.0] * n, battery, [float(fuel)] * n, loops)
            self.st.lap[:] = laps_done
            self.st.tyre_wear[:] = [start_cars[d].tyre_wear for d in order]
        self.ctl = K.default_controls(n)

        # RNG streams (HR-04) and drivers.
        self.rngs = make_rngs(setup.seed)
        # Weather (T-039) before the first plans: they use the grip it gives.
        self.weather = WeatherState()
        rain_lap = setup.rain_lap if setup.rain_lap is not None else self.app.demo.rain_lap
        self._rain_lap = rain_lap if setup.rain != "dry" else None
        """Forced rain (E1): the leader's lap it starts on, until it has started."""
        self.weather_model = WeatherModel.for_race(
            self.app.weather, self.track, self.rngs["weather"],
            "dry" if self._rain_lap is not None else setup.rain, self.weather,
        )  # fmt: skip
        self.weather_model.rain_pending = self._rain_lap is not None
        self.instructions = [D.DriverInstructions() for _ in range(n)]
        self._instruction_arrays = D.instruction_arrays(self.instructions, self.app.ai_driver)
        self.balances = [D.EnergyBalance(self.app.ai_driver.energy_feedback_gain) for _ in range(n)]
        self.line = np.zeros(n, dtype=np.int64)
        self.overtake_available = np.zeros(n, dtype=np.bool_)
        self.status: list[CarStatus] = ["RUNNING"] * n
        self._finished = np.zeros(n, dtype=np.bool_)
        self._retired = np.zeros(n, dtype=np.bool_)
        self.retired: dict[int, str] = {}
        self.tyre_laps = np.zeros(n, dtype=np.int64)
        if start is not None:
            self.tyre_laps[:] = [start_cars[d].tyre_age_laps for d in order]
        self._plan_cache: dict[tuple[object, ...], D.CarPlan] = {}
        self._planned_grip = np.ones(n)
        self._weather_lap = -1
        self._grip_surface: tuple[float, float] | None = None
        self._grip_rounded: dict[Compound, float] = {}
        self._aim_j = np.zeros(n)
        car_plans = [self._plan_car(i) for i in range(n)]
        self.car_plans = car_plans
        self.plans = D.kernel_plans(car_plans)
        if start is not None:  # a flying start: every car at its planned speed
            k = (self.st.s_m / self.trk.ds_m).astype(np.int64)
            for i, plan in enumerate(car_plans):
                self.st.v_ms[i] = float(plan.v_ref[int(k[i]) % plan.v_ref.size])

        # Overtakes (T-034) and pit stops (T-035).
        skill = {d.driver_id: d.skill_racecraft for t in self.grid.teams for d in t.drivers}
        self.overtake = OvertakeModel(
            self.app.overtake,
            trigger_points(self.track, self.app.overtake, self.model.s_m, car_plans[0].v_ref),
            self.trk,
            self.rngs["overtake"],
            np.array([skill[d] for d in self.driver_ids], dtype=np.float64),
        )
        self.pit = PitLane(self.track.pit, self.app.pit, n, length, self.rngs["pit"])
        # Rival Strategy AI (T-041) for every car except Our Car.
        styles = {
            t: str(p.strategy_style) if p.strategy_style != "UNKNOWN" else "BALANCED"
            for t, p in self.perf.teams.items()
        }  # fmt: skip
        aggression = {
            t: float(p.aggression) if not isinstance(p.aggression, str) else 0.5
            for t, p in self.perf.teams.items()
        }  # fmt: skip
        self.rival_plans = RS.make_plans(
            self.driver_ids, self.team_ids, styles, aggression, laps, compound,
            self.app.rival_strategy, self.rngs["rival_strategy"],
        )  # fmt: skip
        self.rival_plans.pop(str(setup.our_driver_id), None)
        for driver, rival in self.rival_plans.items():  # mid-race: stops already made
            if driver in start_cars:
                car = start_cars[driver]
                rival.stops_done = car.pit_stops
                rival.stop_lap = max(rival.stop_lap, car.laps_done)
                rival.next_compound = (
                    Compound.HARD if car.compound != Compound.HARD else Compound.MEDIUM
                )
        self.rival_book = RS.RivalBook.from_plans(self.rival_plans, self.driver_ids)
        # Drawn after every plan, so the plans' own draws are as before (E1).
        RS.draw_wet_delays(self.rival_book, self.app.rival_strategy, self.rngs["rival_strategy"])
        self.rivals_wet_boxed: list[tuple[int, str, Compound]] = []
        """(Rival's completed laps, driver_id, compound) of every wet-crossover call (E1)."""
        if setup.our_driver_id is not None and setup.our_driver_id not in self.driver_ids:
            raise ConfigError(f"our_driver_id {setup.our_driver_id} is not on the grid")
        self.feed = PublicFeed(
            self.app.feed, self.rngs["feed_noise"], self.driver_ids,
            self.model.x_m,
            self.model.y_m, self.model.heading_rad, length,
        )  # fmt: skip
        # Every car is in the Public Feed, Our Car too: rival teams see its public
        # telemetry (owner, day 6). Our own pit wall lists only the Rivals
        # (EngineerViewBuilder), and nobody sees Our Car's true battery (HR-03).
        # Rival Battery Radar for every car, from the Public Feed only (TRD, PF-06):
        # updated with each feed frame, read at decision ticks (owner round 15).
        sm_zones = [(z.s_start_m, z.s_end_m) for z in self.track.zones
                    if "straight_mode_allowed" in z.tags]  # fmt: skip
        self.radar = RadarBank(n, self.app.radar, sm_zones, length, self.app.feed.rate_hz)
        self._radar_pending: list[Any] = []
        self._s_before = self.st.s_m.copy()
        # AI Driver mistakes at corners (T-037).
        consistency = {d.driver_id: d.skill_consistency for t in self.grid.teams for d in t.drivers}
        self.skill_consistency = np.array([consistency[d] for d in self.driver_ids])
        self._corners = sorted(self.track.corners, key=lambda c: c.s_m)
        self._corner_s = np.array([c.s_m for c in self._corners], dtype=np.float64)
        # Each car's next corner and its race distance (lap x length + s): one
        # compare per tick finds the cars that passed a corner.
        self._next_corner = np.searchsorted(self._corner_s, self.st.s_m, side="right")
        wrapped = self._next_corner >= self._corner_s.size
        self._next_corner %= max(self._corner_s.size, 1)
        self._next_corner_d = (
            (self.st.lap + wrapped) * length + self._corner_s[self._next_corner]
            if self._corner_s.size
            else np.full(n, np.inf)
        )
        self.mistakes: list[MistakeEvent] = []
        self.contacts: list[ContactEvent] = []
        """Overtake contacts (T-038)."""

        # Clock and timing.
        dt = self.app.sim.dt_s
        self.dt = dt
        self.chunk_steps = max(1, round(1.0 / (self.app.feed.rate_hz * dt)))
        self.decision_steps = max(1, round(self.app.sim.decision_tick_s / dt))
        self.t = 0.0
        self.steps = 0
        self.flag: Flag = "GREEN"
        self.track_status = TrackStatus()
        """Safety Car / VSC state (H4); public."""
        self.track_events: list[tuple[float, str, str]] = []
        """(t, status, reason) at every Safety Car / VSC change."""
        scripted = setup.scripted_sc_lap
        self._scripted_sc_lap = scripted if scripted is not None else self.app.demo.scripted_sc_lap
        self.sc_rivals_boxed: list[str] = []
        self._sc_end_lap = 0
        """Leader's completed laps at which the Safety Car comes in."""
        """Rivals the SC / VSC pit branch called in (H4)."""
        self.finish_order: list[int] = []
        self.timing = _Timing(n)
        self.timing.lap_battery_j[:] = self.st.battery_j
        self.prior_pit_stops = np.zeros(n, dtype=np.int64)
        """Stops made before the race was picked up mid-way (E3)."""
        if start is not None:
            self._start_timing(start)
        self._prev_next = self.st.next_loop.copy()
        self._prev_lap = self.st.lap.copy()
        self._classification = np.arange(n)
        self._rank = np.arange(n)
        self.max_t_s = laps * NOMINAL_LAP_S * eng.max_race_factor
        self.pending_commands: list[EngineerCommand] = []
        self.applied_commands: list[EngineerCommand] = []
        self.command_handler: Callable[[RaceEngine, EngineerCommand], None] | None = None
        """Replaces the built-in Our Car handling (tests observe commands with it)."""
        # Engineer Commands for Our Car (T-061).
        self.our_index = (
            self.driver_ids.index(setup.our_driver_id) if setup.our_driver_id is not None else None
        )
        self._box_plan: dict[int, tuple[int, Compound]] = {}
        self._push_until = np.full(n, -(10**9), dtype=np.int64)
        # ATTACK / DEFEND calls last until the situation is over (owner, sprint day 5).
        self._attack_until = np.full(n, NO_LIMIT, dtype=np.int64)
        self._attack_mode: dict[int, EnergyMode] = {}
        """Energy Mode to go back to when an ATTACK (which drives in PUSH) ends."""
        self._defend_until = np.full(n, NO_LIMIT, dtype=np.int64)
        self._defend_threat = np.full(n, -1, dtype=np.int64)
        """The car behind when DEFEND was called (-1: none)."""
        self._ot_rules: list[tuple[bool, int | None, str | None]] = []
        self._ot_zone_masks = {
            z.zone_id: zone_ids_mask(self.track, self.model.s_m, [z.zone_id])
            for z in self.track.zones
            if z.type == "overtaking"
        }
        self.trace: list[str] | None = None
        self.auto_snapshots: list[Snapshot] = []
        """One per lap, taken when the leader crosses the timing line (PF-04)."""
        self.auto_snapshot = True
        self._leader_lap = False
        for d, car in start_cars.items():
            if car.retired:
                self.retire(self.driver_ids.index(d), "retired before the start lap")

    def _start_timing(self, start: StartState) -> None:
        """Public timing at a mid-race start: each car's last line crossing and gaps."""
        tm = self.timing
        for car in start.cars:
            i = self.driver_ids.index(car.driver_id)
            tm.line_t[i] = tm.sector_start_t[i] = -car.lap_elapsed_s
            tm.gap_s[i], tm.interval_s[i] = car.gap_s, car.interval_s
            self.prior_pit_stops[i] = car.pit_stops
            if not car.retired:
                tm.crossings.setdefault((car.laps_done, LINE), {})[i] = -car.lap_elapsed_s

    # ------------------------------------------------------------------ #
    # Driver plans
    # ------------------------------------------------------------------ #

    def _plan_car(self, i: int) -> D.CarPlan:
        """Full plan for car ``i`` (shared by cars in the same situation)."""
        st, team, instr = self.st, self.team_ids[i], self.instructions[i]
        battery, fuel, wear = float(st.battery_j[i]), float(st.fuel_kg[i]), float(st.tyre_wear[i])
        grip = self._plan_grip(i)
        key = (team, self.compounds[i], instr, round(battery / 1e5), round(fuel), round(wear, 2),
               grip)  # fmt: skip
        if key not in self._plan_cache:
            prof = reference_params(
                self.rules, self.perf.teams[team], self.tyres, self.compounds[i], self.app,
                self.track, fuel, wear=wear, grip_track=grip,
            )  # fmt: skip
            predictor = D.LapPredictor.for_car(self.app.sim.dt_s, self.trk, self.glb, self.cars, i)
            self._plan_cache[key] = D.plan_lap(
                predictor, self.model.s_m, self.track, prof, instr, self.app.ai_driver, battery,
                fuel, wear,
            )  # fmt: skip
        self._aim_j[i] = D.lap_target_change_j(
            instr.mode, battery, self.app.ai_driver, float(self.cars.e_usable_max_j[i])
        )
        return self._plan_cache[key]

    def _set_plan(self, i: int, plan: D.CarPlan) -> None:
        self._planned_grip[i] = self._plan_grip(i)
        self.car_plans[i] = plan
        self.plans.v_ref[i] = plan.v_ref
        self.plans.deploy[i] = plan.deploy
        self.plans.superclip[i] = plan.superclip
        self.plans.throttle_cap[i] = plan.throttle_cap
        self.plans.part_harvest[i] = plan.part_harvest

    def box(self, i: int, compound: Compound) -> bool:
        """Call car ``i`` in for ``compound`` (PF-12 BOX; T-061 wires the command)."""
        return self.pit.request_box(i, compound, self.t)

    def cancel_box(self, i: int) -> bool:
        """Cancel car ``i``'s stop before the pit entry (PF-12 CANCEL_BOX)."""
        return self.pit.cancel_box(i, self.t)

    def set_instructions(self, i: int, instructions: D.DriverInstructions) -> None:
        """Give car ``i`` new instructions (T-061 wires commands here).

        Attack / defend / hold flags act at the next decision tick; a change of
        Energy Mode or of what shapes the lap re-shapes the plan at the current
        deploy level (no lap predictions: the per-lap energy retune follows).
        """
        old = self.instructions[i]
        self.instructions[i] = instructions
        D.set_instruction_row(self._instruction_arrays, i, instructions, self.app.ai_driver)
        if _plan_key(instructions) != _plan_key(old):
            self._set_plan(i, self._reshape_car(i))

    def _reshape_car(self, i: int) -> D.CarPlan:
        """Plan car ``i`` for its current instructions and tyres at its current deploy level."""
        st, team, instr, cfg = self.st, self.team_ids[i], self.instructions[i], self.app.ai_driver
        fuel, wear = float(st.fuel_kg[i]), float(st.tyre_wear[i])
        key = (
            "shape",
            team,
            self.compounds[i],
            _shape_key(instr),
            round(fuel / 10.0),
            round(wear * 5.0),
            self._plan_grip(i),
        )
        if key not in self._plan_cache:
            prof = reference_params(
                self.rules, self.perf.teams[team], self.tyres, self.compounds[i], self.app,
                self.track, fuel, wear=wear, grip_track=self._plan_grip(i),
            )  # fmt: skip
            self._plan_cache[key] = D.shape_plan(
                self.trk, self.model.s_m, self.track, prof, replace(instr, keep_deploy=False), cfg
            )
        old = self.car_plans[i]
        plan = replace(
            self._plan_cache[key], reserve_straights=instr.keep_deploy,
            level_slope_j=old.level_slope_j,
        ).with_level(old.deploy_level)  # fmt: skip
        battery = float(st.battery_j[i])
        self._aim_j[i] = D.lap_target_change_j(
            instr.mode, battery, cfg, float(self.cars.e_usable_max_j[i])
        )
        return plan

    def _new_lap_energy(self, i: int) -> None:
        """Retune car ``i``'s deploy level from the lap it just finished.

        The level moves by the change of the Energy Mode's target (PUSH: spend
        down to the reserve, then hold) plus ``energy_feedback_gain`` x the
        last lap's miss, through the plan's battery slope (no lap prediction).
        """
        cfg = self.app.ai_driver
        battery = float(self.st.battery_j[i])
        change = battery - self.timing.lap_battery_j[i]
        self.timing.lap_battery_j[i] = battery
        aimed = self._aim_j[i]
        self.balances[i].update(change, aimed)
        aim = D.lap_target_change_j(
            self.instructions[i].mode, battery, cfg, float(self.cars.e_usable_max_j[i])
        )
        more = (aim - aimed) + cfg.energy_feedback_gain * (aimed - change)
        self._set_plan(i, self.car_plans[i].relevel(more))
        self._aim_j[i] = aim

    # ------------------------------------------------------------------ #
    # PF-04 stages
    # ------------------------------------------------------------------ #

    def _mark(self, stage: str) -> None:
        if self.trace is not None:
            self.trace.append(stage)

    def submit(self, command: EngineerCommand) -> None:
        """Queue an Engineer Command; it applies at ``effective_at_s``."""
        self.pending_commands.append(command)
        self.pending_commands.sort(key=lambda c: c.effective_at_s)

    def _apply_commands(self) -> None:
        self._mark("commands")
        while self.pending_commands and self.pending_commands[0].effective_at_s <= self.t:
            command = self.pending_commands.pop(0)
            if self.command_handler is not None:
                self.command_handler(self, command)
            else:
                self._apply_command(command)
            self.applied_commands.append(command)

    # ------------------------------------------------------------------ #
    # Engineer Commands (T-061, TRD ENGINEER COMMANDS / AI DRIVER)
    # ------------------------------------------------------------------ #

    def command_context(self) -> CommandContext:
        """Public facts for validating Our Car's commands (PF-07)."""
        i = self.our_index
        if i is None:
            raise ValueError("no Our Car in this race")
        tm = self.timing
        mate = self._teammate(i)
        behind = (
            float(tm.gap_s[mate] - tm.gap_s[i])
            if mate is not None and self._rank[mate] > self._rank[i] and self.st.running[mate]
            else None
        )
        return CommandContext(
            lap=int(self.st.lap[i]) + 1,
            race_laps=self.laps,
            zone_ids=frozenset(z.zone_id for z in self.track.zones),
            overtake_zone_ids=frozenset(self._ot_zone_masks),
            corner_ids=frozenset(c.corner_id for c in self._corners),
            compounds=frozenset(
                c for c, t in self.tyres.compounds.items() if not isinstance(t.mu_base, str)
            ),
            box_pending=self.pit.phase[i] == PitPhase.BOX_PENDING,
            past_pit_entry=self.pit.in_lane(i),
            teammate_gap_behind_s=behind,
        )

    def _teammate(self, i: int) -> int | None:
        mates = [j for j in range(self.n) if j != i and self.team_ids[j] == self.team_ids[i]]
        return mates[0] if mates else None

    def _apply_command(self, command: EngineerCommand) -> None:
        """Apply a validated command to Our Car (MVP-09)."""
        i = self.our_index
        if i is None:
            logger.warning("command %s ignored: no Our Car", command.type)
            return
        T, p = CommandType, command.params
        if command.type in (T.DEFEND, T.HOLD_POSITION, T.LET_TEAMMATE_BY):
            self._end_attack(i)  # these clear ATTACK
        ins = self.instructions[i]
        if command.type == T.SET_ENERGY_MODE:
            self._attack_mode.pop(i, None)  # the engineer's mode stays after an ATTACK
            self.set_instructions(i, replace(ins, mode=EnergyMode(p["mode"])))
        elif command.type == T.SET_OVERTAKE_PERMISSION:
            self._ot_rules.append((bool(p["allowed"]), p.get("lap"), p.get("zone_id")))
            self._update_overtake_permission()
        elif command.type == T.SET_LIFT_COAST:
            zones = p.get("zone_ids")
            self.set_instructions(
                i,
                replace(ins, lift_coast=bool(p["enabled"]),
                        lift_zones=tuple(zones) if zones else None),
            )  # fmt: skip
        elif command.type == T.BOX:
            self._box_plan[i] = (int(p["lap"]), Compound(p["compound"]))
            self._check_box(i)
        elif command.type == T.CANCEL_BOX:
            self._box_plan.pop(i, None)
            self.cancel_box(i)
        elif command.type == T.DEFEND:
            # The corner is where the defence starts; it lasts until the threat clears.
            self._defend_threat[i] = self._car_behind(i)
            self._defend_until[i] = int(self.st.lap[i]) + self.app.engineer.call_max_laps
            self.set_instructions(i, replace(ins, defend=True, keep_deploy=True, attack=False))
        elif command.type == T.ATTACK:
            if not ins.attack:
                self._attack_mode[i] = ins.mode
            self._attack_until[i] = int(self.st.lap[i]) + self.app.engineer.call_max_laps
            self._end_defence(i)
            self.set_instructions(
                i,
                replace(self.instructions[i], attack=True, follow_close=True, hold_position=False,
                        mode=EnergyMode.PUSH),
            )  # fmt: skip
        elif command.type == T.HOLD_POSITION:
            self.set_instructions(i, replace(ins, hold_position=True, attack=False))
        elif command.type == T.LET_TEAMMATE_BY:
            self.set_instructions(i, replace(ins, let_teammate_by=True, attack=False))
        elif command.type == T.PUSH_LAP:
            self._push_until[i] = int(self.st.lap[i]) + int(p["laps"])
            self.set_instructions(i, replace(ins, push_lap=True, manage_tyres=False))
        elif command.type == T.MANAGE_TYRES:
            on = bool(p["enabled"])
            self.set_instructions(
                i, replace(ins, manage_tyres=on, push_lap=ins.push_lap and not on)
            )

    def _end_attack(self, i: int) -> None:
        """End car ``i``'s ATTACK and go back to the Energy Mode it had before."""
        self._attack_until[i] = NO_LIMIT
        mode = self._attack_mode.pop(i, None)
        ins = self.instructions[i]
        if ins.attack or ins.follow_close or mode is not None:
            self.set_instructions(
                i, replace(ins, attack=False, follow_close=False, mode=mode or ins.mode)
            )

    def _end_defence(self, i: int) -> None:
        """End car ``i``'s DEFEND."""
        self._defend_until[i], self._defend_threat[i] = NO_LIMIT, -1
        ins = self.instructions[i]
        if ins.defend or ins.keep_deploy:
            self.set_instructions(i, replace(ins, defend=False, keep_deploy=False))

    def _car_behind(self, i: int) -> int:
        """Return the running car right behind car ``i`` on the road (-1: none)."""
        st = self.st
        behind = np.flatnonzero((st.ahead_idx == i) & st.running & ~st.in_pit)
        return int(behind[0]) if behind.size else -1

    def _defence_over(self, i: int) -> bool:
        """DEFEND is over once the threat has passed or is ``defend_clear_gap_s`` back."""
        st, length = self.st, self.trk.length_m
        j = int(self._defend_threat[i])
        if j < 0 or not st.running[j] or st.in_pit[j]:
            j = self._car_behind(i)
            if j < 0:
                return True
        if self._rank[j] < self._rank[i]:
            return True
        behind_m = (st.lap[i] - st.lap[j]) * length + st.s_m[i] - st.s_m[j]
        return bool(behind_m / max(float(st.v_ms[j]), 1.0) > self.app.engineer.defend_clear_gap_s)

    def _check_box(self, i: int) -> None:
        """Request a planned stop once car ``i`` is on the planned lap."""
        plan = self._box_plan.get(i)
        if plan is not None and int(self.st.lap[i]) + 1 >= plan[0] and self.box(i, plan[1]):
            del self._box_plan[i]

    def _update_overtake_permission(self) -> None:
        """Our Car's Overtake permission here and now: the latest matching rule wins."""
        i = self.our_index
        if i is None or not self._ot_rules:
            return
        lap = int(self.st.lap[i]) + 1
        self._ot_rules = [r for r in self._ot_rules if r[1] is None or r[1] >= lap]
        k = int(self.st.s_m[i] / self.trk.ds_m) % self.model.s_m.size
        here = next((z for z, m in self._ot_zone_masks.items() if m[k]), None)
        allowed = True
        for rule_allowed, rule_lap, zone in self._ot_rules:
            if (rule_lap is None or rule_lap == lap) and (zone is None or zone == here):
                allowed = rule_allowed
        if allowed != self.instructions[i].overtake_permitted:
            self.set_instructions(i, replace(self.instructions[i], overtake_permitted=allowed))

    def _command_upkeep(self) -> None:
        """Decision tick: end LET_TEAMMATE_BY and DEFEND when due; Overtake rules.

        LET_TEAMMATE_BY ends once the teammate is ahead, DEFEND once the threat has
        cleared or ``call_max_laps`` are run.
        """
        i = self.our_index
        if i is None:
            return
        ins = self.instructions[i]
        if ins.defend and (self.st.lap[i] >= self._defend_until[i] or self._defence_over(i)):
            self._end_defence(i)
            ins = self.instructions[i]
        mate = self._teammate(i)
        if ins.let_teammate_by and (mate is None or self._rank[mate] < self._rank[i]):
            self.set_instructions(i, replace(ins, let_teammate_by=False))
        self._update_overtake_permission()

    def _commands_new_lap(self, i: int) -> None:
        """Line crossing: PUSH_LAP and ATTACK run out, a planned stop comes due."""
        ins = self.instructions[i]
        if ins.push_lap and self.st.lap[i] >= self._push_until[i] > -(10**9):
            self._push_until[i] = -(10**9)
            self.set_instructions(i, replace(ins, push_lap=False))
        if self.instructions[i].attack and self.st.lap[i] >= self._attack_until[i]:
            self._end_attack(i)
        self._check_box(i)

    def _rival_strategy(self) -> None:
        """Rival Strategy AI (T-041); the Radar is brought up to date first."""
        self._mark("rival_strategy")
        self._sync_radar()
        st, book = self.st, self.rival_book
        idx = book.index
        if idx.size == 0:
            return
        racing = st.running[idx]
        mode, attack, defend, hold, box = self._rival_decisions()
        ins = self._instruction_arrays
        changed = racing & (
            (mode != ins.mode[idx]) | (attack != ins.attack[idx]) | (defend != ins.defend[idx])
            | (hold != ins.hold_position[idx])
        )  # fmt: skip
        for k in np.flatnonzero(changed):
            i = int(idx[k])
            self.set_instructions(
                i,
                replace(
                    self.instructions[i], mode=RS.MODE_ORDER[int(mode[k])],
                    attack=bool(attack[k]), defend=bool(defend[k]), hold_position=bool(hold[k]),
                ),
            )  # fmt: skip
        targets = self._rival_targets()
        for k in np.flatnonzero(racing & box):
            if self.box(int(idx[k]), self._rival_compound(int(k), targets)):
                book.stops_done[k] += 1
        if targets is not None:
            self._rivals_wet(racing, targets)

    def _rival_targets(self) -> list[Compound] | None:
        """Per Rival row, the grippiest tyre for the track now (E1); ``None`` on a dry track.

        Public information only (HR-03): the track wetness everyone sees and the
        tyres.yaml grip curves, plus the car's own tyres.
        """
        idx = self.rival_book.index
        wet = set(W.WET_COMPOUNDS)
        if self.weather.track_wetness <= 0.0 and not any(self.compounds[i] in wet for i in idx):
            return None
        best: dict[Compound, Compound] = {}
        out = []
        for k, i in enumerate(idx.tolist()):
            current = self.compounds[i]
            slick = current if current not in wet else self.rival_book.next_compound[k]
            if slick not in best:
                best[slick] = W.best_compound(self.tyres, self.weather.track_wetness, slick)
            out.append(best[slick])
        return out

    def _rival_compound(self, k: int, targets: list[Compound] | None) -> Compound:
        """Return the tyre Rival row ``k`` fits at a stop: wet ones while the track wants them."""
        if targets is not None and targets[k] in W.WET_COMPOUNDS:
            return targets[k]
        return self.rival_book.next_compound[k]

    def _rivals_wet(self, racing: npt.NDArray[np.bool_], targets: list[Compound]) -> None:
        """Wet crossover branch (T-062 weather, E1): box for the right tyre after each delay."""
        st, book = self.st, self.rival_book
        for k, i in enumerate(book.index.tolist()):
            if not racing[k] or st.in_pit[i] or self.pit.phase[i] != PitPhase.RUNNING:
                continue
            done = max(int(st.lap[i]), 0)
            if RS.wet_box_due(book, k, self.compounds[i], targets[k], done, self.laps):
                if self.box(i, targets[k]):
                    book.stops_done[k] += 1
                    book.wet_due_lap[k] = -1
                    self.rivals_wet_boxed.append((done, self.driver_ids[i], targets[k]))
                    logger.info("%s boxes for %s (wet crossover), lap %d",
                                self.driver_ids[i], targets[k], done + 1)  # fmt: skip

    def _rival_decisions(self) -> RS.Decisions:
        """``(mode, attack, defend, hold, box)`` per row of ``rival_book`` (PF-10).

        Inputs: each Rival's own Ground Truth, public positions and gaps, and
        the other cars' Radar Estimates (HR-03). Updates the plans' HARVEST state.
        """
        cfg, st, book = self.app.rival_strategy, self.st, self.rival_book
        idx = book.index
        own = st.battery_j[idx] / MJ
        # Opponents' energy: their Radar Estimates only (HR-03). The race-start prior
        # (sprint day 5) is for the pit wall; the Rival Strategy AI keeps treating a
        # car without an anchor as level with itself, as before it.
        energy, confidence = self.radar.energies(with_prior=False)
        ga, gb, ahead_e, behind_e = RS.battle_inputs(
            idx, st.s_m, st.running & ~st.in_pit, st.ahead_idx, st.gap_ahead_m, st.v_ms, own,
            energy, confidence,
        )  # fmt: skip
        return RS.decide_book(
            book, own, self.timing.lap_battery_j[idx] / MJ, st.tyre_wear[idx],
            np.maximum(st.lap[idx], 0),  # -1 behind the line at the start
            self.laps, st.in_pit[idx], ga, gb, ahead_e, behind_e, cfg,
        )  # fmt: skip

    def _decide(self) -> None:
        """AI Driver decision tick for every running car (line, Overtake, boost)."""
        self._mark("ai_driver")
        self._command_upkeep()
        st, ctl, cfg = self.st, self.ctl, self.app.ai_driver
        running = np.flatnonzero(st.running)
        if running.size == 0:
            return
        gap_behind_m = np.full(self.n, np.inf)
        if running.size > 1:
            by_s = running[np.argsort(st.s_m[running])]
            gap_behind_m[np.roll(by_s, -1)] = st.gap_ahead_m[by_s]
        k = (st.s_m / self.trk.ds_m).astype(np.int64) % self.trk.kappa.size
        v = np.maximum(st.v_ms, 1.0)
        line, overtake, boost = D.decide_all(
            st.battery_j, self.trk.accel_zone[k], st.gap_ahead_m / v, gap_behind_m / v,
            self.overtake_available, self._instruction_arrays, cfg,
        )  # fmt: skip
        racing = st.running & ~st.in_pit  # pit lane: no racing decisions
        boost &= racing
        overtake &= racing & self.ot_zone[k]
        rising = boost & ~ctl.boost_active
        ctl.boost_total_w[rising] = st.power_w[rising]  # post-Miami boost cap reference
        ctl.boost_active[:] = boost
        ctl.overtake_active[:] = overtake
        self.line[racing] = line[racing]
        ctl.mgmt_factor[:] = self._instruction_arrays.mgmt_factor

    def _weather(self) -> None:
        """Weather (T-039, PF-14), at decision ticks: rain, wetness, grip, plans."""
        self._mark("weather")
        if self.steps % self.decision_steps:
            return
        st = self.st
        leader_lap = int(st.lap.max())
        laps, self._weather_lap = max(leader_lap - self._weather_lap, 0), leader_lap
        if self._rain_lap is not None and st.running.any() and self.flag != "CHEQUERED":
            if int(st.lap[st.running].max()) + 1 >= self._rain_lap:  # the leader starts it
                self._rain_lap = None
                self.weather_model.start_rain()
        share = float(np.count_nonzero(st.running & ~st.in_pit)) / self.n
        if self.weather_model.step(self.decision_steps * self.dt, share, laps):
            logger.info("weather: %s at %.0f s", self.weather.condition, self.t)
        self._apply_grip()

    def _grip(self, i: int) -> float:
        """Car ``i``'s grip factor now (its compound on this track surface)."""
        return self.weather_model.grip(self.tyres, self.compounds[i])

    def _plan_grip(self, i: int) -> float:
        """Car ``i``'s grip rounded to ``weather.replan_grip_step`` (what its plan uses)."""
        step = self.app.weather.replan_grip_step
        return round(round(self._grip(i) / step) * step, 6)

    def _apply_grip(self) -> None:
        """Set every car's grip; re-plan cars whose rounded grip moved (PF-14).

        Nothing to do while wetness and track evolution stand still; the car
        loop runs only when some compound's rounded grip has moved.
        """
        surface = (self.weather.track_wetness, self.weather.track_evolution)
        if surface == self._grip_surface:
            return
        self._grip_surface = surface
        by_compound = {c: self.weather_model.grip(self.tyres, c) for c in set(self.compounds)}
        self.ctl.grip_factor[:] = [by_compound[c] for c in self.compounds]
        step = self.app.weather.replan_grip_step
        rounded = {c: round(round(g / step) * step, 6) for c, g in by_compound.items()}
        if rounded == self._grip_rounded:
            return
        self._grip_rounded = rounded
        for i in np.flatnonzero(self.st.running).tolist():
            if self._plan_grip(i) != self._planned_grip[i]:
                self._set_plan(i, self._reshape_car(i))

    def _kernel(self) -> None:
        self._mark("kernel")
        self._s_before[:] = self.st.s_m
        self.t = K.advance(
            self.chunk_steps, self.dt, self.t, self.plans, self.trk, self.glb, self.cars,
            self.ctl, self.st,
        )  # fmt: skip
        self.steps += self.chunk_steps

    def _overtake(self) -> list[OvertakeEvent]:
        """Overtake attempts at trigger points passed this interval (PF-11); none under SC / VSC."""
        self._mark("overtake")
        if self.track_status.status != "GREEN":
            return []
        ins = self._instruction_arrays
        # The engineer's HOLD_POSITION stops Our Car's attempts (TRD); the Rival
        # Strategy AI's "hold" means "not attacking" and leaves attempts alone.
        holding = np.zeros(self.n, dtype=np.bool_)
        if self.our_index is not None:
            holding[self.our_index] = ins.hold_position[self.our_index]
        events = self.overtake.resolve(
            self.t,
            self._s_before,
            self.cars,
            self.ctl,
            self.st,
            ins.defend,
            ins.attack,
            holding,
        )
        for event in events:
            if event.success:
                self.line[event.attacker] = D.RACING_LINE  # PF-11: line 2 -> 0
                a = event.attacker
                if a == self.our_index and self.instructions[a].attack:  # ATTACK done
                    self._end_attack(a)
        for event in events:
            self._contact(event)
        return events

    def _contact(self, event: OvertakeEvent) -> None:
        """Overtake contact (T-038, MVP-11; RNG ``events`` only, HR-04).

        A real attempt (pass chance at least ``contact_min_p_pass``; not a blue
        flag) touches with probability ``contact_p``. Severity by ``contact_shares``:
        LIGHT slows both cars to ``contact_speed_factor``; VSC / SC stops the
        attacker off / on the racing line, an incident that raises a VSC / SC.
        """
        cfg = self.app.race_events
        if event.blue_flag or event.p_pass < cfg.contact_min_p_pass or cfg.contact_p <= 0.0:
            return
        rng = self.rngs["events"]
        if rng.random() >= cfg.contact_p:
            return
        shares, u = cfg.contact_shares, rng.random()
        cumulative = np.cumsum(list(shares.values()))
        picked = (s for s, c in zip(shares, cumulative, strict=True) if u < c)
        severity: ContactSeverity = next(picked, "LIGHT")
        a, d = event.attacker, event.defender
        self.contacts.append(ContactEvent(self.t, a, d, severity))
        logger.info("contact %s / %s at %.0f m: %s", self.driver_ids[a], self.driver_ids[d],
                    event.s_m, severity)  # fmt: skip
        if severity == "LIGHT":
            self.st.v_ms[[a, d]] *= cfg.contact_speed_factor
            return
        self.retire(a, f"contact with {self.driver_ids[d]}")
        self.incident(a, on_line=severity == "SC")

    def _pit(self) -> list[PitEvent]:
        """Pit lane state machine (PF-12); fits the new tyres at the pit exit."""
        self._mark("pit")
        events = self.pit.step(self.t, self._s_before, self.st)
        for event in events:
            i = event.car
            if event.phase == PitPhase.PIT_LANE_IN and self.status[i] == "RUNNING":
                self._set_status(i, "PIT")
            elif event.phase == PitPhase.RUNNING and self.status[i] == "PIT":
                self._set_status(i, "RUNNING")
                if event.compound is not None:
                    self.compounds[i] = event.compound
                    K.set_compound(self.cars, i, self.tyres, event.compound)
                    self.ctl.grip_factor[i] = self._grip(i)
                    self.st.tyre_wear[i] = 0.0
                    self.tyre_laps[i] = 0
                    self._set_plan(i, self._reshape_car(i))
        return events

    def _events(self) -> None:
        """Race events: AI Driver mistakes, retirements (out of fuel), SC / VSC (H4)."""
        self._mark("events")
        self._mistakes()
        self._track_status_upkeep()
        st = self.st
        if st.fuel_kg.min() > 0.0:
            return
        for i in np.flatnonzero(st.running & (st.fuel_kg <= 0.0)):
            self.retire(int(i), "out of fuel")

    # ------------------------------------------------------------------ #
    # Safety Car / VSC (hackathon H4, simplified T-038)
    # ------------------------------------------------------------------ #

    def incident(self, i: int, on_line: bool) -> None:
        """Raise a Safety Car for a car stopped on the racing line, a VSC for one off it."""
        current = self.track_status.status
        where = "on the line" if on_line else "off the line"
        reason = f"{self.driver_ids[i]} stopped {where}"
        if on_line and current in ("GREEN", "VSC"):
            self.deploy("SC", reason)
        elif not on_line and current == "GREEN":
            self.deploy("VSC", reason)

    def deploy(self, kind: Literal["SC", "VSC"], reason: str) -> None:
        """Deploy a Safety Car or VSC now; the Rivals' SC / VSC pit branch runs once."""
        if self.flag == "CHEQUERED":
            return
        cfg = self.app.race_events
        if kind == "SC":
            running = self.st.running
            leader_done = int(self.st.lap[running].max()) if running.any() else 0
            self._sc_end_lap = leader_done + cfg.sc_laps  # restart when the leader completes it
            self.track_status = TrackStatus("SC", sc_laps_remaining=cfg.sc_laps)
        else:
            self.track_status = TrackStatus("VSC", vsc_end_time_s=self.t + cfg.vsc_duration_s)
        self.flag = kind
        self.track_events.append((self.t, kind, reason))
        logger.info("%s at %.1f s: %s", kind, self.t, reason)
        self._rivals_sc_pit()
        self._apply_track_status()

    def _end_track_status(self, reason: str) -> None:
        self.track_status = TrackStatus()
        if self.flag in ("SC", "VSC"):
            self.flag = "GREEN"
        self.track_events.append((self.t, "GREEN", reason))
        self._apply_track_status()

    def _track_status_upkeep(self) -> None:
        """Scripted Safety Car, VSC end, speed caps for the next interval."""
        st = self.st
        status = self.track_status
        if self._scripted_sc_lap is not None and st.running.any():
            leader_lap = int(st.lap[st.running].max()) + 1
            if leader_lap >= self._scripted_sc_lap and status.status == "GREEN":
                self._scripted_sc_lap = None
                self.deploy("SC", "scripted (demo)")
                return
        if status.status == "VSC" and status.vsc_end_time_s is not None:
            if self.t >= status.vsc_end_time_s:
                self._end_track_status("VSC ending")
                return
        if status.status != "GREEN":
            self._apply_track_status()

    def _sc_leader_line(self) -> None:
        """Count the Safety Car's laps down at the leader's line crossing; restart at 0."""
        status = self.track_status
        if status.status not in ("SC", "SC_IN_THIS_LAP"):
            return
        running = self.st.running
        leader_done = int(self.st.lap[running].max()) if running.any() else self._sc_end_lap
        left = self._sc_end_lap - leader_done
        if left == status.sc_laps_remaining:
            return  # the crossing that deployed it
        if left <= 0:
            self._end_track_status("Safety Car in, restart")
        else:
            name: TrackStatusName = "SC_IN_THIS_LAP" if left == 1 else "SC"
            self.track_status = TrackStatus(name, sc_laps_remaining=left)

    def _apply_track_status(self) -> None:
        """Speed caps: VSC = race pace / delta factor; SC = queue at SC pace, 55 m apart."""
        cfg, st, ctl = self.app.race_events, self.st, self.ctl
        status = self.track_status.status
        if status == "GREEN":
            ctl.speed_scale[:] = 1.0
            return
        if status == "VSC":
            ctl.speed_scale[:] = 1.0 / cfg.vsc_delta_factor
            return
        sc = 1.0 / cfg.sc_pace_factor
        on_track = st.running & ~st.in_pit
        # A car with a car ahead within the gap runs at SC pace; one further back
        # closes up; the queue's first car (no car ahead within half a lap) leads at SC pace.
        far = st.gap_ahead_m > cfg.sc_gap_m
        first = (st.ahead_idx < 0) | (st.gap_ahead_m > 0.5 * self.trk.length_m)
        scale = np.where(far & ~first, cfg.sc_catch_up_scale, sc)
        close = st.gap_ahead_m < 0.8 * cfg.sc_gap_m
        scale = np.where(close & ~first, 0.95 * sc, scale)
        ctl.speed_scale[:] = np.where(on_track, scale, 1.0)

    def _rivals_sc_pit(self) -> None:
        """Rivals' SC / VSC pit branch: box now if the planned stop is near, else stay out."""
        cfg, st, book = self.app.race_events, self.st, self.rival_book
        targets = self._rival_targets()
        for k, i in enumerate(book.index.tolist()):
            if not st.running[i] or st.in_pit[i] or book.stops_done[k] > 0:
                continue
            done = max(int(st.lap[i]), 0)
            if self.laps - done < cfg.rival_box_min_laps_left:
                continue
            if int(book.stop_lap[k]) - done > cfg.rival_box_window_laps:
                continue  # its planned stop is far off: stays out
            if self.box(i, self._rival_compound(k, targets)):
                book.stops_done[k] += 1
                self.sc_rivals_boxed.append(self.driver_ids[i])

    def _mistakes(self) -> None:
        """Mistakes at corners passed this interval (T-037; RNG ``mistakes`` only, HR-04).

        Each car on track that passed a corner draws once. A lock-up, off-track
        or spin keeps ``speed_factor`` of the speed (a lock-up also flat-spots
        the tyre); a crash retires the car.
        """
        st, cfg, length = self.st, self.app.mistakes, self.trk.length_m
        due = K.reached(st.lap, st.s_m, length, self._next_corner_d)
        if due.size == 0:
            return
        rng, wetness = self.rngs["mistakes"], self.weather.track_wetness
        for i in due.tolist():
            p = D.mistake_probability(
                cfg, float(self.skill_consistency[i]), float(st.tyre_wear[i]), wetness
            )
            distance = float(st.lap[i]) * length + float(st.s_m[i])
            while distance >= self._next_corner_d[i]:
                k = int(self._next_corner[i])
                self._advance_corner(i)
                if st.running[i] and not st.in_pit[i]:
                    self._mistake(i, k, D.draw_mistake(cfg, p, rng))

    def _advance_corner(self, i: int) -> None:
        """Point car ``i`` at the corner after its current next corner."""
        k = int(self._next_corner[i])
        nxt = (k + 1) % self._corner_s.size
        self._next_corner[i] = nxt
        self._next_corner_d[i] += (self._corner_s[nxt] - self._corner_s[k]) % self.trk.length_m or (
            self.trk.length_m
        )

    def _mistake(self, i: int, k: int, kind: MistakeKind | None) -> None:
        """Apply car ``i``'s mistake at corner ``k`` (none: nothing happens)."""
        if kind is None:
            return
        st, cfg = self.st, self.app.mistakes
        corner = self._corners[k].corner_id
        self.mistakes.append(MistakeEvent(self.t, i, kind, corner))
        logger.info("%s: %s at %s, t %.1f s", self.driver_ids[i], kind, corner, self.t)
        if kind == "CRASH":
            self.retire(i, f"crash at {corner}")
            on_line = bool(self.rngs["events"].random() < self.app.race_events.crash_on_line_p)
            self.incident(i, on_line)
            return
        st.v_ms[i] *= cfg.speed_factor[kind]
        if kind == "LOCK_UP":
            st.tyre_wear[i] = min(float(st.tyre_wear[i]) + cfg.lock_up_wear, 1.0)

    def retire(self, i: int, reason: str) -> None:
        """Car ``i`` stops for good: status DNF, off the road."""
        if self.status[i] in ("FINISHED", "DNF"):
            return
        self._set_status(i, "DNF")
        self.retired[i] = reason
        self.st.running[i] = False
        self.st.v_ms[i] = 0.0
        logger.info("%s retires at %.1f s: %s", self.driver_ids[i], self.t, reason)

    def _public_feed(self) -> None:
        """Public Feed emission (PF-06): every tick is one feed interval."""
        self._mark("public_feed")
        if self.feed.emit(self.t, self.st, self.ctl):
            self._radar_pending.append(self.feed.ticks[-1])

    def _sync_radar(self) -> None:
        """Feed the Radar every frame emitted since the last read, in order, in one call."""
        ticks = self._radar_pending
        if not ticks:
            return
        self.radar.push_feed(
            np.concatenate([tk.car for tk in ticks]),
            np.concatenate([np.full(tk.car.size, tk.t_s) for tk in ticks]),
            np.concatenate([tk.v_ms for tk in ticks]),
            np.concatenate([tk.throttle for tk in ticks]),
            np.concatenate([tk.brake for tk in ticks]),
            np.concatenate([tk.s_m for tk in ticks]),
            np.concatenate([tk.noise for tk in ticks], axis=1),
            self.model.heading_rad,
        )  # fmt: skip
        self._radar_pending = []

    def radar_estimate(self, i: int) -> RadarEstimate:
        """Car ``i``'s Radar Estimate from the Public Feed (what Rivals and the engineer see).

        Every feed frame reaches the Radar in order; frames are handed over when an
        estimate is read (decision ticks, the UI), not one call per frame (NFR-02).
        """
        self._sync_radar()
        return self.radar.estimate(i, self.driver_ids[i])

    # ------------------------------------------------------------------ #
    # Timing
    # ------------------------------------------------------------------ #

    def _record_pass(self, i: int, lap: int, loop: int, t: float) -> None:
        """Gap and interval for car ``i`` passing ``loop`` (or the line) on ``lap``."""
        tm = self.timing
        passes = tm.crossings.setdefault((lap, loop), {})
        passes[i] = t
        tm.gap_s[i] = t - min(passes.values())
        rank = int(self._rank[i])
        ahead = int(self._classification[rank - 1]) if rank > 0 else -1
        tm.interval_s[i] = t - passes[ahead] if ahead in passes else tm.gap_s[i]

    def _timing(self) -> None:
        """Laps, sectors, gaps, Overtake detection, finish (stage 8)."""
        self._mark("timing")
        st, tm = self.st, self.timing
        moved = np.flatnonzero((st.next_loop != self._prev_next) | (st.lap != self._prev_lap))
        if moved.size == 0:  # nobody passed a loop or the line
            self._classify()
            return
        events: list[tuple[float, int, int]] = []  # (time, car, loop or LINE)
        n_loops = self.trk.loops_m.size
        for car in moved.tolist():
            old, new = int(self._prev_next[car]), int(st.next_loop[car])
            if st.lap[car] != self._prev_lap[car]:  # passed the line: rest of the old lap, then on
                passed = [*range(old, n_loops), *range(new)]
                events.append((float(st.line_time_s[car]), car, LINE))
            else:  # a set-back (new < old) passes nothing until it drives on
                passed = list(range(old, new))
            events.extend((float(st.loop_time_s[car, j]), car, j) for j in passed)
        self._prev_next[:] = st.next_loop
        self._prev_lap[:] = st.lap
        for t, i, j in sorted(events):
            if j == LINE:
                self._line_crossing(i, t)
                continue
            lap = int(st.loop_lap[i, j])
            self._record_pass(i, lap, j, t)
            if j in self.sector_loops and lap >= 0:
                k = self.sector_loops.index(j)
                tm.sectors[i, k] = t - tm.sector_start_t[i]
                tm.sector_start_t[i] = t
            if j in self.detection_loops:
                last = tm.last_pass_t.get(j)
                self.overtake_available[i] = last is not None and t - last <= self.activation_gap_s
                tm.last_pass_t[j] = t
        self._classify()
        if any(j == LINE for _, _, j in events):  # forget passes the whole field is past
            racing = np.array([s in ("RUNNING", "PIT") for s in self.status])
            oldest = int(st.lap[racing].min()) if racing.any() else self.laps
            for key in [k for k in tm.crossings if k[0] < oldest - 1]:
                del tm.crossings[key]

    def _line_crossing(self, i: int, t: float) -> None:
        st, tm = self.st, self.timing
        lap = int(st.lap[i])
        self._record_pass(i, lap, LINE, t)
        if lap == 0:  # the start: lap 1 is timed from t = 0
            tm.line_t[i] = 0.0
            tm.sector_start_t[i] = 0.0
            return
        lap_s = t - tm.line_t[i]
        tm.sectors[i, 2] = t - tm.sector_start_t[i]
        tm.last_lap_s[i] = lap_s
        tm.lap_times[i].append(lap_s)
        tm.line_t[i] = t
        tm.sector_start_t[i] = t
        self.tyre_laps[i] += 1
        if int(self._rank[i]) == 0 and self.flag != "CHEQUERED":
            self._sc_leader_line()
        if self.auto_snapshot and int(self._rank[i]) == 0 and self.flag != "CHEQUERED":
            self._leader_lap = True  # snapshot at the end of this tick (PF-04)
        if self.flag != "CHEQUERED" and lap >= self.laps:
            self.flag = "CHEQUERED"
        if self.flag == "CHEQUERED":
            self._set_status(i, "FINISHED")
            tm.finish_t[i] = t
            st.running[i] = False
            self.finish_order.append(i)
            return
        self._new_lap_energy(i)
        self._commands_new_lap(i)

    def _progress_m(self) -> FloatArray:
        """Race distance per car; a finished car stays at its finishing line crossing."""
        st = self.st
        length = self.trk.length_m
        done, dnf = self._status_masks()
        progress = np.where(done, st.lap * length, st.lap * length + st.s_m)
        return np.where(dnf, progress - DNF_OFFSET_M, progress)  # retired cars last, by distance

    def _status_masks(self) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
        """``(finished, retired)`` masks, kept in step with ``status``."""
        return self._finished, self._retired

    def _set_status(self, i: int, status: CarStatus) -> None:
        self.status[i] = status
        self._finished[i] = status == "FINISHED"
        self._retired[i] = status == "DNF"

    def _classify(self) -> None:
        """Race order: finished cars by laps then finish time, then running by distance."""
        st = self.st
        self._classification = K.race_order(
            st.lap, st.s_m, self.trk.length_m, self._finished, self._retired,
            self.timing.finish_t, DNF_OFFSET_M,
        )  # fmt: skip
        self._rank[self._classification] = np.arange(self.n)

    # ------------------------------------------------------------------ #
    # Loop
    # ------------------------------------------------------------------ #

    @property
    def finished(self) -> bool:
        """Every car has taken the flag (or retired)."""
        if all(s == "DNF" for s in self.status):
            return True
        return self.flag == "CHEQUERED" and all(s in ("FINISHED", "DNF") for s in self.status)

    def tick(self) -> None:
        """One feed interval of the race, PF-04 stages in order."""
        decision_tick = self.steps % self.decision_steps == 0
        self._apply_commands()
        if decision_tick:
            self._rival_strategy()
            self._decide()
        self._weather()
        self._kernel()
        self._overtake()
        self._pit()
        self._events()
        self._timing()
        self._public_feed()
        if self._leader_lap:
            self._leader_lap = False
            self.auto_snapshots.append(self.snapshot())

    def run(self, max_t_s: float | None = None) -> RaceResult:
        """Run to the end of the race (or ``max_t_s`` sim seconds)."""
        limit = self.max_t_s if max_t_s is None else min(max_t_s, self.max_t_s)
        while not self.finished and self.t < limit:
            self.tick()
        if not self.finished and max_t_s is None:
            logger.warning("race stopped at the time limit %.0f s", self.t)
        return self.result()

    # ------------------------------------------------------------------ #
    # Snapshots (F09, T-040)
    # ------------------------------------------------------------------ #

    #: Attributes shared by reference between an engine and its snapshots:
    #: config, track and compiled track arrays never change in a race.
    _SHARED = (
        "setup", "app", "rules", "grid", "perf", "tyres", "track", "model", "trk", "glb",
        "ot_zone", "sector_loops", "detection_loops", "driver_ids", "team_ids", "laps", "n",
        "dt", "chunk_steps", "decision_steps", "max_t_s", "harvest_limit_mj",
        "activation_gap_s",
    )  # fmt: skip
    #: Not part of the race state.
    _EXCLUDED = ("command_handler", "trace", "auto_snapshots", "plans")

    def _memo(self) -> dict[int, Any]:
        """``deepcopy`` memo that shares immutable records instead of copying them.

        Driver plans, feed ticks and overtake / pit events never change once made;
        only the containers holding them are copied.
        """
        memo: dict[int, Any] = {}
        for item in [
            *self.car_plans, *self._plan_cache.values(), *self.feed.ticks,
            *self.overtake.events, *self.pit.events, *self.mistakes,
        ]:  # fmt: skip
            memo[id(item)] = item
        return memo

    def snapshot(self) -> Snapshot:
        """Snapshot the race now (TRD ``save``)."""
        state = {k: v for k, v in self.__dict__.items() if k not in self._SHARED + self._EXCLUDED}
        return Snapshot(
            t=self.t,
            race_state=self.race_state(),
            rng_states=rng_states(self.rngs),
            command_log=[*self.applied_commands, *self.pending_commands],
            engine_state=copy.deepcopy(state, self._memo()),
            shared={k: self.__dict__[k] for k in self._SHARED},
        )

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> RaceEngine:
        """Build an engine that continues from ``snapshot`` (TRD ``restore``)."""
        engine = cls.__new__(cls)
        engine.__dict__.update(snapshot.shared)
        state = snapshot.engine_state
        memo: dict[int, Any] = {}
        for item in [
            *state["car_plans"], *state["_plan_cache"].values(), *state["feed"].ticks,
            *state["overtake"].events, *state["pit"].events, *state["mistakes"],
        ]:  # fmt: skip
            memo[id(item)] = item
        engine.__dict__.update(copy.deepcopy(state, memo))
        engine.plans = D.kernel_plans(engine.car_plans)
        engine.command_handler = None
        engine.trace = None
        engine.auto_snapshots = []
        return engine

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #

    def result(self) -> RaceResult:
        """Classification and lap times so far."""
        tm = self.timing
        return RaceResult(
            finished=self.finished,
            t_s=self.t,
            classification=[self.driver_ids[i] for i in self._classification],
            laps_completed={d: max(int(self.st.lap[i]), 0) for i, d in enumerate(self.driver_ids)},
            finish_time_s={
                d: (float(tm.finish_t[i]) if math.isfinite(tm.finish_t[i]) else None)
                for i, d in enumerate(self.driver_ids)
            },
            lap_times_s={d: list(tm.lap_times[i]) for i, d in enumerate(self.driver_ids)},
            retired={self.driver_ids[i]: reason for i, reason in self.retired.items()},
        )

    def timing_state(self) -> TimingState:
        """Public timing (TRD TimingState)."""
        tm = self.timing
        order = [int(i) for i in self._classification]
        leader = order[0]
        length = self.trk.length_m
        progress = self._progress_m()
        ids = self.driver_ids

        def maybe(x: float) -> float | None:
            return None if math.isnan(x) else float(x)

        return TimingState(
            order=[ids[i] for i in order],
            gap_to_leader_s={ids[i]: 0.0 if i == leader else float(tm.gap_s[i]) for i in order},
            interval_s={ids[i]: 0.0 if i == leader else float(tm.interval_s[i]) for i in order},
            laps_down={
                ids[i]: max(int((progress[leader] - progress[i]) // length), 0)
                if self.status[i] != "DNF"
                else 0
                for i in order
            },
            last_lap_s={ids[i]: maybe(tm.last_lap_s[i]) for i in order},
            sector_s={ids[i]: [maybe(x) for x in tm.sectors[i]] for i in order},
            compound={ids[i]: self.compounds[i] for i in order},
            tyre_age_laps={ids[i]: int(self.tyre_laps[i]) for i in order},
            pit_stops={ids[i]: self.pit_stops(i) for i in order},
            penalties_s={ids[i]: 0.0 for i in order},
        )

    def pit_stops(self, i: int) -> int:
        """Completed pit stops of car ``i`` (public timing)."""
        return int(self.prior_pit_stops[i]) + sum(
            1 for e in self.pit.events if e.car == i and e.phase == PitPhase.RUNNING and e.compound
        )

    def car_state(self, i: int) -> CarState:
        """Ground Truth ``CarState`` of car ``i`` (Our Car in the EngineerView)."""
        st, ctl = self.st, self.ctl
        tyre = tyre_params(self.tyres, self.compounds[i])
        return CarState(
            driver_id=self.driver_ids[i],
            team_id=self.team_ids[i],
            s_m=float(st.s_m[i]),
            lap=int(st.lap[i]),
            line=int(self.line[i]),
            v_ms=float(st.v_ms[i]),
            throttle=float(ctl.throttle[i]),
            brake=float(ctl.brake[i]),
            gear=0,  # gears are not modelled (T-050 may derive one for the feed)
            aero_mode="STRAIGHT_MODE" if st.aero_mode[i] == K.STRAIGHT_MODE else "CORNER_MODE",
            battery_mj=float(st.battery_j[i]) / MJ,
            harvest_mj_lap=float(st.harvest_lap_j[i]) / MJ,
            deploy_mj_lap=float(st.deploy_lap_j[i]) / MJ,
            overtake_available=bool(self.overtake_available[i]),
            overtake_active=bool(ctl.overtake_active[i]),
            energy_mode=self.instructions[i].mode.value,
            compound=self.compounds[i],
            tyre_age_laps=int(self.tyre_laps[i]),
            tyre_wear=float(st.tyre_wear[i]),
            tyre_temp_c=tyre_temp_c(tyre),
            fuel_kg=float(st.fuel_kg[i]),
            damage=0.0,
            status=self.status[i],
            penalties_s=0.0,
            track_limit_warnings=0,
        )

    def race_state(self) -> RaceState:
        """Ground Truth ``RaceState`` mirrored from the kernel arrays."""
        cars = [self.car_state(i) for i in range(self.n)]
        return RaceState(
            t_s=self.t,
            seed=self.setup.seed,
            rule_set_id=self.rules.rule_set_id,
            track_id=self.track.track_id,
            grid_id=self.grid.grid_id,
            cars=cars,
            flag=self.flag,
            weather=replace(self.weather),
            timing=self.timing_state(),
            pending_commands=list(self.pending_commands),
            track_status=self.track_status,
        )


# --------------------------------------------------------------------------- #
# Headless CLI (T-036, NFR-02)
# --------------------------------------------------------------------------- #

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_NOT_FINISHED = 3


@dataclass(frozen=True)
class RunTiming:
    """Wall-clock cost of one headless race (NFR-02 reports these)."""

    setup_s: float
    race_s: float

    @property
    def total_s(self) -> float:
        """Setup plus race."""
        return self.setup_s + self.race_s


def run_headless(
    setup: RaceSetup, config_dir: Path = DEFAULT_CONFIG_DIR
) -> tuple[RaceResult, RunTiming]:
    """Build and run one race without UI; return the result and the wall-clock timing."""
    start = time.perf_counter()
    engine = RaceEngine(setup, config_dir)
    built = time.perf_counter()
    result = engine.run()
    return result, RunTiming(built - start, time.perf_counter() - built)


def format_result(result: RaceResult) -> list[str]:
    """Classification lines: position, driver, laps, time or gap, retirements."""
    lines = []
    winner = result.classification[0]
    win_t = result.finish_time_s[winner]
    for pos, driver in enumerate(result.classification, start=1):
        finish = result.finish_time_s[driver]
        laps = result.laps_completed[driver]
        if driver in result.retired:
            text = f"DNF ({result.retired[driver]})"
        elif finish is None or win_t is None:
            text = "running"
        elif driver == winner:
            text = f"{finish:9.3f} s"
        elif laps < result.laps_completed[winner]:
            down = result.laps_completed[winner] - laps
            text = f"+{down} lap{'s' if down > 1 else ''}"
        else:
            text = f"+{finish - win_t:8.3f} s"
        lines.append(f"{pos:2d}  {driver:4s} {laps:3d} laps  {text}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run one race headless and print the classification and timing (NFR-02)."""
    parser = argparse.ArgumentParser(description="Run one race without UI (NFR-02).")
    parser.add_argument(
        "--headless", action="store_true", help="required: no UI (main.py is the app)"
    )
    parser.add_argument("--track", default="suzuka")
    parser.add_argument("--rules", default="2026_post_miami", help="Rule Set id")
    parser.add_argument("--grid", default="real_2026")
    parser.add_argument("--seed", type=int, default=None, help="default: sim.default_seed")
    parser.add_argument("--laps", type=int, default=None, help="default: the track's race_laps")
    parser.add_argument("--fuel-kg", type=float, default=None, help="default: track fuel_start_kg")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not args.headless:
        parser.error("only --headless runs are supported here; the desktop app is main.py")
    try:
        seed = args.seed if args.seed is not None else load_app(args.config_dir).sim.default_seed
        setup = RaceSetup(
            track_id=args.track, rule_set_id=args.rules, grid_id=args.grid, seed=seed,
            laps=args.laps, fuel_kg=args.fuel_kg,
        )  # fmt: skip
        result, timing = run_headless(setup, args.config_dir)
    except (ConfigError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return EXIT_INVALID
    for line in format_result(result):
        print(line)
    print(
        f"race {'finished' if result.finished else 'NOT finished'} at sim t = {result.t_s:.1f} s; "
        f"wall clock: setup {timing.setup_s:.2f} s + race {timing.race_s:.2f} s "
        f"= {timing.total_s:.2f} s (NFR-02 budget 10 s)"
    )
    return EXIT_OK if result.finished else EXIT_NOT_FINISHED


if __name__ == "__main__":
    sys.exit(main())
