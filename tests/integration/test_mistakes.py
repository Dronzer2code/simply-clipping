"""T-037: AI Driver mistakes (TRD AI DRIVER; HR-04 stream ``mistakes``)."""

from __future__ import annotations

import collections
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app
from pitwall_sim.config.models import EnergyMode, MistakesConfig
from pitwall_sim.driver import ai_driver as D
from pitwall_sim.race.engine import RaceEngine, RaceSetup

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def cfg() -> MistakesConfig:
    return load_app(CONFIG_DIR).mistakes


def test_rate_scales_with_wear_wetness_and_consistency(cfg: MistakesConfig) -> None:
    def p(skill: float, wear: float, wet: float) -> float:
        return D.mistake_probability(cfg, skill, wear, wet)

    assert p(1.0, 0.0, 0.0) == pytest.approx(cfg.base_p_per_corner)
    assert p(1.0, 0.8, 0.0) > p(1.0, 0.2, 0.0) > p(1.0, 0.0, 0.0)  # tyre wear
    assert p(1.0, 0.0, 1.0) > p(1.0, 0.0, 0.5) > p(1.0, 0.0, 0.0)  # wetness
    assert p(0.0, 0.0, 0.0) > p(0.5, 0.0, 0.0) > p(1.0, 0.0, 0.0)  # skill_consistency
    huge = cfg.model_copy(update={"base_p_per_corner": 0.9})
    assert D.mistake_probability(huge, 0.0, 1.0, 1.0) == 1.0


def test_outcomes_follow_the_shares(cfg: MistakesConfig) -> None:
    rng = np.random.default_rng(42)
    kinds = collections.Counter(D.draw_mistake(cfg, 1.0, rng) for _ in range(20000))
    for kind, share in cfg.kind_shares.items():
        assert kinds[kind] / 20000 == pytest.approx(share, abs=0.015)
    assert all(D.draw_mistake(cfg, 0.0, rng) is None for _ in range(100))


def _engine(base_p: float, seed: int = 42) -> RaceEngine:
    engine = RaceEngine(RaceSetup(laps=3, seed=seed), CONFIG_DIR)
    mistakes = engine.app.mistakes.model_copy(update={"base_p_per_corner": base_p})
    engine.app = engine.app.model_copy(update={"mistakes": mistakes})
    return engine


def test_mistakes_in_a_race_use_only_their_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(0.05)
    streams = []
    draw = D.draw_mistake

    def spy(cfg: MistakesConfig, p: float, rng: np.random.Generator) -> object:
        streams.append(rng)
        return draw(cfg, p, rng)

    monkeypatch.setattr(D, "draw_mistake", spy)
    result = engine.run()
    assert streams and all(rng is engine.rngs["mistakes"] for rng in streams)
    kinds = {m.kind for m in engine.mistakes}
    assert {"LOCK_UP", "OFF_TRACK"} <= kinds
    corners = {c.corner_id for c in engine.track.corners}
    assert all(m.corner_id in corners for m in engine.mistakes)
    for m in engine.mistakes:
        if m.kind == "CRASH":
            assert result.retired[engine.driver_ids[m.car]].startswith("crash at")
    assert result.finished  # spun cars drive on; crashed cars are classified DNF


def test_mistakes_are_deterministic_and_change_the_race() -> None:
    a, b, clean = _engine(0.05), _engine(0.05), _engine(0.0)
    ra, rb, rc = a.run(), b.run(), clean.run()
    assert a.mistakes == b.mistakes and ra.finish_time_s == rb.finish_time_s
    assert not clean.mistakes and ra.finish_time_s != rc.finish_time_s


def test_a_stopped_car_pulls_away_from_a_lift_point() -> None:
    """A spin leaves the car at 0 m/s; the plan's lift and coast must not hold it there."""
    engine = RaceEngine(RaceSetup(laps=3, our_driver_id="VER"), CONFIG_DIR)
    i = engine.driver_ids.index("VER")  # Our Car: the Rival AI leaves its instructions alone
    engine.set_instructions(
        i, replace(engine.instructions[i], mode=EnergyMode.HARVEST, lift_coast=True)
    )
    n_pts = engine.plans.throttle_cap.shape[1]

    def cap_here(e: RaceEngine) -> float:
        k = int(e.st.s_m[i] / e.trk.ds_m) % n_pts
        return float(e.plans.throttle_cap[i, k])

    for _ in range(2000):
        engine.tick()
        if cap_here(engine) == 0.0:
            break
    assert cap_here(engine) == 0.0
    engine.st.v_ms[i] = 0.0
    snap = engine.snapshot()
    speeds = []
    for share in (engine.glb.lift_min_speed_share, 0.0):  # 0.0: lift at any speed (old kernel)
        fork = RaceEngine.from_snapshot(snap)
        fork.glb = fork.glb._replace(lift_min_speed_share=share)
        for _ in range(8):
            fork.tick()
        speeds.append(float(fork.st.v_ms[i]))
    assert speeds[0] > 10.0 > speeds[1]
