"""P1 load: the public inputs of the bridge contract and the package's config.yaml.

Reads only what ``docs/spec/SIMPLY_CLIPPING_BRIDGE.md`` allows (SC-R02): the
export's ``feed/`` files, the track's public layout JSON, and the rows of ``our``
in ``own_file`` (a team knows its own exact battery, never another car's).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

CONFIG_FILE = Path(__file__).with_name("config.yaml")
FEED_FILES = ("cars.parquet", "laps.parquet", "gaps.parquet")
CARS_COLUMNS = ("driver", "time", "distance", "speed", "throttle", "brake", "gear", "x", "y")
#: Our own exact channels; nothing else is read from ``own_file``.
OWN_COLUMNS = ("driver", "time_s", "lap", "lap_distance_m", "speed_kmh", "throttle", "brake",
               "battery_mj")  # fmt: skip

Config = dict[str, Any]


@dataclass(frozen=True)
class Feed:
    """One race's public feed (BRIDGE section 1)."""

    cars: pd.DataFrame
    """Merged per-car stream: driver, time (s), distance (m), speed (km/h), throttle, brake, ..."""
    laps: pd.DataFrame
    """FastF1-style lap table."""
    gaps: pd.DataFrame
    """Per car per lap at the line: GapToLeader, IntervalToPositionAhead (s)."""


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
