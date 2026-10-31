"""P1 load: the public inputs of the bridge contract and the package's config.yaml.

Reads only what ``docs/spec/SIMPLY_CLIPPING_BRIDGE.md`` allows (SC-R02): the
export's ``feed/`` files, the track's public layout JSON, and the rows of ``our``
in ``own_file`` (a team knows its own exact battery, never another car's).

Per car the merged stream (time, distance, speed, throttle, brake, gear, x, y)
becomes :class:`CarInput`: track progress comes from the integrated distance,
pinned to ``(lap - 1) * length`` at each public lap start (``laps.parquet``
``LapStartTime``), so it does not drift over a race. Gaps longer than
``signal.max_gap_s`` split the stream into segments (:func:`segment_ids`); the
physics never interpolates across them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import yaml

CONFIG_FILE = Path(__file__).with_name("config.yaml")
FEED_FILES = ("cars.parquet", "laps.parquet", "gaps.parquet")
CARS_COLUMNS = ("driver", "time", "distance", "speed", "throttle", "brake", "gear", "x", "y")
#: Our own exact channels; nothing else is read from ``own_file``.
OWN_COLUMNS = ("driver", "time_s", "lap", "lap_distance_m", "speed_kmh", "throttle", "brake",
               "battery_mj")  # fmt: skip

Config = dict[str, Any]
Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Feed:
    """One race's public feed (BRIDGE section 1)."""

    cars: pd.DataFrame
    """Merged per-car stream: driver, time (s), distance (m), speed (km/h), throttle, brake, ..."""
    laps: pd.DataFrame
    """FastF1-style lap table."""
    gaps: pd.DataFrame
    """Per car per lap at the line: GapToLeader, IntervalToPositionAhead (s)."""


@dataclass(frozen=True)
class CarInput:
    """One car's public stream, time ordered, as the physics reads it."""

    driver: str
    team: str
    t_s: Array
    progress_m: Array
    """Distance along the race: ``(lap - 1) * length + lap distance``."""
    speed_kmh: Array
    throttle_pct: Array
    brake: npt.NDArray[np.bool_]


@dataclass(frozen=True)
class Zone:
    """A public track zone; ``s_end_m < s_start_m`` crosses the line."""

    zone_id: str
    s_start_m: float
    s_end_m: float
    tags: tuple[str, ...]

    def length_m(self, lap_m: float) -> float:
        """Zone length along the lap."""
        return (self.s_end_m - self.s_start_m) % lap_m

    def contains(self, s_m: Array, lap_m: float) -> npt.NDArray[np.bool_]:
        """Whether each lap distance lies in the zone."""
        return np.asarray((s_m - self.s_start_m) % lap_m < self.length_m(lap_m))


@dataclass(frozen=True)
class Track:
    """The public layout the estimator uses: lap length, zones, corners."""

    track_id: str
    length_m: float
    zones: tuple[Zone, ...]
    corners: tuple[tuple[str, float], ...]

    @classmethod
    def from_layout(cls, layout: dict[str, Any]) -> Track:
        """Build from the layout JSON (or the same fields of a live track object)."""
        zones = tuple(
            Zone(str(z["zone_id"]), float(z["s_start_m"]), float(z["s_end_m"]),
                 tuple(str(t) for t in z.get("tags", ())))
            for z in layout.get("zones", ())
        )  # fmt: skip
        corners = tuple((str(c["corner_id"]), float(c["s_m"])) for c in layout.get("corners", ()))
        return cls(str(layout.get("track_id", "")), float(layout["length_m"]), zones, corners)

    def tagged(self, tag: str) -> tuple[Zone, ...]:
        """Zones carrying ``tag`` (``straight_mode_allowed``, ``acceleration_zone``)."""
        return tuple(z for z in self.zones if tag in z.tags)

    def zone_index(self, s_m: Array, tag: str) -> npt.NDArray[np.int64]:
        """Index of the ``tag`` zone each lap distance lies in, -1 for none."""
        out = np.full(np.shape(s_m), -1, dtype=np.int64)
        for k, zone in enumerate(self.tagged(tag)):
            out[zone.contains(s_m, self.length_m)] = k
        return out

    def next_corner(self, s_m: float) -> str | None:
        """Return the first corner at or after ``s_m`` (wrapping at the line)."""
        if not self.corners:
            return None
        ahead = [((s - s_m) % self.length_m, cid) for cid, s in self.corners]
        return min(ahead)[1]


def load_config(path: Path = CONFIG_FILE) -> Config:
    """Return the constants (SC-R04)."""
    cfg: Config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return cfg


def const(cfg: Config, key: str) -> Any:
    """``const(cfg, "alerts.attack_gap_s")``; a missing key raises KeyError naming it."""
    node: Any = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"simply_clipping config has no {key!r} (simply_clipping/config.yaml)")
        node = node[part]
    return node


def load_feed(feed_dir: Path) -> Feed:
    """Read cars, laps and gaps from an export's ``feed/`` folder."""
    cars, laps, gaps = (pd.read_parquet(feed_dir / name) for name in FEED_FILES)
    missing = [c for c in CARS_COLUMNS if c not in cars.columns]
    if missing:
        raise ValueError(f"{feed_dir / 'cars.parquet'} lacks columns {missing}")
    return Feed(cars=cars, laps=laps, gaps=gaps)


def load_layout(layout_file: Path) -> dict[str, Any]:
    """Return the track's public layout: length_m, centreline, zones, corners."""
    layout: dict[str, Any] = json.loads(layout_file.read_text(encoding="utf-8"))
    return layout


def load_own(own_file: Path, our: str) -> pd.DataFrame:
    """Our own exact data: the rows of ``our`` only, filtered while reading (SC-R02)."""
    return pd.read_parquet(own_file, columns=list(OWN_COLUMNS), filters=[("driver", "==", our)])


def segment_ids(t_s: Array, max_gap_s: float) -> npt.NDArray[np.int64]:
    """Segment number per sample: a new segment after every gap longer than ``max_gap_s``."""
    if t_s.size == 0:
        return np.zeros(0, dtype=np.int64)
    return np.concatenate(([0], np.cumsum(np.diff(t_s) > max_gap_s))).astype(np.int64)


def progress(
    t_s: Array, distance_m: Array, lap_start_s: Array, lap_number: Array, lap_m: float
) -> Array:
    """Race progress: integrated distance pinned to ``(lap - 1) * lap_m`` at each lap start.

    Between two lap starts the distance is scaled to exactly one lap; after the
    last known lap start it runs on at the integrated rate.
    """
    if lap_start_s.size == 0:
        return np.asarray(distance_m - distance_m[0], dtype=np.float64)
    order = np.argsort(lap_start_s)
    d_at = np.interp(lap_start_s[order], t_s, distance_m)
    p_at = (lap_number[order] - 1.0) * lap_m
    keep = np.concatenate(([True], np.diff(d_at) > 0.0))  # a lap start must move the car on
    d_at, p_at = d_at[keep], p_at[keep]
    out = np.interp(distance_m, d_at, p_at)
    after = distance_m > d_at[-1]
    out[after] = p_at[-1] + (distance_m[after] - d_at[-1])
    before = distance_m < d_at[0]
    out[before] = p_at[0] - (d_at[0] - distance_m[before])
    return np.asarray(out, dtype=np.float64)


def car_inputs(feed: Feed, lap_m: float) -> dict[str, CarInput]:
    """Every car's stream, with race progress from the public lap starts."""
    laps = feed.laps
    out: dict[str, CarInput] = {}
    for driver, rows in feed.cars.groupby("driver", sort=True):
        rows = rows.sort_values("time")
        t = rows["time"].to_numpy(dtype=np.float64)
        mine = laps[laps["Driver"] == driver] if "Driver" in laps else laps.iloc[0:0]
        if "LapStartTime" in mine and "LapNumber" in mine:
            starts = mine["LapStartTime"]
            start_s = (starts.dt.total_seconds() if hasattr(starts, "dt") else starts).to_numpy(
                dtype=np.float64
            )
            number = mine["LapNumber"].to_numpy(dtype=np.float64)
        else:  # no public lap starts: progress from the integrated distance alone
            start_s = number = np.zeros(0)
        ok = np.isfinite(start_s) & np.isfinite(number)
        team = str(mine["Team"].iloc[0]) if "Team" in mine and len(mine) else ""
        out[str(driver)] = CarInput(
            driver=str(driver),
            team=team,
            t_s=t,
            progress_m=progress(
                t, rows["distance"].to_numpy(dtype=np.float64), start_s[ok], number[ok], lap_m
            ),  # fmt: skip
            speed_kmh=rows["speed"].to_numpy(dtype=np.float64),
            throttle_pct=rows["throttle"].to_numpy(dtype=np.float64),
            brake=rows["brake"].to_numpy(dtype=bool),
        )
    return out
