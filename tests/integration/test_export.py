"""Sprint S-1: the race export (FastF1-like feed, Ground Truth, events, car params)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pitwall_sim.export import FEED_FILES, export_race

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def export(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("export")
    return out, export_race(out, seed=42, scenario="normal", laps=2, config_dir=CONFIG_DIR)


def test_feed_files_look_like_fastf1(export: tuple[Path, dict[str, Any]]) -> None:
    out, _ = export
    feed = {name: pd.read_parquet(out / "feed" / f"{name}.parquet") for name in FEED_FILES}
    assert list(feed["cars"].columns) == [
        "driver", "time", "distance", "speed", "throttle", "brake", "gear", "x", "y",
    ]  # fmt: skip
    assert feed["cars"]["driver"].nunique() == 22  # every car, Our Car included
    assert set(feed["car_data"].columns) >= {"Driver", "SessionTime", "Speed", "RPM", "nGear",
                                             "Throttle", "Brake"}  # fmt: skip
    assert "DRS" not in feed["car_data"].columns
    assert set(feed["pos_data"].columns) >= {"Driver", "SessionTime", "X", "Y", "Z"}
    assert feed["car_data"]["Throttle"].dtype.kind == "i"
    assert feed["car_data"]["Brake"].dtype == bool
    assert set(feed["laps"].columns) == {
        "Driver", "DriverNumber", "Team", "LapNumber", "LapTime", "Sector1Time", "Sector2Time",
        "Sector3Time", "LapStartTime", "Position", "Compound", "TyreLife", "PitInTime",
        "PitOutTime",
    }  # fmt: skip
    assert pd.api.types.is_timedelta64_dtype(feed["laps"]["LapTime"])
    assert set(feed["gaps"].columns) == {"Driver", "LapNumber", "Time", "GapToLeader",
                                         "IntervalToPositionAhead"}  # fmt: skip


def test_streams_have_their_own_rate_jitter_and_dropouts(
    export: tuple[Path, dict[str, Any]],
) -> None:
    out, _ = export
    car = pd.read_parquet(out / "feed" / "car_data.parquet")
    pos = pd.read_parquet(out / "feed" / "pos_data.parquet")
    one_car = car[car["Driver"] == "VER"]["SessionTime"].dt.total_seconds().to_numpy()
    one_pos = pos[pos["Driver"] == "VER"]["SessionTime"].dt.total_seconds().to_numpy()
    assert not np.array_equal(one_car[:50], one_pos[:50])  # independent timestamps
    steps = np.diff(one_car)
    assert 1 / 4.0 - 0.07 <= np.median(steps) <= 1 / 3.7 + 0.07
    assert (steps > 0.4).any()  # dropped frames and gaps
    rate = one_car.size / (one_car[-1] - one_car[0])
    assert 3.0 < rate < 4.0


def test_ground_truth_at_10_hz_with_every_flag(export: tuple[Path, dict[str, Any]]) -> None:
    out, info = export
    gt = pd.read_parquet(out / "truth" / "ground_truth.parquet")
    for col in ("time_s", "distance_m", "battery_mj", "p_ice_kw", "p_k_deploy_kw",
                "p_harvest_kw", "superclip", "taper_active", "zone_cap_kw", "overtake_active",
                "energy_mode", "aero_mode", "cda_true", "mass_kg", "state_true"):  # fmt: skip
        assert col in gt.columns, col
    ver = gt[gt["driver"] == "VER"]
    assert np.median(np.diff(ver["time_s"].to_numpy())) == pytest.approx(1.0 / info["truth_hz"])
    assert set(gt["state_true"]) <= {"DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE"}
    assert {"DEPLOY", "HARVEST"} <= set(gt["state_true"])
    assert ((gt["battery_mj"] >= 0.0) & (gt["battery_mj"] <= 4.0 + 1e-6)).all()
    assert gt["superclip"].dtype == bool and gt["taper_active"].dtype == bool


def test_events_car_params_and_run_info(export: tuple[Path, dict[str, Any]]) -> None:
    out, info = export
    ev = pd.read_parquet(out / "truth" / "events.parquet")
    assert {"type", "t_start_s", "t_end_s", "lap", "car_a", "car_b", "s_m", "value",
            "scenario_target"} <= set(ev.columns)  # fmt: skip
    assert {"overtake", "clip"} <= set(ev["type"])
    params = json.loads((out / "truth" / "car_params.json").read_text(encoding="utf-8"))
    assert len(params) == 22
    ver = params["VER"]
    assert ver["cda_straight_m2"] < ver["cda_corner_m2"]
    assert ver["mass_start_kg"] == pytest.approx(ver["mass_min_kg"] + info["fuel_kg"])
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["seed"] == 42 and run["scenario"] == "normal" and run["commit"]
    assert run["targets"]["produced"]


def test_same_seed_same_export(tmp_path: Path, export: tuple[Path, dict[str, Any]]) -> None:
    out, _ = export
    again = export_race(tmp_path, seed=42, scenario="normal", laps=2, config_dir=CONFIG_DIR)
    assert again["race_time_s"] == pytest.approx(export[1]["race_time_s"])
    a = pd.read_parquet(out / "feed" / "cars.parquet")
    b = pd.read_parquet(tmp_path / "feed" / "cars.parquet")
    pd.testing.assert_frame_equal(a, b)
