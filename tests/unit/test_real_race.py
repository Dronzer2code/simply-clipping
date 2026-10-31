"""E3 real race moment: the OpenF1 loader and the moment at a real lap (no network)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pitwall_sim.config.loader import ConfigError, load_app, load_grid
from pitwall_sim.config.models import Compound
from pitwall_sim.race.engine import RaceSetup
from pitwall_sim.replay import real_race as R
from pitwall_sim.track.openf1 import OpenF1Client, RateLimiter

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
FIXTURE = ROOT / "tests" / "fixtures" / "real_race" / "jpn2026_openf1_trimmed.json"
#: Real order at the start of lap 30 (OpenF1 lap start times), BEA out on lap 21.
LAP30 = (
    "ANT", "PIA", "HAM", "RUS", "LEC", "NOR", "GAS", "VER", "LAW", "OCO", "BOR", "HAD", "HUL",
    "LIN", "SAI", "COL", "ALB", "PER", "STR", "ALO", "BOT", "BEA",
)  # fmt: skip


@pytest.fixture(scope="module")
def data() -> R.RealRaceData:
    return R.RealRaceData.load(FIXTURE)


@pytest.fixture(scope="module")
def lap30(data: R.RealRaceData) -> R.RealMoment:
    return R.moment(data, 30, load_grid("real_2026", CONFIG_DIR))


def test_order_laps_and_retired(lap30: R.RealMoment) -> None:
    assert lap30.order == LAP30
    assert (lap30.race_laps, lap30.laps_to_go) == (53, 24)
    cars = {c.driver_id: c for c in lap30.cars}
    assert cars["ANT"].laps_done == 29 and cars["ANT"].lap_fraction == 0.0
    assert all(c.laps_done == 28 for c in lap30.cars[1:-1])  # nobody lapped yet
    assert lap30.retired == ("BEA",) and cars["BEA"].laps_done == 20
    assert [c.position for c in lap30.cars] == list(range(1, 23))


def test_gaps_and_track_position(lap30: R.RealMoment) -> None:
    cars = {c.driver_id: c for c in lap30.cars}
    assert cars["PIA"].gap_s == pytest.approx(1.912, abs=1e-3)
    assert cars["NOR"].gap_s == pytest.approx(5.047, abs=1e-3)
    assert cars["NOR"].interval_s == pytest.approx(5.047 - 3.951, abs=1e-3)
    assert cars["BOT"].gap_s == pytest.approx(29.952, abs=1e-3)
    running = [c for c in lap30.cars if not c.retired]
    gaps = [c.gap_s for c in running]
    assert gaps == sorted(gaps)
    for c in running[1:]:  # behind the line: the rest of the lap = the gap
        assert 0.0 < 1.0 - c.lap_fraction < 0.4
        assert c.lap_elapsed_s + c.gap_s == pytest.approx(c.lap_elapsed_s / c.lap_fraction, 1e-6)


def test_tyres_and_stops(lap30: R.RealMoment) -> None:
    cars = {c.driver_id: c for c in lap30.cars}
    # NOR: MEDIUM to lap 16, HARD from lap 17; on lap 29 now -> 12 laps on the HARD
    assert (cars["NOR"].compound, cars["NOR"].tyre_age_laps, cars["NOR"].pit_stops) == (
        Compound.HARD, 12, 1,
    )  # fmt: skip
    # ANT (leader, on lap 30): HARD from lap 23 -> 7 laps
    assert (cars["ANT"].compound, cars["ANT"].tyre_age_laps) == (Compound.HARD, 7)
    # STR: HARD 22-24, MEDIUM from 25 -> two stops, 4 laps on the MEDIUM
    assert (cars["STR"].compound, cars["STR"].tyre_age_laps, cars["STR"].pit_stops) == (
        Compound.MEDIUM, 4, 2,
    )  # fmt: skip
    assert cars["BOT"].compound == Compound.MEDIUM  # started on HARD


def test_earlier_lap_and_bounds(data: R.RealRaceData) -> None:
    grid = load_grid("real_2026", CONFIG_DIR)
    lap20 = R.moment(data, 20, grid)
    assert lap20.order[0] == "RUS" and lap20.laps_to_go == 34  # before the stops
    assert lap20.retired == ()  # BEA still running on lap 20
    with pytest.raises(ValueError):
        R.moment(data, 1, grid)
    with pytest.raises(ValueError):
        R.moment(data, 54, grid)


def test_unknown_car_is_a_config_error(data: R.RealRaceData) -> None:
    bad = replace(data, drivers=[*data.drivers, {"driver_number": 99, "name_acronym": "XXX"}])
    with pytest.raises(ConfigError):
        R.driver_ids(bad, load_grid("real_2026", CONFIG_DIR))


def test_start_state_and_setup_defaults(lap30: R.RealMoment) -> None:
    app = load_app(CONFIG_DIR)
    cfg = app.real_race
    base = RaceSetup(seed=7, our_driver_id="NOR", scripted_sc_lap=12, laps=15, fuel_kg=110.0)
    setup = R.race_setup(base, lap30, app)
    assert setup.seed == 7 and setup.our_driver_id == "NOR"
    assert setup.laps == 53 and setup.grid_order == LAP30 and setup.rain == "dry"
    assert setup.fuel_kg == pytest.approx(24 * cfg.fuel_per_lap_kg + cfg.fuel_margin_kg)
    assert setup.scripted_sc_lap == R.NO_SC_LAP  # lap 12 is behind the moment
    assert R.race_setup(replace(base, scripted_sc_lap=35), lap30, app).scripted_sc_lap == 35
    assert setup.start is not None
    start = {c.driver_id: c for c in setup.start.cars}
    assert start["NOR"].tyre_wear == pytest.approx(12 * cfg.wear_per_lap[Compound.HARD])
    assert start["STR"].tyre_wear == pytest.approx(4 * cfg.wear_per_lap[Compound.MEDIUM])
    assert setup.start.battery_fraction == cfg.battery_fraction
    assert start["BEA"].retired


def test_save_trim_load_round_trip(data: R.RealRaceData, tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    small = data.trimmed([1, 29, 30, 31])
    small.save(path)
    again = R.RealRaceData.load(path)
    assert again == small
    assert {r["lap_number"] for r in again.laps} == {1, 29, 30, 31}
    lap30 = R.moment(again, 30, load_grid("real_2026", CONFIG_DIR))
    assert lap30.order[:21] == LAP30[:21]  # the running cars need only the laps around


def test_fetch_uses_the_openf1_client_and_its_cache(data: R.RealRaceData, tmp_path: Path) -> None:
    urls: list[str] = []
    tables = {e: getattr(data, e) for e in R.ENDPOINTS}

    def fake(url: str, timeout_s: float) -> list[dict[str, object]]:
        urls.append(url)
        endpoint = url.split("/v1/")[1].split("?")[0]
        assert "session_key=11253" in url
        return list(tables[endpoint])

    app = load_app(CONFIG_DIR)
    client = OpenF1Client(app.openf1, tmp_path, RateLimiter(100, 1000), fetch=fake)
    first = R.RealRaceData.fetch(11253, client)
    assert first == data and len(urls) == len(R.ENDPOINTS)
    again = R.RealRaceData.fetch(11253, OpenF1Client(app.openf1, tmp_path, fetch=fake))
    assert again == data and len(urls) == len(R.ENDPOINTS)  # second time from the cache
