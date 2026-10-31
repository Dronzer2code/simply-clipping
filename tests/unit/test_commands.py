"""T-060: Engineer Command validation (a rejection per type) and the queue (PF-07)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pitwall_sim.config.loader import load_app
from pitwall_sim.config.models import Compound, EnergyMode, EngineerConfig
from pitwall_sim.engineer.commands import (
    CommandContext,
    CommandQueue,
    CommandType,
    EngineerCommand,
    Validation,
    make_command,
    validate,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
T = CommandType


@pytest.fixture(scope="module")
def cfg() -> EngineerConfig:
    return load_app(CONFIG_DIR).engineer


CTX = CommandContext(
    lap=10, race_laps=53, zone_ids=frozenset({"SM1", "SM2", "ST3", "OT1"}),
    overtake_zone_ids=frozenset({"OT1"}), corner_ids=frozenset({"T1", "T11"}),
    compounds=frozenset({Compound.SOFT, Compound.MEDIUM, Compound.HARD}),
    teammate_gap_behind_s=1.2,
)  # fmt: skip

VALID: list[tuple[CommandType, dict[str, Any], dict[str, Any]]] = [
    (T.SET_ENERGY_MODE, {"mode": "PUSH"}, {"mode": EnergyMode.PUSH}),
    (T.SET_OVERTAKE_PERMISSION, {"allowed": False},
     {"allowed": False, "lap": None, "zone_id": None}),
    (T.SET_OVERTAKE_PERMISSION, {"allowed": True, "lap": 12, "zone_id": "OT1"},
     {"allowed": True, "lap": 12, "zone_id": "OT1"}),
    (T.SET_LIFT_COAST, {"enabled": True}, {"enabled": True, "zone_ids": None}),
    (T.SET_LIFT_COAST, {"enabled": True, "zone_ids": ["SM1"]},
     {"enabled": True, "zone_ids": ["SM1"]}),
    (T.BOX, {"lap": 10, "compound": "HARD"}, {"lap": 10, "compound": Compound.HARD}),
    (T.DEFEND, {}, {"corner_id": None}),
    (T.DEFEND, {"corner_id": "T1"}, {"corner_id": "T1"}),
    (T.ATTACK, {}, {}),
    (T.HOLD_POSITION, {}, {}),
    (T.LET_TEAMMATE_BY, {}, {}),
    (T.PUSH_LAP, {"laps": 3}, {"laps": 3}),
    (T.MANAGE_TYRES, {"enabled": False}, {"enabled": False}),
]  # fmt: skip


@pytest.mark.parametrize(("kind", "params", "normal"), VALID)
def test_valid_commands_are_normalised(
    cfg: EngineerConfig, kind: CommandType, params: dict[str, Any], normal: dict[str, Any]
) -> None:
    result = validate(kind, params, CTX, cfg)
    assert result == Validation(True, normal)


INVALID: list[tuple[CommandType, dict[str, Any], CommandContext, str]] = [
    (T.SET_ENERGY_MODE, {"mode": "FAST"}, CTX, "mode must be one of"),
    (T.SET_ENERGY_MODE, {}, CTX, "missing parameter(s): mode"),
    (T.SET_OVERTAKE_PERMISSION, {"allowed": "yes"}, CTX, "allowed must be true or false"),
    (T.SET_OVERTAKE_PERMISSION, {"allowed": True, "zone_id": "SM1"}, CTX, "no overtaking zone"),
    (T.SET_OVERTAKE_PERMISSION, {"allowed": True, "lap": 4}, CTX, "lap must be 10..53"),
    (T.SET_LIFT_COAST, {"enabled": True, "zone_ids": ["Z9"]}, CTX, "no zone(s) Z9"),
    (T.SET_LIFT_COAST, {"enabled": True, "zone_ids": "SM1"}, CTX, "must be a list"),
    (T.BOX, {"lap": 9, "compound": "HARD"}, CTX, "has already started"),
    (T.BOX, {"lap": 60, "compound": "HARD"}, CTX, "the race has 53 laps"),
    (T.BOX, {"lap": 12, "compound": "WET"}, CTX, "WET tyres are not available"),
    (T.BOX, {"lap": 12, "compound": "SUPERSOFT"}, CTX, "compound must be one of"),
    (T.BOX, {"lap": 12.5, "compound": "HARD"}, CTX, "lap must be a whole number"),
    (T.CANCEL_BOX, {}, CTX, "no stop is pending"),
    (T.CANCEL_BOX, {}, CommandContext(**{**CTX.__dict__, "box_pending": True,
                                         "past_pit_entry": True}), "past the pit entry"),
    (T.DEFEND, {"corner_id": "T99"}, CTX, "no corner T99"),
    (T.ATTACK, {"now": True}, CTX, "unknown parameter(s): now"),
    (T.HOLD_POSITION, {"gap": 1}, CTX, "unknown parameter(s): gap"),
    (T.LET_TEAMMATE_BY, {}, CommandContext(**{**CTX.__dict__, "teammate_gap_behind_s": 3.5}),
     "not within 2 s behind"),
    (T.LET_TEAMMATE_BY, {}, CommandContext(**{**CTX.__dict__, "teammate_gap_behind_s": None}),
     "not within"),
    (T.PUSH_LAP, {"laps": 6}, CTX, "laps must be 1..5"),
    (T.PUSH_LAP, {"laps": True}, CTX, "whole number"),
    (T.MANAGE_TYRES, {"enabled": 1}, CTX, "true or false"),
]  # fmt: skip


@pytest.mark.parametrize(("kind", "params", "ctx", "reason"), INVALID)
def test_invalid_commands_are_rejected_with_a_reason(
    cfg: EngineerConfig, kind: CommandType, params: dict[str, Any], ctx: CommandContext,
    reason: str,
) -> None:  # fmt: skip
    result = validate(kind, params, ctx, cfg)
    assert not result.ok and result.reason is not None and reason in result.reason


def test_every_type_has_a_rejection_test() -> None:
    assert {k for k, *_ in INVALID} == set(CommandType)


def test_unknown_type_and_bad_params_never_raise(cfg: EngineerConfig) -> None:
    assert "command must be one of" in (validate("TELEPORT", {}, CTX, cfg).reason or "")
    assert validate(T.ATTACK, ["x"], CTX, cfg).reason == "parameters must be a mapping"  # type: ignore[arg-type]


def test_make_command_sets_the_effective_time(cfg: EngineerConfig) -> None:
    cmd = make_command(T.BOX, {"lap": 11, "compound": "MEDIUM"}, CTX, cfg, 100.0, 1.0)
    assert isinstance(cmd, EngineerCommand)
    assert cmd.effective_at_s == 101.0 and cmd.source == "UI"
    assert cmd.params == {"lap": 11, "compound": Compound.MEDIUM} and len(cmd.command_id) == 36
    bad = make_command(T.BOX, {"lap": 1, "compound": "MEDIUM"}, CTX, cfg, 100.0, 1.0)
    assert isinstance(bad, Validation) and not bad.ok


def test_queue_releases_commands_in_effective_order() -> None:
    q = CommandQueue()

    def cmd(name: str, t: float) -> EngineerCommand:
        return EngineerCommand(name, t - 1.0, "UI", T.ATTACK, {}, t)

    for c in (cmd("c", 30.0), cmd("a", 10.0), cmd("b1", 20.0), cmd("b2", 20.0)):
        q.push(c)
    assert [c.command_id for c in q.pending()] == ["a", "b1", "b2", "c"]
    assert q.due(5.0) == []
    assert [c.command_id for c in q.due(20.0)] == ["a", "b1", "b2"]  # ties: issue order
    assert len(q) == 1 and [c.command_id for c in q.due(1e9)] == ["c"] and len(q) == 0
