"""T-025/T-026: calibration compare: references, rule set by date, RMSE, order, CLI."""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import pytest

from pitwall_sim.calibration import compare
from pitwall_sim.calibration.compare import (
    EXIT_OK,
    EXIT_UNAVAILABLE,
    ReferenceLap,
    lap_of,
    load_reference_lap,
    load_team_references,
    order_ok,
    positions,
    rule_set_for_date,
    simulate_quali_lap,
    speed_rmse_kmh,
    track_arrays,
    valid_car_samples,
)
from pitwall_sim.car.lap_sim import LapResult
from pitwall_sim.config.loader import (
    ConfigError,
    load_app,
    load_grid,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.track.builder import TrackModel, read_track_model
from pitwall_sim.track.openf1 import OpenF1Client, OpenF1Error, RateLimiter
from tests.unit.test_openf1 import _FakeApi

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
SUZUKA = ROOT / "data" / "tracks" / "suzuka.parquet"


@pytest.fixture(scope="module")
def model() -> TrackModel:
    return read_track_model(SUZUKA)


def test_rule_set_follows_the_reference_date() -> None:
    assert rule_set_for_date(date(2026, 3, 28), CONFIG_DIR).rule_set_id == "2026_pre_miami"
    assert rule_set_for_date(date(2026, 5, 3), CONFIG_DIR).rule_set_id == "2026_post_miami"
    assert rule_set_for_date(date(2026, 10, 11), CONFIG_DIR).rule_set_id == "2026_post_miami"
    with pytest.raises(ConfigError, match="no Rule Set"):
        rule_set_for_date(date(2025, 12, 1), CONFIG_DIR)


def _raw_xy(model: TrackModel, i: int) -> tuple[int, int]:
    """Raw (unscaled) OpenF1 coordinates, 1/10 m, of model point ``i``."""
    cx, cy = model.x_m.mean(), model.y_m.mean()
    k = model.scale_factor
    x = cx + (model.x_m[i] - cx) / k
    y = cy + (model.y_m[i] - cy) / k
    return round(x * 10), round(y * 10)


def test_reference_lap_maps_speed_samples_onto_the_centre_line(
    model: TrackModel, tmp_path: Path
) -> None:
    start = datetime(2026, 3, 28, 6, 49, 1, tzinfo=UTC)
    lap_s = 88.0
    every = 100  # one location sample per 100 m, crossing s = 0 near the end
    idx = list(range(50, model.s_m.size, every)) + [model.s_m.size - 1, 10]
    location, car_data = [], []
    for n, i in enumerate(idx):
        t = start + timedelta(seconds=lap_s * n / len(idx))
        x, y = _raw_xy(model, i)
        location.append({"date": t.isoformat(), "x": x, "y": y})
        # car_data halfway between location samples, speed = 100 + metres / 100.
        if n + 1 < len(idx):
            car_data.append({"date": (t + timedelta(seconds=0.5 * lap_s / len(idx))).isoformat(),
                             "speed": 100 + n})  # fmt: skip
    api = _FakeApi(
        {
            "sessions": [
                {
                    "session_key": 1,
                    "session_name": "Qualifying",
                    "location": "Suzuka",
                    "circuit_short_name": "Suzuka",
                    "country_name": "Japan",
                    "date_start": "2026-03-28T06:00:00+00:00",
                }
            ],  # fmt: skip
            "laps": [
                {
                    "driver_number": 12,
                    "lap_number": 11,
                    "date_start": start.isoformat(),
                    "lap_duration": lap_s,
                    "is_pit_out_lap": False,
                }
            ],  # fmt: skip
            "location": location,
            "car_data": car_data,
        }
    )
    client = OpenF1Client(
        load_app(CONFIG_DIR).openf1,
        tmp_path,
        limiter=RateLimiter(3, 30, clock=lambda: 0.0, sleep=lambda _s: None),
        fetch=api,
    )

    ref = load_reference_lap(load_track("suzuka", CONFIG_DIR), model, client)

    assert ref.lap_time_s == lap_s
    assert ref.session_date == date(2026, 3, 28)
    assert ref.source["driver_number"] == "12"
    assert np.all(np.diff(ref.s_m) >= 0.0)  # sorted by distance
    # Samples lie halfway between their location samples (100 m apart).
    first = float(ref.s_m[np.argmin(np.abs(ref.speed_kmh - 100))])
    assert first == pytest.approx(model.s_m[50] + 50.0, abs=2.0)


def test_speed_rmse() -> None:
    s = np.arange(0.0, 100.0, 1.0)
    sim = LapResult(
        s_m=s,
        v_ms=np.full(s.size, 50.0),  # 180 km/h
        t_s=s / 50.0,
        battery_j=np.zeros(s.size),
        lap_time_s=2.0,
        harvested_j=0.0,
        drawn_j=0.0,
        fuel_used_kg=0.0,
        battery_end_j=0.0,
    )
    ref = ReferenceLap(2.0, np.array([10.0, 50.0, 99.5]), np.array([170.0, 190.0, 180.0]),
                       date(2026, 3, 28), {})  # fmt: skip

    assert speed_rmse_kmh(sim, ref) == pytest.approx(np.sqrt((100 + 100 + 0) / 3))


# --------------------------------------------------------------------------- #
# CLI (reference loader mocked: no network)
# --------------------------------------------------------------------------- #


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(CONFIG_DIR, tmp_path / "config")
    (tmp_path / "data" / "tracks").mkdir(parents=True)
    shutil.copy(SUZUKA, tmp_path / "data" / "tracks" / "suzuka.parquet")
    monkeypatch.chdir(tmp_path)
    return tmp_path / "config"


def _quali_lap(config_dir: Path, model: TrackModel, team_id: str = "mercedes") -> LapResult:
    track = load_track("suzuka", config_dir)
    return lap_of(
        simulate_quali_lap(
            track_arrays(model, track),
            track,
            rule_set_for_date(date(2026, 3, 28), config_dir),
            load_team_performance(config_dir).teams[team_id],
            load_tyres(config_dir),
            load_app(config_dir),
        )
    )


def test_cli_prints_and_writes_the_report(
    workdir: Path, model: TrackModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _quali_lap(workdir, model)
    # A reference identical to the simulation: delta 0, RMSE 0, PASS.
    ref = ReferenceLap(sim.lap_time_s, sim.s_m, sim.v_ms * 3.6, date(2026, 3, 28),
                       {"session_key": "1", "driver_number": "12"})  # fmt: skip
    monkeypatch.setattr(compare, "load_team_references", lambda *_a: {"mercedes": ref})

    code = compare.main(["--track", "suzuka", "--team", "mercedes", "--config-dir", str(workdir)])

    assert code == EXIT_OK
    table = pq.read_table("data/calibration/suzuka.parquet")
    row: dict[str, Any] = table.to_pylist()[0]
    assert row["team_id"] == "mercedes"
    assert row["delta_pct"] == pytest.approx(0.0, abs=1e-9)
    assert row["speed_rmse_kmh"] == pytest.approx(0.0, abs=1e-6)
    assert row["lap_time_ok"] and row["speed_ok"]
    assert table.schema.metadata[b"rule_set_id"] == b"2026_pre_miami"
    assert table.schema.metadata[b"deploy"] == b"policy"


def test_cli_reports_missing_references(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object) -> None:
        raise OpenF1Error("no data")

    monkeypatch.setattr(compare, "load_team_references", unavailable)

    assert compare.main(["--track", "suzuka", "--config-dir", str(workdir)]) == EXIT_UNAVAILABLE


def test_quali_conditions_use_the_track_fuel_and_a_full_battery(model: TrackModel) -> None:
    """Owner round 10: quali_fuel_kg from the track (5 kg), battery full, policy deploy."""
    track = load_track("suzuka", CONFIG_DIR)
    assert track.quali_fuel_kg == 5.0
    lap = _quali_lap(CONFIG_DIR, model)

    assert lap.battery_j[0] == pytest.approx(4.0e6)
    assert lap.zone_drawn_j is not None  # the deploy policy ran


def test_positions_and_order_check() -> None:
    assert positions({"a": 90.0, "b": 89.0, "c": 91.0}) == {"b": 1, "a": 2, "c": 3}

    def result(real: int, sim: int) -> compare.TeamResult:
        return compare.TeamResult("t", 90.0, 90.0, 0.0, 0.0, True, True, real, sim, 0.0, 0.0)

    assert order_ok([result(1, 3), result(4, 2)], 2)
    assert not order_ok([result(1, 4)], 2)


def test_team_references_pick_each_teams_best_driver(model: TrackModel, tmp_path: Path) -> None:
    start = datetime(2026, 3, 28, 6, 49, 1, tzinfo=UTC)
    location = [{"date": (start + timedelta(seconds=n)).isoformat(),
                 "x": _raw_xy(model, i)[0], "y": _raw_xy(model, i)[1]}
                for n, i in enumerate(range(0, model.s_m.size, 500))]  # fmt: skip
    car_data = [{"date": (start + timedelta(seconds=n + 0.5)).isoformat(), "speed": 200}
                for n in range(len(location) - 1)]  # fmt: skip

    def lap(car: int, duration: float, out_lap: bool = False) -> dict[str, Any]:
        return {"driver_number": car, "lap_number": 5, "date_start": start.isoformat(),
                "lap_duration": duration, "is_pit_out_lap": out_lap}  # fmt: skip

    api = _FakeApi(
        {
            "sessions": [
                {
                    "session_key": 1,
                    "session_name": "Qualifying",
                    "location": "Suzuka",
                    "circuit_short_name": "Suzuka",
                    "country_name": "Japan",
                    "date_start": "2026-03-28T06:00:00+00:00",
                }
            ],  # fmt: skip
            # Mercedes: 12 and 63; McLaren: 81; car 99 is not on the grid.
            "laps": [
                lap(12, 88.9),
                lap(63, 88.7),
                lap(81, 89.1),
                lap(81, 80.0, out_lap=True),
                lap(99, 70.0),
            ],  # fmt: skip
            "location": location,
            "car_data": car_data,
        }
    )
    client = OpenF1Client(
        load_app(CONFIG_DIR).openf1,
        tmp_path,
        limiter=RateLimiter(3, 30, clock=lambda: 0.0, sleep=lambda _s: None),
        fetch=api,
    )

    refs = load_team_references(
        load_track("suzuka", CONFIG_DIR), model, client, load_grid("real_2026", CONFIG_DIR)
    )

    assert set(refs) == {"mercedes", "mclaren"}
    assert refs["mercedes"].lap_time_s == 88.7  # the better of its two drivers
    assert refs["mercedes"].source["driver_number"] == "63"
    assert refs["mclaren"].lap_time_s == 89.1  # out lap ignored

    # Owner round 13: speed traces must cover enough 250 m sections. The fake
    # laps sample every 500 m, so each covers about half of the 24 sections.
    covered, n_sections = compare.section_coverage(refs["mercedes"].s_m, model.length_m, 250.0)
    assert n_sections == 24 and covered < n_sections
    track, grid = load_track("suzuka", CONFIG_DIR), load_grid("real_2026", CONFIG_DIR)
    enough = load_team_references(track, model, client, grid, min_sections=covered)
    assert enough["mercedes"].lap_time_s == 88.7
    assert enough["mercedes"].source["sections_covered"] == f"{covered}/24"
    assert load_team_references(track, model, client, grid, min_sections=covered + 1) == {}


def test_invalid_and_frozen_car_samples_are_dropped() -> None:
    def row(speed: int, rpm: int = 10_000, throttle: int = 100, brake: int = 0) -> dict[str, Any]:
        return {"speed": speed, "rpm": rpm, "n_gear": 7, "throttle": throttle, "brake": brake}

    rows = [row(200), row(210), row(189, 11535, 104, 104), row(250), row(250), row(250), row(250),
            row(260), row(260), row(270)]  # fmt: skip

    kept = valid_car_samples(rows)

    # 104 is out of range; the 4-sample frozen run keeps only its first sample;
    # a 2-sample repeat is normal and kept.
    assert [r["speed"] for r in kept] == [200, 210, 250, 260, 260, 270]


def test_section_coverage_counts_sections_with_samples() -> None:
    from pitwall_sim.calibration.compare import section_coverage

    s = np.array([10.0, 260.0, 270.0, 990.0, 1010.0])  # 1010 wraps to 10 on a 1000 m lap
    assert section_coverage(s, 1000.0, 250.0) == (3, 4)
    assert section_coverage(np.arange(0.0, 5807.0, 50.0), 5807.0, 250.0) == (24, 24)
