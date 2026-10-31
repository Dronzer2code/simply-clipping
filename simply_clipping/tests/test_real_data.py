"""SC-5: an OpenF1 race converts to the bridge input (offline, from a filled cache)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from simply_clipping.real_data import cache_path, convert


def _put(cache: Path, endpoint: str, params: dict[str, int], rows: list[dict[str, object]]) -> None:
    path = cache_path(endpoint, params, cache)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_openf1_race_converts_to_the_bridge_input(tmp_path: Path) -> None:
    cache, s = tmp_path / "cache", 9999
    _put(
        cache,
        "drivers",
        {"session_key": s},
        [{"driver_number": 1, "name_acronym": "AAA", "team_name": "Team A"}],
    )
    _put(
        cache,
        "laps",
        {"session_key": s},
        [
            {"driver_number": 1, "lap_number": 1, "date_start": "2026-03-29T05:00:00+00:00"},
            {"driver_number": 1, "lap_number": 2, "date_start": "2026-03-29T05:01:30+00:00"},
        ],
    )
    t = pd.date_range("2026-03-29T05:00:00Z", periods=400, freq="250ms")
    _put(
        cache,
        "car_data",
        {"session_key": s, "driver_number": 1},
        [
            {"date": d.isoformat(), "speed": 180.0, "throttle": 100, "brake": 0, "n_gear": 7}
            for d in t
        ],
    )
    _put(
        cache,
        "location",
        {"session_key": s, "driver_number": 1},
        [{"date": d.isoformat(), "x": 10.0 * i, "y": 0.0, "z": 0.0} for i, d in enumerate(t)],
    )
    feed = tmp_path / "feed"
    convert(s, cache, feed)
    cars = pd.read_parquet(feed / "cars.parquet")
    assert list(cars.columns) == [
        "driver",
        "time",
        "distance",
        "speed",
        "throttle",
        "brake",
        "gear",
        "x",
        "y",
    ]
    assert set(cars["driver"]) == {"AAA"} and cars["time"].iloc[0] == 0.0
    np.testing.assert_allclose(cars["distance"].iloc[-1], 50.0 * 0.25 * 399, rtol=1e-6)
    np.testing.assert_allclose(cars["x"].iloc[4], 4.0)  # decimetres -> metres
    laps = pd.read_parquet(feed / "laps.parquet")
    assert laps["LapStartTime"].dt.total_seconds().tolist() == [0.0, 90.0]
