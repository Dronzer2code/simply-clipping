"""T-034: overtake model (TRD OVERTAKE MODEL, PF-11) and the RNG streams it uses.

Coefficients come from config at test time.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.compare import rule_set_for_date
from pitwall_sim.config.loader import load_app, load_team_performance, load_track, load_tyres
from pitwall_sim.config.models import Compound
from pitwall_sim.race import step_kernel as K
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.overtake import (
    PLACEHOLDER_KEYS,
    OvertakeModel,
    TriggerPoint,
    crossed,
    p_pass,
    trigger_points,
)
from pitwall_sim.race.snapshot import RNG_STREAMS, make_rngs
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def app():  # type: ignore[no-untyped-def]
    return load_app(CONFIG_DIR)


@pytest.fixture(scope="module")
def short_race() -> RaceEngine:
    engine = RaceEngine(RaceSetup(laps=3), CONFIG_DIR)
    engine.run()
    return engine


# --------------------------------------------------------------------------- #
# Acceptance: p_pass rises with dv; overtakes occur; placeholders flagged
# --------------------------------------------------------------------------- #


def test_p_pass_rises_with_speed_difference(app) -> None:  # type: ignore[no-untyped-def]
    cfg = app.overtake
    ps = [
        p_pass(cfg, dv, 0.0, False, 0.0, False, cfg.braking_zone_difficulty)
        for dv in range(-10, 21, 2)
    ]
    assert all(b > a for a, b in zip(ps, ps[1:], strict=False))
    assert 0.0 < ps[0] < ps[-1] < 1.0


def test_p_pass_follows_each_factor(app) -> None:  # type: ignore[no-untyped-def]
    cfg = app.overtake
    base = p_pass(cfg, 2.0, 0.0, False, 0.0, False, 2.0)
    assert p_pass(cfg, 2.0, 0.05, False, 0.0, False, 2.0) > base  # better grip
    assert p_pass(cfg, 2.0, 0.0, True, 0.0, False, 2.0) > base  # Overtake mode
    assert p_pass(cfg, 2.0, 0.0, False, 0.3, False, 2.0) > base  # racecraft
    assert p_pass(cfg, 2.0, 0.0, False, 0.0, True, 2.0) < base  # DEFEND
    assert p_pass(cfg, 2.0, 0.0, False, 0.0, False, 3.0) < base  # harder zone


def test_overtakes_occur_in_a_race(short_race: RaceEngine) -> None:
    events = short_race.overtake.events
    passes = [e for e in events if e.success and not e.blue_flag]
    assert passes
    assert all(0.0 < e.p_pass < 1.0 for e in events if not e.blue_flag)
    assert any(not e.success for e in events)
    finish = short_race.result().classification
    assert finish != list(short_race.driver_ids)  # the order changed on the road


def test_placeholder_weights_are_flagged_in_config() -> None:
    text = (CONFIG_DIR / "app.yaml").read_text(encoding="utf-8")
    section = text.split("\novertake:\n", 1)[1].split("\n\n", 1)[0]
    for key in PLACEHOLDER_KEYS:
        line = re.search(rf"^\s+{key}:.*$", section, re.MULTILINE)
        assert line is not None, key
        # Sprint day 4: some are gameplay-tuned, to be recalibrated in T-02C.
        text_ = line.group(0)
        assert "PLACEHOLDER: calibrate" in text_ or (
            "GAMEPLAY-TUNED" in text_ and "recalibrate in T-02C" in text_
        ), key


# --------------------------------------------------------------------------- #
# Kernel: no passing without an overtake
# --------------------------------------------------------------------------- #


def test_a_faster_car_cannot_drive_through_the_car_ahead(app) -> None:  # type: ignore[no-untyped-def]
    track = load_track("suzuka", CONFIG_DIR)
    perf, tyres = load_team_performance(CONFIG_DIR), load_tyres(CONFIG_DIR)
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    rules = rule_set_for_date(date(2026, 3, 29), CONFIG_DIR)
    trk = K.kernel_track(model, track)
    glb = K.kernel_globals(rules, app, track, tyres, "mercedes", perf)
    cars = K.kernel_cars(["mercedes"] * 2, [Compound.MEDIUM] * 2, rules, app, perf, tyres, 8.5)
    st = K.initial_state(2, [130.0, 100.0], [50.0, 50.0], [2e6] * 2, [40.0] * 2)
    v_ref = np.stack([np.full(model.s_m.size, 50.0), np.full(model.s_m.size, 80.0)])
    ctl = K.default_controls(2)
    t = 0.0
    gaps = []
    for _ in range(100):
        t = K.advance(5, app.sim.dt_s, t, K.flat_plans(v_ref), trk, glb, cars, ctl, st)
        gaps.append(st.s_m[0] - st.s_m[1])
    # It closes up to the follow gap and stays behind (dirty air opens it in corners).
    assert min(gaps) == pytest.approx(app.overtake.follow_gap_m, abs=1.0)
    assert min(gaps) > 0.0


# --------------------------------------------------------------------------- #
# Trigger points, crossings, swaps
# --------------------------------------------------------------------------- #


def test_trigger_points_cover_overtaking_and_braking_zones(app, short_race: RaceEngine) -> None:  # type: ignore[no-untyped-def]
    cfg = app.overtake
    plan = short_race.car_plans[0]
    points = trigger_points(short_race.track, cfg, short_race.model.s_m, plan.v_ref)
    ot = [p for p in points if p.zone_id == "OT1"]
    assert len(ot) == 1 and ot[0].difficulty == cfg.zone_difficulty_default  # UNKNOWN in config
    braking = [p for p in points if p.zone_id is None]
    assert braking and all(p.difficulty == cfg.braking_zone_difficulty for p in braking)
    assert [p.s_m for p in points] == sorted(p.s_m for p in points)


def test_crossed_is_wrap_aware() -> None:
    assert crossed(100.0, 120.0, 110.0) and not crossed(100.0, 120.0, 130.0)
    assert crossed(5800.0, 10.0, 5.0) and crossed(5800.0, 10.0, 5805.0)
    assert not crossed(5800.0, 10.0, 100.0)


def test_swap_exchanges_cars_and_keeps_timing_in_step(app, short_race: RaceEngine) -> None:  # type: ignore[no-untyped-def]
    trk = short_race.trk
    st = K.initial_state(
        3, [1000.0, 1015.0, 3000.0], [60.0, 50.0, 70.0], [2e6] * 3, [40.0] * 3, trk.loops_m
    )
    model = OvertakeModel(
        app.overtake, [TriggerPoint(1010.0, 2.0, None)], trk, make_rngs(1)["overtake"], np.zeros(3)
    )
    assert model._swap(0, 1, st, t_s=12.0)
    assert st.s_m[0] == 1015.0 and st.s_m[1] == 1000.0
    assert st.v_ms[0] == 50.0 and st.v_ms[1] == 60.0
    for i in range(3):
        assert st.next_loop[i] == np.searchsorted(trk.loops_m, st.s_m[i], side="right")
    model._set_back(0, st, metres=50.0)
    assert st.s_m[0] == pytest.approx(1000.0 + app.overtake.follow_gap_m)  # not past car 1


def test_same_seed_same_overtakes() -> None:
    first = RaceEngine(RaceSetup(laps=2, seed=7), CONFIG_DIR)
    second = RaceEngine(RaceSetup(laps=2, seed=7), CONFIG_DIR)
    other = RaceEngine(RaceSetup(laps=2, seed=8), CONFIG_DIR)
    for engine in (first, second, other):
        engine.run()
    assert first.overtake.events == second.overtake.events
    assert first.overtake.events != other.overtake.events


def test_named_rng_streams_are_independent_and_seeded() -> None:
    a, b = make_rngs(42), make_rngs(42)
    assert tuple(a) == RNG_STREAMS
    assert {name: a[name].random() for name in a} == {name: b[name].random() for name in b}
    draws = {make_rngs(42)[name].random() for name in RNG_STREAMS}
    assert len(draws) == len(RNG_STREAMS)


def test_hold_position_makes_no_attempt_but_blue_flags_still_pass(  # type: ignore[no-untyped-def]
    app, short_race: RaceEngine
) -> None:
    """Owner, sprint day 5 follow-up: HOLD_POSITION means no overtake attempts (TRD)."""
    trk = short_race.trk
    point = TriggerPoint(1010.0, 0.0, None)
    st = K.initial_state(2, [1012.0, 1015.0], [80.0, 50.0], [2e6] * 2, [40.0] * 2, trk.loops_m)
    model = OvertakeModel(app.overtake, [point], trk, make_rngs(1)["overtake"], np.zeros(2))
    mu, ctl, defending = np.ones(2), K.default_controls(2), np.zeros(2, dtype=np.bool_)
    assert model._attempt(0.0, 0, 1, point, mu, ctl, st, defending, hold=True) is None
    assert st.s_m[0] == 1012.0  # nothing happened: no swap, no set-back
    assert model._attempt(0.0, 0, 1, point, mu, ctl, st, defending) is not None
    lapping = K.initial_state(2, [1012.0, 1015.0], [80.0, 50.0], [2e6] * 2, [40.0] * 2, trk.loops_m)
    lapping.lap[0] = 1  # a lap ahead: the blue flag lets it by
    event = model._attempt(0.0, 0, 1, point, mu, ctl, lapping, defending, hold=True)
    assert event is not None and event.blue_flag


def test_engine_passes_hold_position_to_the_overtake_stage(
    short_race: RaceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []
    monkeypatch.setattr(short_race.overtake, "resolve", lambda *args: seen.append(args) or [])
    short_race._overtake()
    holding = seen[0][-1]
    assert not holding.any()  # no Our Car here: the Rival Strategy's hold is not passed on
    hold = short_race._instruction_arrays.hold_position
    hold[:] = True
    seen.clear()
    short_race._overtake()
    assert not seen[0][-1].any()
    hold[:] = False
