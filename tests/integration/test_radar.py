"""T-051: Rival Battery Radar on the simulator's Public Feed.

``test_radar_on_sim`` reports the Radar's error against Ground Truth (run with
``pytest -s`` to see it). The Radar sees only feed frames, the public Straight
Mode zones and its own ``radar.*`` constants (import-linter contract
``radar-feed-only`` keeps it away from the simulation core).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app, unresolved_keys
from pitwall_sim.observe.radar.energy import _ANCHOR_T, _WEIGHT, RadarEstimator, estimate_batch
from pitwall_sim.observe.radar.physics import savgol_coefficients
from pitwall_sim.race.engine import RaceEngine, RaceSetup

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def _zones(engine: RaceEngine) -> list[tuple[float, float]]:
    return [
        (z.s_start_m, z.s_end_m) for z in engine.track.zones if "straight_mode_allowed" in z.tags
    ]


@pytest.fixture(scope="module")
def radar_race() -> tuple[RaceEngine, dict[str, RadarEstimator], np.ndarray]:
    engine = RaceEngine(RaceSetup(laps=3, fuel_kg=50.0), CONFIG_DIR)
    args = (engine.app.radar, _zones(engine), engine.trk.length_m, engine.app.feed.rate_hz)
    radar = {d: RadarEstimator(d, *args) for d in engine.driver_ids}
    truth_t: list[float] = []
    truth: list[np.ndarray] = []
    rows = []  # (t, car, estimate MJ, confidence)
    last = -np.inf
    while not engine.finished:
        engine.tick()
        truth_t.append(engine.t)
        truth.append(engine.st.battery_j / 1e6)
        if engine.steps % engine.decision_steps == 0:
            new = engine.feed.recent(since_s=last)
            last = engine.t
            for i, d in enumerate(engine.driver_ids):
                e = radar[d].update(new.get(d, []))
                if e.confidence > 0.0:
                    rows.append((e.t_s, i, e.energy_mj, e.confidence))
    t = np.array(truth_t)
    gt = np.array(truth)
    r = np.array(rows)
    true_at = np.array([np.interp(ts, t, gt[:, int(i)]) for ts, i in r[:, :2]])
    return engine, radar, np.column_stack((r, true_at))


def test_radar_on_sim(radar_race) -> None:  # type: ignore[no-untyped-def]
    engine, radar, rows = radar_race
    cfg = engine.app.radar
    err = rows[:, 2] - rows[:, 4]
    print(
        f"\nRadar on sim (3 laps, {rows.shape[0]} estimates): MAE {np.mean(np.abs(err)):.2f} MJ, "
        f"median {np.median(np.abs(err)):.2f}, p90 {np.percentile(np.abs(err), 90):.2f}, "
        f"bias {err.mean():+.2f} MJ (window {cfg.e_max_mj} MJ)"
    )
    # Owner, sprint day 5: before its first anchor every car has the start prior
    # (assumed full, confidence start_prior_confidence decaying); an anchor replaces it.
    known = set(rows[:, 1].astype(int))
    assert known == set(range(engine.n))
    for d in engine.driver_ids:
        e = radar[d].estimate()
        assert e.prior != radar[d].anchored
        if e.prior:
            assert 0.0 < e.confidence <= cfg.start_prior_confidence
    assert ((rows[:, 2] >= 0.0) & (rows[:, 2] <= cfg.e_max_mj)).all()
    assert ((rows[:, 3] > 0.0) & (rows[:, 3] <= 1.0)).all()
    assert np.mean(np.abs(err)) < cfg.e_max_mj / 2  # sanity: better than knowing nothing
    states = {radar[d].state for d in engine.driver_ids}
    assert states <= {"DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE"}


def test_incremental_equals_batch(radar_race) -> None:  # type: ignore[no-untyped-def]
    engine, _, _ = radar_race
    frames = engine.feed.frames("VER")
    args = (engine.app.radar, _zones(engine), engine.trk.length_m, engine.app.feed.rate_hz)
    batch = estimate_batch("VER", frames, *args)
    step = RadarEstimator("VER", *args)
    for k in range(0, len(frames), 7):
        incremental = step.update(frames[k : k + 7])
    assert incremental == batch


def test_radar_uses_its_own_constants(radar_race) -> None:  # type: ignore[no-untyped-def]
    engine, _, _ = radar_race
    frames = engine.feed.frames("VER")
    zones = _zones(engine)
    base = estimate_batch("VER", frames, engine.app.radar, zones, engine.trk.length_m, 4.0)
    heavier = engine.app.radar.model_copy(update={"mass_kg": engine.app.radar.mass_kg * 1.2})
    other = estimate_batch("VER", frames, heavier, zones, engine.trk.length_m, 4.0)
    assert other.energy_mj != base.energy_mj
    app = load_app(CONFIG_DIR)
    assert not [k for k in unresolved_keys(app, "config/app.yaml") if ".radar." in f".{k.key}"]


def test_savgol_weights_and_confidence_half_life() -> None:
    smooth = savgol_coefficients(5, 2, 0, 0.1)
    np.testing.assert_allclose(smooth, np.array([-3, 12, 17, 12, -3]) / 35.0)
    slope = savgol_coefficients(5, 2, 1, 0.1)
    assert slope @ (2.0 * np.arange(-2, 3) * 0.1) == pytest.approx(2.0)  # d/dt of 2t
    cfg = load_app(CONFIG_DIR).radar
    radar = RadarEstimator("X", cfg, [], 5807.0, 4.0)
    radar.bank.fits[0, 1] = (1.0, 0.8, cfg.fit_min_samples)  # a Straight Mode CdA fit
    t1, t2 = cfg.missing_window_s, cfg.missing_window_s + cfg.confidence_half_life_s
    window = np.arange(0.0, cfg.missing_window_s, 0.25)
    radar.bank.frame_t[0, : 2 * window.size] = np.concatenate((t1 - window, t2 - window))
    assert radar.confidence(t1) == 0.0  # no frame, no anchor yet: unknown
    radar.bank.state[0, _ANCHOR_T] = 0.0  # anchored at the start
    radar.bank.state[0, _WEIGHT] = 1.0
    full, half = radar.confidence(t1), radar.confidence(t2)
    assert full == pytest.approx(0.5 ** (t1 / cfg.confidence_half_life_s))
    assert half / full == pytest.approx(0.5)


def test_compiled_radar_matches_the_python_reference(radar_race) -> None:  # type: ignore[no-untyped-def]
    from pitwall_sim.observe.radar.reference import ReferenceRadarEstimator

    engine, _, _ = radar_race
    args = (engine.app.radar, _zones(engine), engine.trk.length_m, engine.app.feed.rate_hz)
    for driver in ("VER", "HAM", "ALO"):
        frames = engine.feed.frames(driver)
        compiled, reference = RadarEstimator(driver, *args), ReferenceRadarEstimator(driver, *args)
        for k in range(0, len(frames), 9):
            a = compiled.update(frames[k : k + 9])
            b = reference.update(frames[k : k + 9])
            assert a.t_s == pytest.approx(b.t_s, abs=1e-9)
            assert a.energy_mj == pytest.approx(b.energy_mj, abs=1e-6)
            assert a.state == b.state
            assert a.confidence == pytest.approx(b.confidence, abs=1e-9)
            assert (a.last_clip_s_m is None) == (b.last_clip_s_m is None)


def test_engine_radar_equals_a_standalone_estimator() -> None:
    """The engine's batched Radar sees exactly the published feed frames, in order."""
    engine = RaceEngine(RaceSetup(laps=1, fuel_kg=20.0), CONFIG_DIR)
    while engine.t < 100.0:  # inside the feed window: every frame is still kept
        engine.tick()
    args = (engine.app.radar, _zones(engine), engine.trk.length_m, engine.app.feed.rate_hz)
    for i, driver in enumerate(engine.driver_ids[:6]):
        alone = RadarEstimator(driver, *args).update(engine.feed.frames(driver))
        from_engine = engine.radar_estimate(i)
        assert from_engine.t_s == pytest.approx(alone.t_s)
        assert from_engine.energy_mj == pytest.approx(alone.energy_mj, abs=1e-9)
        assert from_engine.state == alone.state
        assert from_engine.confidence == pytest.approx(alone.confidence)


def test_rival_strategy_does_not_read_the_start_prior() -> None:
    """Sprint day 5: the start prior is for the pit wall; Rivals see unanchored cars as level."""
    engine = RaceEngine(RaceSetup(laps=1, fuel_kg=50.0), CONFIG_DIR)
    for _ in range(4 * 30):  # 30 s: CdA fits, no anchors yet
        engine.tick()
    engine._sync_radar()
    _, with_prior = engine.radar.energies()
    _, rival_view = engine.radar.energies(with_prior=False)
    on_prior = engine.radar.state[:, _WEIGHT] < 1.0
    assert on_prior.any() and (with_prior[on_prior] > 0.0).any()
    assert (rival_view[on_prior] == 0.0).all()
    assert np.array_equal(rival_view[~on_prior], with_prior[~on_prior])
