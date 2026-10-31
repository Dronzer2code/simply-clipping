"""T-050: Public Feed (4 Hz, noise, dropout) and public timing.

Acceptance: frame rate, noise sigma and drop rate within 10 % of config over a
race. Each emission keeps the cars' true values next to the drawn noise, so the
published values can be compared with Ground Truth.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.models import Compound
from pitwall_sim.race.engine import RaceEngine, RaceSetup

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
OUR_CAR = "ANT"


@pytest.fixture(scope="module")
def race() -> RaceEngine:
    engine = RaceEngine(RaceSetup(laps=2, fuel_kg=40.0, our_driver_id=OUR_CAR), CONFIG_DIR)
    i = engine.driver_ids.index("HAM")
    while not engine.finished:
        if engine.st.lap[i] == 0 and not engine.pit.events:
            engine.box(i, Compound.HARD)
        engine.tick()
    return engine


def _published(engine: RaceEngine) -> dict[str, np.ndarray]:
    feed = engine.feed
    cols: dict[str, list[np.ndarray]] = {}
    for tick in feed.ticks:
        c = feed.columns(tick)
        k = (tick.s_m / feed.ds_m).astype(np.int64) % feed.x.size
        parts = {
            "speed_err": c["speed_kmh"] - tick.v_ms * 3.6,
            "throttle_err": c["throttle_pct"] - tick.throttle * 100.0,
            "throttle_true": tick.throttle,
            "x_err": c["x_m"] - feed.x[k],
            "y_err": c["y_m"] - feed.y[k],
            "car": tick.car,
        }
        for name, value in parts.items():
            cols.setdefault(name, []).append(np.asarray(value, dtype=np.float64))
    return {name: np.concatenate(v) for name, v in cols.items()}


def test_frame_rate_and_drop_rate_match_config(race: RaceEngine) -> None:
    cfg, feed = race.app.feed, race.feed
    attempts = feed.emitted + feed.dropped
    assert feed.dropped / attempts == pytest.approx(cfg.drop_p, rel=0.10)
    # Every car is in the feed (Our Car too, owner day 6), minus pit-lane time;
    # finished cars stop emitting, so compare against the time each car raced.
    racing_s = sum(
        (race.timing.finish_t[i] if np.isfinite(race.timing.finish_t[i]) else race.t)
        for i in range(race.n)
    )  # fmt: skip
    rate = attempts / racing_s
    assert rate == pytest.approx(cfg.rate_hz, rel=0.10)


def test_noise_sigmas_match_config(race: RaceEngine) -> None:
    cfg = race.app.feed
    pub = _published(race)
    assert pub["speed_err"].size > 5_000
    assert np.std(pub["speed_err"]) == pytest.approx(cfg.speed_noise_kmh, rel=0.10)
    part = (pub["throttle_true"] > 0.05) & (pub["throttle_true"] < 0.95)  # away from the clip
    # Quantising to 1 % (also part of the spec) adds 1/12 %^2 of variance.
    expected = np.sqrt(cfg.throttle_noise_pct**2 + 1.0 / 12.0)
    assert np.std(pub["throttle_err"][part]) == pytest.approx(expected, rel=0.10)
    for axis in ("x_err", "y_err"):
        assert np.std(pub[axis]) == pytest.approx(cfg.position_noise_m, rel=0.10)


def test_frames_follow_the_contract_with_every_car(race: RaceEngine) -> None:
    feed = race.feed
    frames = feed.recent()
    assert set(frames) == set(race.driver_ids)  # Rivals see Our Car too (owner, day 6)
    ham = frames["HAM"]
    assert ham and all(a.t_s < b.t_s for a, b in zip(ham, ham[1:], strict=False))
    for f in ham:
        assert 0.0 <= f.throttle_pct <= 100.0 and f.throttle_pct == round(f.throttle_pct)
        assert 1 <= f.gear <= len(race.app.feed.gear_upshift_kmh) + 1
        assert 0.0 <= f.distance_m < race.trk.length_m
        assert isinstance(f.brake, bool)
    assert feed.frames("HAM", since_s=ham[-5].t_s) == ham[-4:]
    assert len(feed.ticks) > 0.9 * race.app.feed.window_s * race.app.feed.rate_hz  # full window
    assert feed.ticks[-1].t_s - feed.ticks[0].t_s < race.app.feed.window_s


def test_gear_rises_with_speed(race: RaceEngine) -> None:
    gears = race.feed.gear(np.array([10.0, 30.0, 50.0, 70.0, 90.0]))
    assert list(gears) == sorted(gears) and gears[0] == 1 and gears[-1] == 8


def test_public_timing_lists_tyres_and_stops(race: RaceEngine) -> None:
    timing = race.timing_state()
    assert timing.compound["HAM"] == Compound.HARD
    assert timing.pit_stops["HAM"] == 1
    assert timing.pit_stops["VER"] == 0
    assert timing.tyre_age_laps["VER"] == race.laps
    assert set(timing.penalties_s.values()) == {0.0}


def test_rivals_radar_follows_our_car_but_our_view_lists_only_rivals(race: RaceEngine) -> None:
    """Owner, day 6: a rival team sees our public telemetry; our pit wall lists the Rivals."""
    from pitwall_sim.observe.engineer_view import EngineerViewBuilder

    i = race.driver_ids.index(OUR_CAR)
    assert race.radar.frame_n[i] > 0  # the Rivals' Radar takes Our Car's frames
    view = EngineerViewBuilder(race, OUR_CAR).build()
    assert OUR_CAR not in view.rival_feed and OUR_CAR not in view.radar
