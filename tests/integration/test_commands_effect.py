"""T-061 / MVP-09: every R1 Engineer Command changes Our Car (``test_each_command_effect``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall_sim.config.models import Compound, EnergyMode
from pitwall_sim.engineer.commands import CommandType, EngineerCommand, make_command
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.overtake import OvertakeEvent
from pitwall_sim.race.pit import PitPhase
from pitwall_sim.track.zones import zone_ids_mask

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
OUR = "RUS"
T = CommandType


def _engine(laps: int = 6) -> RaceEngine:
    engine = RaceEngine(RaceSetup(laps=laps, our_driver_id=OUR), CONFIG_DIR)
    for _ in range(4 * 60):  # one minute in: the field has spread out
        engine.tick()
    return engine


def _issue(engine: RaceEngine, kind: CommandType, params: dict[str, Any]) -> None:
    """Validate against public facts, queue with the radio latency, run until applied."""
    cmd = make_command(
        kind, params, engine.command_context(), engine.app.engineer, engine.t,
        engine.app.radio.radio_latency_s,
    )  # fmt: skip
    assert isinstance(cmd, EngineerCommand), cmd
    engine.submit(cmd)
    while cmd not in engine.applied_commands:
        engine.tick()


def _run_laps(engine: RaceEngine, laps: int) -> None:
    i = engine.our_index
    assert i is not None
    end = int(engine.st.lap[i]) + laps
    while engine.st.lap[i] < end and not engine.finished:
        engine.tick()


def _fork(engine: RaceEngine) -> RaceEngine:
    return RaceEngine.from_snapshot(engine.snapshot())


@pytest.fixture
def engine() -> RaceEngine:
    return _engine()


def test_set_energy_mode(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    base = _fork(engine)
    _issue(engine, T.SET_ENERGY_MODE, {"mode": "HARVEST"})
    _issue(base, T.SET_ENERGY_MODE, {"mode": "PUSH"})
    assert engine.instructions[i].mode == EnergyMode.HARVEST
    _run_laps(engine, 2)
    _run_laps(base, 2)
    assert engine.st.battery_j[i] > base.st.battery_j[i] + 0.2e6  # battery near full: capped


def test_set_overtake_permission(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    lap = int(engine.st.lap[i]) + 2
    _issue(engine, T.SET_OVERTAKE_PERMISSION, {"allowed": False, "lap": lap})
    assert engine.instructions[i].overtake_permitted  # only on that lap
    seen = set()
    while int(engine.st.lap[i]) + 1 <= lap + 1 and not engine.finished:
        engine.tick()
        if engine.steps % engine.decision_steps == 0:
            seen.add((int(engine.st.lap[i]) + 1, engine.instructions[i].overtake_permitted))
            if int(engine.st.lap[i]) + 1 == lap:
                assert not engine.ctl.overtake_active[i]
    assert (lap, False) in seen and (lap + 1, True) in seen
    _issue(engine, T.SET_OVERTAKE_PERMISSION, {"allowed": False})
    engine.tick()
    assert not engine.instructions[i].overtake_permitted


def test_set_lift_coast(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    assert (engine.plans.throttle_cap[i] == 1.0).all()  # BALANCED: no lift
    _issue(engine, T.SET_LIFT_COAST, {"enabled": True, "zone_ids": ["SM1"]})
    lift = engine.plans.throttle_cap[i] < 1.0
    sm1 = zone_ids_mask(engine.track, engine.model.s_m, ["SM1"])
    assert lift.any() and not (lift & ~sm1).any()
    _issue(engine, T.SET_LIFT_COAST, {"enabled": True})
    everywhere = engine.plans.throttle_cap[i] < 1.0
    assert (everywhere & ~sm1).any()
    _issue(engine, T.SET_LIFT_COAST, {"enabled": False})
    assert (engine.plans.throttle_cap[i] == 1.0).all()


def test_box_on_a_later_lap(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    lap = int(engine.st.lap[i]) + 2
    _issue(engine, T.BOX, {"lap": lap, "compound": "HARD"})
    while int(engine.st.lap[i]) + 1 < lap:
        assert engine.pit.phase[i] == PitPhase.RUNNING
        engine.tick()
    stopped = False
    while not engine.finished and int(engine.st.lap[i]) + 1 <= lap + 1:
        engine.tick()
        stopped |= engine.pit.phase[i] == PitPhase.STATIONARY
    assert stopped and engine.compounds[i] == Compound.HARD


def test_cancel_box(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    _issue(engine, T.BOX, {"lap": int(engine.st.lap[i]) + 1, "compound": "SOFT"})
    if engine.pit.in_lane(i):  # just past the entry: wait for the next lap's call
        pytest.skip("box landed in the lane")
    assert engine.pit.phase[i] == PitPhase.BOX_PENDING
    _issue(engine, T.CANCEL_BOX, {})
    assert engine.pit.phase[i] == PitPhase.RUNNING
    _run_laps(engine, 1)
    assert not any(e.car == i and e.phase == PitPhase.STATIONARY for e in engine.pit.events)


def _put_behind(engine: RaceEngine, i: int, j: int, metres: float) -> None:
    """Place car ``j`` ``metres`` behind car ``i`` on the same lap (public order follows)."""
    st = engine.st
    st.lap[j], st.s_m[j] = st.lap[i], st.s_m[i] - metres
    if st.s_m[j] < 0.0:
        st.lap[j] -= 1
        st.s_m[j] += engine.trk.length_m
    engine._classify()


def test_defend_lasts_until_the_threat_clears(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    _issue(engine, T.DEFEND, {"corner_id": engine.track.corners[0].corner_id})
    assert engine.instructions[i].defend and engine._instruction_arrays.defend[i]
    j = (i + 1) % engine.n
    engine._defend_threat[i] = j
    gap_m = engine.app.engineer.defend_clear_gap_s * float(engine.st.v_ms[j])
    _put_behind(engine, i, j, 0.5 * gap_m)  # still close: keep defending, corner or not
    engine._command_upkeep()
    assert engine.instructions[i].defend
    _put_behind(engine, i, j, 1.5 * gap_m)  # more than 1.0 s back: the threat has cleared
    engine._command_upkeep()
    assert not engine.instructions[i].defend
    _issue(engine, T.DEFEND, {})
    engine._defend_threat[i] = j
    _put_behind(engine, i, j, -10.0)  # it got past
    engine._command_upkeep()
    assert not engine.instructions[i].defend


def test_defend_lasts_at_most_two_laps(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    _issue(engine, T.DEFEND, {})
    assert engine._defend_until[i] == engine.st.lap[i] + engine.app.engineer.call_max_laps
    j = (i + 1) % engine.n
    engine._defend_threat[i] = j
    _put_behind(engine, i, j, 5.0)
    engine.st.lap[[i, j]] += engine.app.engineer.call_max_laps
    engine._command_upkeep()
    assert not engine.instructions[i].defend


def test_attack_and_hold_position(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    v_ref = engine.plans.v_ref[i].copy()
    _issue(engine, T.ATTACK, {})
    ins = engine.instructions[i]
    assert ins.attack and not ins.hold_position and ins.mode == EnergyMode.PUSH  # drives in PUSH
    assert engine.plans.v_ref[i].mean() > v_ref.mean()  # all the grip: stays in the tow
    _issue(engine, T.HOLD_POSITION, {})
    ins = engine.instructions[i]
    assert ins.hold_position and not ins.attack and engine._instruction_arrays.hold_position[i]
    assert ins.mode == EnergyMode.BALANCED  # back to the mode before the ATTACK


def test_attack_runs_out_after_two_laps(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    _issue(engine, T.ATTACK, {})
    _run_laps(engine, engine.app.engineer.call_max_laps - 1)
    assert engine.instructions[i].attack or not engine._attack_mode  # unless it passed already
    _run_laps(engine, 1)
    engine.tick()
    assert not engine.instructions[i].attack
    assert engine.instructions[i].mode == EnergyMode.BALANCED


def test_attack_ends_with_a_completed_pass(
    engine: RaceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    i = engine.our_index
    assert i is not None
    _issue(engine, T.ATTACK, {})
    ahead = int(engine.st.ahead_idx[i])
    passed = OvertakeEvent(engine.t, i, ahead, float(engine.st.s_m[i]), 0.6, True)
    monkeypatch.setattr(engine.overtake, "resolve", lambda *args: [passed])
    engine._overtake()  # the overtake stage sees Our Car's completed pass
    assert not engine.instructions[i].attack
    assert engine.instructions[i].mode == EnergyMode.BALANCED


def test_let_teammate_by(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    mate = engine._teammate(i)
    assert mate is not None
    deploy = engine.plans.deploy[i].copy()
    engine._rank[[i, mate]] = [0, 1]  # teammate just behind (public timing)
    engine.timing.gap_s[[i, mate]] = [0.0, 0.8]
    _issue(engine, T.LET_TEAMMATE_BY, {})
    assert engine.instructions[i].let_teammate_by
    assert not np.array_equal(engine.plans.deploy[i], deploy)  # yields the straights
    engine._rank[[i, mate]] = [1, 0]  # the teammate is through
    engine._command_upkeep()
    assert not engine.instructions[i].let_teammate_by


def test_push_lap_runs_out(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    v_ref = engine.plans.v_ref[i].copy()
    _issue(engine, T.PUSH_LAP, {"laps": 1})
    assert engine.instructions[i].push_lap
    assert engine.plans.v_ref[i].mean() > v_ref.mean()  # higher grip margin
    _run_laps(engine, 1)
    engine.tick()
    assert not engine.instructions[i].push_lap


def test_manage_tyres_lowers_wear(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    base = _fork(engine)
    _issue(engine, T.MANAGE_TYRES, {"enabled": True})
    assert engine.instructions[i].manage_tyres
    for _ in range(engine.decision_steps):  # the kernel takes it at the next decision tick
        engine.tick()
        base.tick()
    assert engine.ctl.mgmt_factor[i] < base.ctl.mgmt_factor[i]
    w0 = float(engine.st.tyre_wear[i])
    _run_laps(engine, 2)
    _run_laps(base, 2)
    assert engine.st.tyre_wear[i] - w0 < base.st.tyre_wear[i] - w0


def test_each_command_effect_covers_every_type() -> None:
    tested = {
        T.SET_ENERGY_MODE, T.SET_OVERTAKE_PERMISSION, T.SET_LIFT_COAST, T.BOX, T.CANCEL_BOX,
        T.DEFEND, T.ATTACK, T.HOLD_POSITION, T.LET_TEAMMATE_BY, T.PUSH_LAP, T.MANAGE_TYRES,
    }  # fmt: skip
    assert tested == set(CommandType)


def test_commands_survive_a_snapshot(engine: RaceEngine) -> None:
    i = engine.our_index
    assert i is not None
    lap = int(engine.st.lap[i]) + 2
    _issue(engine, T.BOX, {"lap": lap, "compound": "HARD"})
    fork = _fork(engine)
    assert fork._box_plan == engine._box_plan == {i: (lap, Compound.HARD)}
    assert fork.command_handler is None and fork.our_index == i


def test_hold_position_stops_our_overtake_attempts(
    engine: RaceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner, day 6: the engineer's HOLD_POSITION stops Our Car's attempts (TRD)."""
    i = engine.our_index
    assert i is not None
    _issue(engine, T.HOLD_POSITION, {})
    seen: list[Any] = []
    monkeypatch.setattr(engine.overtake, "resolve", lambda *args: seen.append(args) or [])
    engine._overtake()
    holding = seen[0][-1]
    assert holding[i] and holding.sum() == 1  # only Our Car; rival "hold" is not passed on
