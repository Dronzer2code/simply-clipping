"""Sprint A-2 / A-5: each call option sends exactly the listed Engineer Commands."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pitwall_sim.config.loader import load_track
from pitwall_sim.config.models import TrackConfig
from pitwall_sim.engineer import calls as C
from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.observe.alerts import Alert, AlertEvidence
from tests.unit.test_alerts import _car, _view

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
T = CommandType


@pytest.fixture(scope="module")
def track() -> TrackConfig:
    return load_track("suzuka", CONFIG_DIR)


def _alert(kind: str) -> Alert:
    ev = AlertEvidence(2.0, 1.0, None, 0.5, "DEPLOY", None)
    return Alert(f"{kind}-NOR-0", kind, "NOR", 6, "T15", ev, 0.8, 500.0, 508.0)  # type: ignore[arg-type]


def _run(option: C.CallOption, view: Any) -> tuple[list[Any], C.CallRunner]:
    sent: list[tuple[CommandType, dict[str, Any]]] = []
    runner = C.CallRunner(lambda kind, params: sent.append((kind, params)) or None)  # type: ignore[func-returns-value]
    assert runner.start(option, view) == []
    return sent, runner


EXPECTED_NOW = {
    ("ATTACK", 1): [(T.ATTACK, {}), (T.SET_OVERTAKE_PERMISSION, {"allowed": True})],
    ("ATTACK", 2): [(T.SET_ENERGY_MODE, {"mode": "HARVEST"})],
    ("ATTACK", 3): [],
    ("DEFEND", 1): [(T.DEFEND, {"corner_id": "T15"})],
    ("DEFEND", 2): [(T.SET_ENERGY_MODE, {"mode": "PUSH"})],
    ("DEFEND", 3): [(T.HOLD_POSITION, {}), (T.SET_ENERGY_MODE, {"mode": "BALANCED"})],
    ("REPASS_RISK", 1): [(T.HOLD_POSITION, {}), (T.SET_ENERGY_MODE, {"mode": "HARVEST"})],
    ("REPASS_RISK", 2): [(T.ATTACK, {})],
    ("CLOSING_SPEED_RISK", 1): [],
    ("CLOSING_SPEED_RISK", 2): [(T.SET_LIFT_COAST, {"enabled": True, "zone_ids": ["SM2"]})],
}


@pytest.mark.parametrize(("kind", "key"), list(EXPECTED_NOW))
def test_each_option_sends_exactly_its_commands(track: TrackConfig, kind: str, key: int) -> None:
    view = _view(me=_car(s_m=4300.0, lap=5))  # on SM2, BALANCED
    option = next(o for o in C.options(_alert(kind), view, track) if o.key == key)
    sent, _ = _run(option, view)
    assert sent == EXPECTED_NOW[(kind, key)]


def test_option_sets_match_the_spec(track: TrackConfig) -> None:
    view = _view()
    labels = {k: [o.label for o in C.options(_alert(k), view, track)]
              for k in ("ATTACK", "DEFEND", "REPASS_RISK", "CLOSING_SPEED_RISK")}  # fmt: skip
    assert labels == {
        "ATTACK": ["Attack now", "Charge, go next lap", "Ignore"],
        "DEFEND": ["Defend into T15", "Deploy on the straight", "Let him go, save energy"],
        "REPASS_RISK": ["Hold behind, harvest", "Go anyway"],
        "CLOSING_SPEED_RISK": ["Warn driver", "Lift"],
    }
    defend = C.options(_alert("DEFEND"), view, track)[0]
    assert defend.radio == "NOR has the battery - defend into T15." and defend.ack == (
        "Copy, defending T15."
    )
    assert C.alert_line(_alert("ATTACK")) == "NOR low on charge - attack into T15"


def test_headline_and_radio_say_which_rule_fired(track: TrackConfig) -> None:
    def branch(kind: str, why: str) -> Alert:
        a = _alert(kind)
        return replace(a, evidence=replace(a.evidence, branch=why))

    clip = branch("ATTACK", "observed clip")
    assert C.alert_line(clip) == "NOR clipped here last lap - attack into T15"
    assert C.options(clip, _view(), track)[0].radio == "NOR clipped here last lap - attack now."
    own = branch("DEFEND", "own battery")
    assert C.alert_line(own) == "We're short for the straight - defend into T15"
    assert C.options(own, _view(), track)[0].radio == (
        "We're short for the straight - defend into T15."
    )
    both = branch("DEFEND", "energy + own battery")
    assert C.alert_line(both) == "NOR has the battery - defend into T15"


@pytest.mark.parametrize(
    ("kind", "key", "later"),
    [
        ("ATTACK", 2, [(T.SET_ENERGY_MODE, {"mode": "BALANCED"}), (T.ATTACK, {})]),
        ("CLOSING_SPEED_RISK", 2, [(T.SET_LIFT_COAST, {"enabled": False})]),
    ],
)
def test_follow_ups_come_at_the_next_lap(
    track: TrackConfig, kind: str, key: int, later: list[Any]
) -> None:
    view = _view(me=_car(s_m=4300.0, lap=5))
    option = next(o for o in C.options(_alert(kind), view, track) if o.key == key)
    sent, runner = _run(option, view)
    before = len(sent)
    runner.update(_view(me=_car(s_m=5500.0, lap=5)))  # same lap: nothing yet
    assert len(sent) == before
    runner.update(_view(me=_car(s_m=100.0, lap=6)))
    assert sent[before:] == later and not runner.pending


def test_repass_hold_ends_when_the_battery_is_back(track: TrackConfig) -> None:
    view = _view(me=_car(battery_mj=0.8))
    option = C.options(_alert("REPASS_RISK"), view, track)[0]
    sent, runner = _run(option, view)
    runner.update(_view(me=_car(battery_mj=1.9, lap=7)))
    assert len(sent) == 2  # still below 2.0 MJ, even laps later
    runner.update(_view(me=_car(battery_mj=2.05, lap=7)))
    assert sent[2:] == [(T.SET_ENERGY_MODE, {"mode": "BALANCED"})]


def test_rejections_are_reported(track: TrackConfig) -> None:
    view = _view()
    option = C.options(_alert("ATTACK"), view, track)[0]
    runner = C.CallRunner(lambda kind, params: "not now" if kind == T.ATTACK else None)
    assert runner.start(option, replace(view)) == ["ATTACK: not now"]
