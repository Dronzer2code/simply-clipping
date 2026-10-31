"""Hackathon H2: team radio keyword parser, 30 phrases -> commands; nonsense -> "Say again?"."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pitwall_sim.config.loader import load_track
from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.engineer.radio_parser import SAY_AGAIN, corner_names, parse

T = CommandType
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TRACK = load_track("suzuka", CONFIG_DIR)
NAMES = corner_names([(c.corner_id, c.name, list(c.aliases)) for c in TRACK.corners])
LAP = 5
HARV, PUSH, BAL = ({"mode": m} for m in ("HARVEST", "PUSH", "BALANCED"))

Expected = list[tuple[CommandType, dict[str, Any], str]]
PHRASES: list[tuple[str, Expected]] = [
    ("save", [(T.SET_ENERGY_MODE, HARV, "now")]),
    ("Harvest now please", [(T.SET_ENERGY_MODE, HARV, "now")]),
    ("charge the battery", [(T.SET_ENERGY_MODE, HARV, "now")]),
    ("push", [(T.SET_ENERGY_MODE, PUSH, "now")]),
    ("Push push push!", [(T.SET_ENERGY_MODE, PUSH, "now")]),
    ("back to balanced", [(T.SET_ENERGY_MODE, BAL, "now")]),
    ("attack", [(T.ATTACK, {}, "now")]),
    ("go for it into turn one", [(T.ATTACK, {}, "now")]),
    ("overtake on", [(T.SET_OVERTAKE_PERMISSION, {"allowed": True}, "now")]),
    ("use overtake", [(T.SET_OVERTAKE_PERMISSION, {"allowed": True}, "now")]),
    ("overtake off", [(T.SET_OVERTAKE_PERMISSION, {"allowed": False}, "now")]),
    ("no overtake this lap", [(T.SET_OVERTAKE_PERMISSION, {"allowed": False}, "now")]),
    ("defend", [(T.DEFEND, {"corner_id": None}, "now")]),
    ("defend into T10", [(T.DEFEND, {"corner_id": "T10"}, "now")]),
    ("defend Spoon", [(T.DEFEND, {"corner_id": "T13"}, "now")]),
    ("defend the hairpin", [(T.DEFEND, {"corner_id": "T11"}, "now")]),
    ("cover the inside into 130R", [(T.DEFEND, {"corner_id": "T15"}, "now")]),
    ("box box, mediums", [(T.BOX, {"lap": LAP, "compound": "MEDIUM"}, "now")]),
    ("box this lap for mediums", [(T.BOX, {"lap": LAP, "compound": "MEDIUM"}, "now")]),
    ("box next lap softs", [(T.BOX, {"lap": LAP + 1, "compound": "SOFT"}, "now")]),
    ("pit lap 9 hards", [(T.BOX, {"lap": 9, "compound": "HARD"}, "now")]),
    ("box in 2 laps", [(T.BOX, {"lap": LAP + 2, "compound": "HARD"}, "now")]),
    ("cancel box", [(T.CANCEL_BOX, {}, "now")]),
    ("stay out, stay out", [(T.CANCEL_BOX, {}, "now"), (T.CANCEL_BOX, {}, "now")]),
    ("hold position", [(T.HOLD_POSITION, {}, "now")]),
    ("push lap", [(T.PUSH_LAP, {"laps": 1}, "now")]),
    ("give me 2 push laps", [(T.PUSH_LAP, {"laps": 2}, "now")]),
    ("manage tyres", [(T.MANAGE_TYRES, {"enabled": True}, "now")]),
    ("Save this lap, attack into turn 1 next lap", [
        (T.SET_ENERGY_MODE, HARV, "now"), (T.SET_ENERGY_MODE, BAL, "next_lap"),
        (T.ATTACK, {}, "next_lap"),
    ]),
    ("defend T1 then push next lap", [
        (T.DEFEND, {"corner_id": "T1"}, "now"), (T.SET_ENERGY_MODE, PUSH, "next_lap"),
    ]),
]  # fmt: skip


def test_thirty_phrases() -> None:
    assert len(PHRASES) == 30


@pytest.mark.parametrize(("text", "expected"), PHRASES)
def test_phrase(text: str, expected: Expected) -> None:
    result = parse(text, NAMES, LAP, "HARD", "BALANCED")
    got = [(c.kind, {k: str(v) if v is not None else None for k, v in c.params.items()}, c.when)
           for c in result.commands]  # fmt: skip
    want = [(k, {p: str(v) if v is not None else None for p, v in ps.items()}, w)
            for k, ps, w in expected]  # fmt: skip
    assert got == want
    assert result.ack.startswith("Copy, ") and not result.unknown


@pytest.mark.parametrize("text", ["banana smoothie", "", "what's the weather like", "hmm"])
def test_nonsense_gets_say_again(text: str) -> None:
    result = parse(text, NAMES, LAP)
    assert result.commands == () and result.ack == SAY_AGAIN
