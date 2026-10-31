"""F05 data contracts: RaceState and CarState, plus the parallel-array mirror.

``CarState`` / ``RaceState`` follow docs/spec/TRD.md DATA CONTRACTS field for field.
The Numba step kernel (T-030) cannot take Python objects, so the cars are
mirrored into :class:`CarArrays`: one contiguous NumPy array per field,
categorical fields as small integer codes, ids as tuples (not used by the
kernel). The round trip ``CarState`` list -> ``CarArrays`` -> ``CarState`` list is
lossless.

``WeatherState`` and ``TimingState`` are named but not defined by the TRD. The
minimal versions here follow TRD WEATHER and the UI_DESIGN timing tower; their
owning tasks (T-039 weather, T-033 timing) may extend them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields
from typing import Any, Literal, get_args

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.models import Compound
from pitwall_sim.engineer.commands import EngineerCommand

type AeroMode = Literal["STRAIGHT_MODE", "CORNER_MODE"]
type EnergyModeName = Literal["PUSH", "BALANCED", "HARVEST"]
type CarStatus = Literal["RUNNING", "PIT", "DNF", "FINISHED"]
type Flag = Literal["GREEN", "YELLOW", "VSC", "SC", "RED", "CHEQUERED"]
type WeatherCondition = Literal["DRY", "DAMP", "WET", "HEAVY_WET"]
type TrackStatusName = Literal["GREEN", "VSC", "SC", "SC_IN_THIS_LAP"]

#: Code tables for categorical fields: the array holds the index into the tuple.
AERO_MODES: tuple[str, ...] = get_args(AeroMode.__value__)
ENERGY_MODES: tuple[str, ...] = get_args(EnergyModeName.__value__)
COMPOUNDS: tuple[Compound, ...] = tuple(Compound)
STATUSES: tuple[str, ...] = get_args(CarStatus.__value__)


@dataclass
class CarState:
    """Ground Truth for one car (TRD DATA CONTRACTS)."""

    driver_id: str
    team_id: str
    s_m: float
    lap: int
    line: int
    """0 racing line, 1 defending/inside, 2 overtaking/outside."""
    v_ms: float
    throttle: float
    brake: float
    gear: int
    aero_mode: AeroMode
    battery_mj: float
    harvest_mj_lap: float
    deploy_mj_lap: float
    overtake_available: bool
    overtake_active: bool
    energy_mode: EnergyModeName
    compound: Compound
    tyre_age_laps: int
    tyre_wear: float
    tyre_temp_c: float
    fuel_kg: float
    damage: float
    status: CarStatus
    penalties_s: float
    track_limit_warnings: int


@dataclass
class WeatherState:
    """Track weather (TRD WEATHER). Minimal T-020 version; T-039 owns it."""

    condition: WeatherCondition = "DRY"
    track_wetness: float = 0.0
    """0 dry .. 1 fully wet."""
    track_evolution: float = 0.0
    """Grip gained from rubber laid down, as a fraction (0 = green track)."""


@dataclass(frozen=True)
class TrackStatus:
    """Safety Car / VSC state (hackathon H4, T-038). Public: everyone sees it."""

    status: TrackStatusName = "GREEN"
    """``SC_IN_THIS_LAP``: the Safety Car comes in at the end of this lap."""
    sc_laps_remaining: int | None = None
    """Safety Car: laps until it comes in (None outside an SC)."""
    vsc_end_time_s: float | None = None
    """VSC: sim time it ends (None outside a VSC)."""


@dataclass
class TimingState:
    """Public timing (UI_DESIGN timing tower). Minimal T-020 version; T-033 owns it."""

    order: list[str] = field(default_factory=list)
    """driver_ids, leader first."""
    gap_to_leader_s: dict[str, float] = field(default_factory=dict)
    interval_s: dict[str, float] = field(default_factory=dict)
    laps_down: dict[str, int] = field(default_factory=dict)
    last_lap_s: dict[str, float | None] = field(default_factory=dict)
    sector_s: dict[str, list[float | None]] = field(default_factory=dict)
    compound: dict[str, Compound] = field(default_factory=dict)
    """Public timing (TRD PUBLIC FEED, T-050): the tyre each car runs."""
    tyre_age_laps: dict[str, int] = field(default_factory=dict)
    pit_stops: dict[str, int] = field(default_factory=dict)
    penalties_s: dict[str, float] = field(default_factory=dict)


@dataclass
class RaceState:
    """Whole-race Ground Truth (TRD DATA CONTRACTS)."""

    t_s: float
    seed: int
    rule_set_id: str
    track_id: str
    grid_id: str
    cars: list[CarState]
    """The Numba kernel uses :class:`CarArrays` mirrored from this list."""
    flag: Flag
    weather: WeatherState
    timing: TimingState
    pending_commands: list[EngineerCommand]
    track_status: TrackStatus = field(default_factory=TrackStatus)

    def hash(self) -> str:
        """SHA-256 of all state arrays, time, flag and timing (F09 determinism check)."""
        digest = hashlib.sha256()
        arrays = to_arrays(self.cars)
        for f in fields(arrays):
            value = getattr(arrays, f.name)
            if isinstance(value, np.ndarray):
                digest.update(f.name.encode())
                digest.update(np.ascontiguousarray(value).tobytes())
            else:
                digest.update(repr(value).encode())
        meta = (self.t_s, self.seed, self.rule_set_id, self.track_id, self.grid_id, self.flag)
        digest.update(repr(meta).encode())
        digest.update(repr(self.weather).encode())
        digest.update(repr(self.timing).encode())
        digest.update(repr(self.track_status).encode())
        return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Parallel-array mirror for the Numba kernel
# --------------------------------------------------------------------------- #

#: Array dtype per numeric or boolean CarState field.
_NUMERIC_DTYPES: dict[str, type[np.generic]] = {
    "s_m": np.float64,
    "lap": np.int64,
    "line": np.int64,
    "v_ms": np.float64,
    "throttle": np.float64,
    "brake": np.float64,
    "gear": np.int64,
    "battery_mj": np.float64,
    "harvest_mj_lap": np.float64,
    "deploy_mj_lap": np.float64,
    "overtake_available": np.bool_,
    "overtake_active": np.bool_,
    "tyre_age_laps": np.int64,
    "tyre_wear": np.float64,
    "tyre_temp_c": np.float64,
    "fuel_kg": np.float64,
    "damage": np.float64,
    "penalties_s": np.float64,
    "track_limit_warnings": np.int64,
}

#: Categorical CarState fields -> code table; stored as int8 indices.
_CODED: dict[str, tuple[Any, ...]] = {
    "aero_mode": AERO_MODES,
    "energy_mode": ENERGY_MODES,
    "compound": COMPOUNDS,
    "status": STATUSES,
}

_IDS = ("driver_id", "team_id")


@dataclass
class CarArrays:
    """Struct-of-arrays mirror of ``list[CarState]``; index ``i`` is car ``i``.

    Numeric fields keep their ``CarState`` names. Categorical fields are int8
    codes into :data:`AERO_MODES`, :data:`ENERGY_MODES`, :data:`COMPOUNDS` and
    :data:`STATUSES`.
    """

    driver_id: tuple[str, ...]
    team_id: tuple[str, ...]
    s_m: npt.NDArray[np.float64]
    lap: npt.NDArray[np.int64]
    line: npt.NDArray[np.int64]
    v_ms: npt.NDArray[np.float64]
    throttle: npt.NDArray[np.float64]
    brake: npt.NDArray[np.float64]
    gear: npt.NDArray[np.int64]
    aero_mode: npt.NDArray[np.int8]
    battery_mj: npt.NDArray[np.float64]
    harvest_mj_lap: npt.NDArray[np.float64]
    deploy_mj_lap: npt.NDArray[np.float64]
    overtake_available: npt.NDArray[np.bool_]
    overtake_active: npt.NDArray[np.bool_]
    energy_mode: npt.NDArray[np.int8]
    compound: npt.NDArray[np.int8]
    tyre_age_laps: npt.NDArray[np.int64]
    tyre_wear: npt.NDArray[np.float64]
    tyre_temp_c: npt.NDArray[np.float64]
    fuel_kg: npt.NDArray[np.float64]
    damage: npt.NDArray[np.float64]
    status: npt.NDArray[np.int8]
    penalties_s: npt.NDArray[np.float64]
    track_limit_warnings: npt.NDArray[np.int64]

    @property
    def n_cars(self) -> int:
        """Number of cars mirrored."""
        return len(self.driver_id)


def to_arrays(cars: list[CarState]) -> CarArrays:
    """Mirror cars into fresh contiguous arrays (no views into the dataclasses)."""
    values: dict[str, Any] = {name: tuple(getattr(c, name) for c in cars) for name in _IDS}
    for name, dtype in _NUMERIC_DTYPES.items():
        values[name] = np.array([getattr(c, name) for c in cars], dtype=dtype)
    for name, table in _CODED.items():
        values[name] = np.array([table.index(getattr(c, name)) for c in cars], dtype=np.int8)
    return CarArrays(**values)


def from_arrays(arrays: CarArrays) -> list[CarState]:
    """Rebuild ``CarState`` objects with plain Python scalars from the mirror."""
    cars = []
    for i in range(arrays.n_cars):
        values: dict[str, Any] = {name: getattr(arrays, name)[i] for name in _IDS}
        for name in _NUMERIC_DTYPES:
            values[name] = getattr(arrays, name)[i].item()
        for name, table in _CODED.items():
            values[name] = table[int(getattr(arrays, name)[i])]
        cars.append(CarState(**values))
    return cars


def _check_mirror_covers_car_state() -> None:
    """Fail at import if CarState gains a field the mirror does not handle."""
    car_fields = {f.name for f in fields(CarState)}
    mirrored = set(_IDS) | set(_NUMERIC_DTYPES) | set(_CODED)
    array_fields = {f.name for f in fields(CarArrays)}
    if car_fields != mirrored or car_fields != array_fields:
        raise TypeError(
            f"CarState / CarArrays mismatch: {sorted(car_fields ^ mirrored)} "
            f"{sorted(car_fields ^ array_fields)}"
        )


_check_mirror_covers_car_state()


# --------------------------------------------------------------------------- #
# A race picked up mid-way (hackathon E3, light PF-18)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StartCar:
    """One car at the moment a race is picked up (``RaceSetup.start``)."""

    driver_id: str
    laps_done: int
    """Completed laps at the moment (the leader: the lap about to start - 1)."""
    lap_fraction: float
    """Share of the current lap already driven, 0 .. 1 (track position = share x length)."""
    lap_elapsed_s: float
    """Time since the car's last line crossing (its current lap's timing starts there)."""
    gap_s: float
    """Gap to the leader (public timing until the first loop updates it)."""
    interval_s: float
    compound: Compound
    tyre_age_laps: int
    tyre_wear: float
    """Hidden: real data has no wear; the caller sets a documented default."""
    pit_stops: int
    retired: bool = False


@dataclass(frozen=True)
class StartState:
    """Every car's place, tyres and stops at ``t = 0`` of a race started mid-way.

    ``cars`` lists the cars in running order (retired cars last). Hidden values real
    timing cannot give (battery, tyre wear, fuel) come from the caller's defaults.
    """

    cars: tuple[StartCar, ...]
    battery_fraction: float
    """Every car's battery as a share of its usable maximum."""
    min_spacing_m: float
    """Cars closer than this on the road are pushed back to it (no overlapping cars)."""
