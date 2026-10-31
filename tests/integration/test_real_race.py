"""E3 real race moment: the race engine starts from a real lap and runs to the flag."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app, load_grid
from pitwall_sim.config.models import Compound
from pitwall_sim.live.session import LiveSession, LiveSetup
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.replay import real_race as R

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
FIXTURE = ROOT / "tests" / "fixtures" / "real_race" / "jpn2026_openf1_trimmed.json"


@pytest.fixture(scope="module")
def data() -> R.RealRaceData:
    return R.RealRaceData.load(FIXTURE)


def _engine(data: R.RealRaceData, lap: int, seed: int = 1, our: str = "NOR") -> RaceEngine:
    setup = R.real_setup(RaceSetup(seed=seed, our_driver_id=our), lap, CONFIG_DIR, data)
    return RaceEngine(setup, CONFIG_DIR)


@pytest.fixture(scope="module")
def lap30(data: R.RealRaceData) -> R.RealMoment:
    return R.moment(data, 30, load_grid("real_2026", CONFIG_DIR))


def test_engine_starts_from_the_real_state(data: R.RealRaceData, lap30: R.RealMoment) -> None:
    e = _engine(data, 30)
    timing = e.timing_state()
    running = [d for d in lap30.order if d not in lap30.retired]
    assert timing.order == [*running, *lap30.retired]  # real order, BEA out
    assert e.laps == 53
    real = {c.driver_id: c for c in lap30.cars}
    ids = e.driver_ids
    for d in running:
        i = ids.index(d)
        assert timing.gap_to_leader_s[d] == pytest.approx(real[d].gap_s, abs=1e-6)
        assert int(e.st.lap[i]) == real[d].laps_done
        assert e.compounds[i] == real[d].compound
        assert timing.tyre_age_laps[d] == real[d].tyre_age_laps
        assert timing.pit_stops[d] == real[d].pit_stops
        assert e.st.v_ms[i] > 20.0  # a flying start
    assert e.status[ids.index("BEA")] == "DNF"
    # On the road: leader at the line, everyone else behind it by the real lap share.
    s = e.st.s_m
    assert s[ids.index("ANT")] == pytest.approx(0.0)
    length = e.trk.length_m
    behind = {d: length - float(s[ids.index(d)]) for d in running[1:]}
    assert behind["PIA"] == pytest.approx((1 - real["PIA"].lap_fraction) * length, abs=1e-6)
    progress = [e.st.lap[ids.index(d)] * length + s[ids.index(d)] for d in running]
    assert np.all(np.diff(progress) <= -load_app(CONFIG_DIR).real_race.min_spacing_m + 1e-9)
    # Hidden state from the documented defaults.
    cfg = load_app(CONFIG_DIR).real_race
    nor = ids.index("NOR")
    assert e.st.tyre_wear[nor] == pytest.approx(12 * cfg.wear_per_lap[Compound.HARD])
    assert e.st.battery_j[nor] == pytest.approx(e.cars.e_usable_max_j[nor] * cfg.battery_fraction)
    assert e.st.fuel_kg[nor] == pytest.approx(24 * cfg.fuel_per_lap_kg + cfg.fuel_margin_kg)
    # Rivals that already stopped have no planned stop left (only a worn-out tyre).
    k = list(e.rival_book.driver_ids).index("PIA")
    assert e.rival_book.stops_done[k] == 1


def test_race_runs_from_lap_30_to_the_flag(data: R.RealRaceData) -> None:
    e = _engine(data, 30)
    result = e.run()
    assert result.finished
    assert max(result.laps_completed.values()) == 53
    assert set(result.retired) == {"BEA"}  # nobody runs out of fuel
    assert result.t_s < 24 * 200.0
    assert all(len(result.lap_times_s[d]) <= 25 for d in result.lap_times_s)  # + lap 29 end
    first = {d: t[0] for d, t in result.lap_times_s.items() if t}
    assert all(80.0 < t < 200.0 for t in first.values()), first  # first lap timed from the line


def test_deterministic_per_seed(data: R.RealRaceData) -> None:
    a, b, c = (_engine(data, 49, seed) for seed in (3, 3, 4))
    ra, rb, _ = a.run(), b.run(), c.run()
    assert ra.finished and ra.classification == rb.classification
    assert a.race_state().hash() == b.race_state().hash()
    assert ra.t_s == rb.t_s
    assert a.race_state().hash() != c.race_state().hash()


def test_live_session_starts_at_the_real_lap(
    data: R.RealRaceData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(R, "load_data", lambda app, config_dir=None, session_key=None: data)
    s = LiveSession(LiveSetup(our_driver_id="NOR", real_lap=30, preset="repass", laps=5),
                    CONFIG_DIR)  # fmt: skip
    f = s.frame()
    assert (f.lap, f.laps) == (30, 53)
    assert s.preset_rival is None  # presets do not apply to a real race moment
    view = f.view
    assert view.timing.order[:6] == ["ANT", "PIA", "HAM", "RUS", "LEC", "NOR"]
    assert s.advance(5.0)
    assert s.frame().lap >= 30


def test_headless_cli_prints_grid_and_result(capsys: pytest.CaptureFixture[str]) -> None:
    code = R.main(["--lap", "50", "--our", "NOR", "--seed", "1", "--fixture", str(FIXTURE)])
    out = capsys.readouterr().out
    assert code == 0
    assert "start of lap 50/53 (4 laps to race)" in out
    assert "  1 ANT " in out and "OUT" in out  # leader; STR and BEA out by lap 50
    assert "NOR*" in out
