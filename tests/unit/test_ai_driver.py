"""T-031: AI Driver (speed tracking, Energy Modes, lines, attack / defend).

Coefficients are loaded from config at test time (owner round 12). Laps are
driven by the step kernel (T-030) from the driver's plans.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.compare import rule_set_for_date
from pitwall_sim.car.speed_profile import reference_params
from pitwall_sim.config.loader import load_app, load_team_performance, load_track, load_tyres
from pitwall_sim.config.models import Compound, EnergyMode
from pitwall_sim.driver import ai_driver as D
from pitwall_sim.race import step_kernel as K
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
TEAM = "mercedes"
RACE_LIMIT_MJ = 8.5
FUEL_KG = 40.0
BATTERY_START_J = 2.0e6
MODES = (EnergyMode.PUSH, EnergyMode.BALANCED, EnergyMode.HARVEST)


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    app = load_app(CONFIG_DIR)
    track = load_track("suzuka", CONFIG_DIR)
    perf = load_team_performance(CONFIG_DIR)
    tyres = load_tyres(CONFIG_DIR)
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    rules = rule_set_for_date(date(2026, 3, 29), CONFIG_DIR)
    trk = K.kernel_track(model, track)
    glb = K.kernel_globals(rules, app, track, tyres, TEAM, perf)
    cars = K.kernel_cars([TEAM], [Compound.MEDIUM], rules, app, perf, tyres, RACE_LIMIT_MJ)
    prof = reference_params(rules, perf.teams[TEAM], tyres, Compound.MEDIUM, app, track, FUEL_KG)
    predictor = D.LapPredictor.for_car(app.sim.dt_s, trk, glb, cars, 0)
    return app, track, model, predictor, prof


def _plan(
    world, instructions: D.DriverInstructions, battery_j: float = BATTERY_START_J, balance=None
) -> D.CarPlan:  # type: ignore[no-untyped-def]
    app, track, model, predictor, prof = world
    return D.plan_lap(
        predictor, model.s_m, track, prof, instructions, app.ai_driver, battery_j, FUEL_KG,
        balance=balance,
    )  # fmt: skip


def _shape(world, instructions: D.DriverInstructions, level: float = D.MAX_LEVEL) -> D.CarPlan:  # type: ignore[no-untyped-def]
    app, track, model, predictor, prof = world
    return D.shape_plan(predictor.trk, model.s_m, track, prof, instructions, app.ai_driver, level)


def _lap(world, plan: D.CarPlan, battery_j: float = BATTERY_START_J) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    """Drive one flying lap in the kernel; return (lap time s, battery change J)."""
    lap_s, end_j = world[3].lap(plan, battery_j, FUEL_KG)
    return lap_s, end_j - battery_j


# --------------------------------------------------------------------------- #
# Acceptance: PUSH faster than BALANCED faster than HARVEST; HARVEST gains battery
# --------------------------------------------------------------------------- #


def test_energy_modes_order_lap_times_and_harvest_gains_battery(world) -> None:  # type: ignore[no-untyped-def]
    laps = {mode: _lap(world, _plan(world, D.DriverInstructions(mode=mode))) for mode in MODES}
    push, balanced, harvest = (laps[m] for m in MODES)
    assert push[0] < balanced[0] < harvest[0]
    assert harvest[1] > 0.0
    assert push[1] < balanced[1] < harvest[1]


def test_energy_modes_meet_their_battery_targets(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    tolerance_j = 0.05e6
    for mode in MODES:
        plan = _plan(world, D.DriverInstructions(mode=mode))
        _, change = _lap(world, plan)
        target = D.lap_target_change_j(mode, BATTERY_START_J, cfg)
        assert 0.0 < plan.deploy_level < D.MAX_LEVEL, mode
        assert change == pytest.approx(target, abs=tolerance_j), mode


def test_deploy_level_fills_acceleration_zones_first(world) -> None:  # type: ignore[no-untyped-def]
    accel = world[3].trk.accel_zone
    half = D.deploy_fractions(0.5, accel, yield_straights=False)
    assert (half[accel] == 0.5).all() and (half[~accel] == 0.0).all()
    most = D.deploy_fractions(1.5, accel, yield_straights=False)
    assert (most[accel] == 1.0).all() and (most[~accel] == 0.5).all()
    yielding = D.deploy_fractions(2.0, accel, yield_straights=True)
    assert (yielding[accel] == 0.0).all() and (yielding[~accel] == 1.0).all()


def test_energy_balance_corrects_a_steady_loss(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    balance = D.EnergyBalance(cfg.energy_feedback_gain)
    loss_j = 0.4e6  # e.g. boost and Overtake spent on top of the plan every lap
    battery = BATTERY_START_J
    changes = []
    for _ in range(5):
        plan = _plan(world, D.DriverInstructions(), battery, balance)
        _, change = _lap(world, plan, battery)
        change -= loss_j
        battery += change
        changes.append(change)
        balance.update(change, 0.0)
    assert abs(changes[-1]) < 0.5 * abs(changes[0])


def test_lift_and_coast_is_slower_but_saves_energy(world) -> None:  # type: ignore[no-untyped-def]
    flat = _lap(world, _shape(world, D.DriverInstructions(), level=1.0))
    lift_plan = _shape(world, D.DriverInstructions(lift_coast=True), level=1.0)
    lift = _lap(world, lift_plan)
    assert (lift_plan.throttle_cap == 0.0).any()
    assert lift[0] > flat[0]
    assert lift[1] > flat[1]


def test_grip_margin_orders_reference_lap_times(world) -> None:  # type: ignore[no-untyped-def]
    push_lap = _shape(world, D.DriverInstructions(push_lap=True)).lap_time_s
    normal = _shape(world, D.DriverInstructions()).lap_time_s
    manage = _shape(world, D.DriverInstructions(manage_tyres=True)).lap_time_s
    assert push_lap < normal < manage


def test_harvest_plan_clips_only_at_acceleration_zone_ends(world) -> None:  # type: ignore[no-untyped-def]
    app, *_ = world
    trk = world[3].trk
    harvest = _shape(world, D.DriverInstructions(mode=EnergyMode.HARVEST))
    push = _shape(world, D.DriverInstructions(mode=EnergyMode.PUSH))
    assert harvest.superclip.any()
    assert not push.superclip.any()
    assert trk.accel_zone[harvest.superclip].all()
    n_zones = int(np.count_nonzero(trk.accel_zone & ~np.roll(trk.accel_zone, 1)))
    clip_m = harvest.superclip.sum() * trk.ds_m
    assert clip_m == pytest.approx(n_zones * app.ai_driver.superclip_zone_m, abs=n_zones * trk.ds_m)


def test_mgmt_factor_follows_instructions(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    assert D.mgmt_factor(D.DriverInstructions(push_lap=True), cfg) == cfg.push_lap_mgmt_factor
    manage = D.DriverInstructions(manage_tyres=True)
    assert D.mgmt_factor(manage, cfg) == cfg.manage_tyres_mgmt_factor
    assert D.mgmt_factor(D.DriverInstructions(), cfg) == 1.0


# --------------------------------------------------------------------------- #
# Kernel: part-throttle / coasting harvest (TRD Battery)
# --------------------------------------------------------------------------- #


def test_coasting_harvest_charges_and_slows_the_car(world) -> None:  # type: ignore[no-untyped-def]
    app, *_ = world
    pred = world[3]
    results = []
    for harvest in (False, True):
        st = K.initial_state(1, [500.0], [70.0], [1e6], [FUEL_KG])
        ctl = K.default_controls(1)
        ctl.part_harvest[0] = harvest
        for _ in range(20):
            K.step(app.sim.dt_s, pred.trk, pred.glb, pred.car, ctl, st)
        results.append((st.v_ms[0], st.battery_j[0], st.harvest_lap_j[0]))
    (v_off, b_off, h_off), (v_on, b_on, h_on) = results
    assert h_off == 0.0 and b_off == 1e6
    expected = min(pred.car.partial_harvest_max_w[0], pred.glb.harvest_max_w) * 20 * app.sim.dt_s
    assert h_on == pytest.approx(expected)
    assert b_on == pytest.approx(1e6 + expected)
    assert v_on < v_off


# --------------------------------------------------------------------------- #
# Decision tick: lines, Overtake, boost (owner round 7)
# --------------------------------------------------------------------------- #


def _sit(**kw: object) -> D.Situation:
    base: dict[str, object] = {"battery_j": 2e6, "in_acceleration_zone": True}
    base.update(kw)
    return D.Situation(**base)  # type: ignore[arg-type]


def test_boost_rules_by_mode(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    push = D.DriverInstructions(mode=EnergyMode.PUSH)
    balanced = D.DriverInstructions(mode=EnergyMode.BALANCED)
    harvest = D.DriverInstructions(mode=EnergyMode.HARVEST)
    assert D.decide(_sit(), push, cfg).boost_active
    assert not D.decide(_sit(in_acceleration_zone=False), push, cfg).boost_active
    assert not D.decide(_sit(), balanced, cfg).boost_active
    assert D.decide(_sit(gap_ahead_s=0.5), balanced, cfg).boost_active
    assert D.decide(_sit(gap_behind_s=0.5), balanced, cfg).boost_active
    assert not D.decide(_sit(gap_ahead_s=0.5), harvest, cfg).boost_active
    low = cfg.boost_reserve_mj * 1e6 * 0.5
    assert not D.decide(_sit(battery_j=low), push, cfg).boost_active


def test_attack_and_defend_force_boost_and_lines(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    attack = D.DriverInstructions(mode=EnergyMode.HARVEST, attack=True)
    defend = D.DriverInstructions(mode=EnergyMode.HARVEST, defend=True)
    assert D.decide(_sit(), attack, cfg).boost_active
    assert D.decide(_sit(), defend, cfg).boost_active
    decision = D.decide(_sit(gap_ahead_s=0.4, overtake_available=True), attack, cfg)
    assert decision.line == D.OVERTAKE_LINE
    assert decision.overtake_active
    assert D.decide(_sit(gap_behind_s=0.4), defend, cfg).line == D.DEFEND_LINE
    assert D.decide(_sit(), defend, cfg).line == D.DEFEND_LINE  # inside line all the way
    assert D.decide(_sit(), D.DriverInstructions(), cfg).line == D.RACING_LINE


def test_attack_uses_all_the_grip_and_defend_keeps_deploy_for_the_straights(world) -> None:  # type: ignore[no-untyped-def]
    normal = _shape(world, D.DriverInstructions(), level=1.5)
    attack = _shape(world, D.DriverInstructions(attack=True, follow_close=True), level=1.5)
    push_lap = _shape(world, D.DriverInstructions(push_lap=True), level=1.5)
    assert attack.lap_time_s == push_lap.lap_time_s < normal.lap_time_s
    defend = _shape(world, D.DriverInstructions(defend=True, keep_deploy=True), level=1.5)
    accel = world[3].trk.accel_zone
    assert (normal.deploy[~accel] > 0.0).any() and (defend.deploy[~accel] == 0.0).all()
    assert np.array_equal(defend.deploy[accel], normal.deploy[accel])
    assert (defend.with_level(2.0).deploy[~accel] == 0.0).all()  # kept through relevels
    # The Rival Strategy AI's own attack / defend flags do not change the plan.
    rival = _shape(world, D.DriverInstructions(attack=True, defend=True), level=1.5)
    assert rival.lap_time_s == normal.lap_time_s and np.array_equal(rival.deploy, normal.deploy)


def test_hold_position_and_team_orders_never_attack(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    close = _sit(gap_ahead_s=0.3, overtake_available=True)
    hold = D.DriverInstructions(mode=EnergyMode.PUSH, attack=True, hold_position=True)
    decision = D.decide(close, hold, cfg)
    assert decision.line != D.OVERTAKE_LINE
    assert not decision.overtake_active
    let_by = D.decide(close, D.DriverInstructions(mode=EnergyMode.PUSH, let_teammate_by=True), cfg)
    assert not let_by.boost_active
    assert not let_by.overtake_active
    assert let_by.line == D.DEFEND_LINE
    no_ot = D.DriverInstructions(attack=True, overtake_permitted=False)
    assert not D.decide(close, no_ot, cfg).overtake_active


def test_vectorised_decisions_match_decide(world) -> None:  # type: ignore[no-untyped-def]
    cfg = world[0].ai_driver
    rng = np.random.default_rng(42)
    n = 400
    instructions = [
        D.DriverInstructions(
            mode=list(EnergyMode)[int(rng.integers(3))],
            attack=bool(rng.random() < 0.3),
            defend=bool(rng.random() < 0.3),
            hold_position=bool(rng.random() < 0.2),
            let_teammate_by=bool(rng.random() < 0.1),
            push_lap=bool(rng.random() < 0.2),
            overtake_permitted=bool(rng.random() < 0.8),
        )
        for _ in range(n)
    ]
    battery = rng.uniform(0.0, 1e6, n)
    accel = rng.random(n) < 0.5
    ahead = rng.uniform(0.0, 2.0, n)
    behind = rng.uniform(0.0, 2.0, n)
    available = rng.random(n) < 0.5
    ins = D.instruction_arrays(instructions, cfg)
    line, overtake, boost = D.decide_all(battery, accel, ahead, behind, available, ins, cfg)
    for i in range(n):
        sit = D.Situation(battery[i], bool(accel[i]), ahead[i], behind[i], bool(available[i]))
        one = D.decide(sit, instructions[i], cfg)
        assert (line[i], overtake[i], boost[i]) == (one.line, one.overtake_active, one.boost_active)
        assert ins.mgmt_factor[i] == D.mgmt_factor(instructions[i], cfg)
