"""Team radio keyword parser (hackathon H2): free text -> Engineer Commands, offline.

``parse(text, corners, current_lap, default_compound)`` splits a message into
clauses (``,`` ``;`` ``.`` ``then`` ``and``) and reads each one for keywords:

| Keywords | Command |
| --- | --- |
| save, harvest, charge, lift and coast¹ | SET_ENERGY_MODE HARVEST (¹ SET_LIFT_COAST) |
| push (not "push lap") | SET_ENERGY_MODE PUSH |
| balanced, normal mode | SET_ENERGY_MODE BALANCED |
| attack, go for it | ATTACK |
| overtake on / off (use / no overtake) | SET_OVERTAKE_PERMISSION |
| defend [corner] | DEFEND (corner_id) |
| box [compound] [this / next lap / lap N / in N laps] | BOX (lap, compound) |
| cancel box, stay out | CANCEL_BOX |
| hold, hold position, stay behind | HOLD_POSITION |
| push lap [N laps] | PUSH_LAP (laps) |
| manage tyres [off] | MANAGE_TYRES (enabled) |

"next lap" in a clause sends its commands at the start of Our Car's next lap;
"this lap" with an Energy Mode sets it back to the current mode next lap ("save
this lap, attack into T1 next lap"). Corners: ``T1``, ``turn 1``, ``turn one`` or
a name from the track config (``Corner.name`` / ``aliases``, e.g. Spoon, 130R).
Nothing recognised: the driver answers "Say again?" (the session does that).

The parser only proposes commands; the session sends them through
``commands.validate`` and the queue (HR-07: no parser or LLM changes race state).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pitwall_sim.engineer.commands import CommandType

T = CommandType
When = Literal["now", "next_lap"]
SAY_AGAIN = "Say again?"
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
}  # fmt: skip
COMPOUNDS = {"soft": "SOFT", "softs": "SOFT", "medium": "MEDIUM", "mediums": "MEDIUM",
             "hard": "HARD", "hards": "HARD", "inter": "INTERMEDIATE", "inters": "INTERMEDIATE",
             "intermediate": "INTERMEDIATE", "intermediates": "INTERMEDIATE", "wet": "WET",
             "wets": "WET"}  # fmt: skip


@dataclass(frozen=True)
class ParsedCommand:
    """One command the message asks for."""

    kind: CommandType
    params: dict[str, Any]
    when: When
    ack: str
    """The driver's words for it ("attacking", "saving this lap")."""


@dataclass(frozen=True)
class ParseResult:
    """A message read: its commands (in order) and the clauses nobody understood."""

    commands: tuple[ParsedCommand, ...]
    unknown: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ack(self) -> str:
        """The driver's template reply."""
        if not self.commands:
            return SAY_AGAIN
        said = [c.ack for c in self.commands if c.ack]
        return "Copy, " + ", ".join(dict.fromkeys(said)) + "."


def corner_names(corners: list[tuple[str, str, list[str]]]) -> dict[str, str]:
    """Spoken names -> corner_id from ``(corner_id, name, aliases)`` of the track config."""
    out: dict[str, str] = {}
    for corner_id, name, aliases in corners:
        for word in (corner_id, name, *aliases):
            out[_norm(word)] = corner_id
    return out


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'")
    for word, n in NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", str(n), text)
    text = re.sub(r"\bturn\s*(\d+)\b", r"t\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _clauses(text: str) -> list[str]:
    text = _norm(text).replace("lift and coast", "lift-coast")
    parts = re.split(r"[,;.!?]|\bthen\b|\band\b", text)
    return [p.strip() for p in parts if p.strip()]


def _corner(clause: str, names: dict[str, str]) -> str | None:
    for spoken in sorted(names, key=len, reverse=True):  # longest name first
        if re.search(rf"(?<![\w-]){re.escape(spoken)}(?![\w-])", clause):
            return names[spoken]
    return None


def _has(clause: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", clause) for w in words)


def _box_lap(clause: str, current_lap: int, when: When) -> int:
    if m := re.search(r"\blap (\d+)\b", clause):
        return int(m.group(1))
    if m := re.search(r"\bin (\d+) laps?\b", clause) or re.search(r"\+ ?(\d+)\b", clause):
        return current_lap + int(m.group(1))
    return current_lap + (1 if when == "next_lap" else 0)


def _read(clause: str, names: dict[str, str], current_lap: int, default_compound: str,
          current_mode: str) -> list[ParsedCommand]:  # fmt: skip
    when: When = "next_lap" if _has(clause, "next lap") else "now"
    this_lap = _has(clause, "this lap")
    out: list[ParsedCommand] = []

    def add(kind: CommandType, params: dict[str, Any], ack: str, at: When = when) -> None:
        out.append(ParsedCommand(kind, params, at, ack + (" next lap" if at == "next_lap" else "")))

    def mode(name: str, ack: str) -> None:
        add(T.SET_ENERGY_MODE, {"mode": name}, ack + (" this lap" if this_lap else ""))
        if this_lap and when == "now" and current_mode != name:
            out.append(ParsedCommand(T.SET_ENERGY_MODE, {"mode": current_mode}, "next_lap", ""))

    if _has(clause, "cancel box", "cancel the stop", "stay out", "don't box", "do not box"):
        add(T.CANCEL_BOX, {}, "staying out")
    elif _has(clause, "box", "pit", "pit stop"):
        compound = next((c for w, c in COMPOUNDS.items() if _has(clause, w)), default_compound)
        lap = _box_lap(clause, current_lap, when)
        add(T.BOX, {"lap": lap, "compound": compound}, f"boxing lap {lap}, {compound.lower()}s",
            "now")  # fmt: skip
    if _has(clause, "push lap", "push laps", "quali lap"):
        m = re.search(r"\b(\d+) (?:push )?laps?\b", clause)
        add(T.PUSH_LAP, {"laps": int(m.group(1)) if m else 1}, "push lap")
    elif _has(clause, "push", "full deploy", "deploy everything"):
        mode("PUSH", "pushing")
    if _has(clause, "save", "harvest", "charge", "recharge"):
        mode("HARVEST", "saving")
    if _has(clause, "balanced", "normal mode", "standard mode"):
        mode("BALANCED", "balanced")
    if _has(clause, "lift-coast"):
        add(T.SET_LIFT_COAST, {"enabled": not _has(clause, "no", "stop", "off")}, "lift and coast")
    if re.search(r"\b(no|stop|disable|don't use) overtake\b|\bovertake (mode )?off\b", clause):
        add(T.SET_OVERTAKE_PERMISSION, {"allowed": False}, "no overtake mode")
    elif re.search(r"\b(use |enable )?overtake (mode )?on\b|\buse overtake\b|\benable overtake\b",
                   clause):  # fmt: skip
        add(T.SET_OVERTAKE_PERMISSION, {"allowed": True}, "overtake mode on")
    if _has(clause, "attack", "go for it", "send it", "get him"):
        corner = _corner(clause, names)
        add(T.ATTACK, {}, "attacking" + (f" into {corner}" if corner else ""))
    if _has(clause, "defend", "cover the inside", "protect", "hold him off", "keep him behind"):
        corner = _corner(clause, names)
        add(T.DEFEND, {"corner_id": corner}, "defending" + (f" {corner}" if corner else ""))
    holding = _has(clause, "hold", "hold position", "stay behind", "don't attack", "do not attack")
    if holding and not _has(clause, "hold him off"):
        add(T.HOLD_POSITION, {}, "holding position")
    if _has(clause, "manage tyres", "manage the tyres", "tyre management", "look after the tyres"):
        add(T.MANAGE_TYRES, {"enabled": not _has(clause, "off", "stop", "no more")},
            "managing tyres")  # fmt: skip
    return out


def parse(text: str, corners: dict[str, str], current_lap: int, default_compound: str = "HARD",
          current_mode: str = "BALANCED") -> ParseResult:  # fmt: skip
    """Read an engineer message (``corners``: :func:`corner_names` of the track)."""
    commands: list[ParsedCommand] = []
    unknown: list[str] = []
    for clause in _clauses(text):
        found = _read(clause, corners, current_lap, default_compound, current_mode)
        tyre = next((c for w, c in COMPOUNDS.items() if _has(clause, w)), None)
        if not found and tyre and commands and commands[-1].kind == T.BOX:
            box = commands[-1]  # "box box, mediums": the tyre in its own clause
            lap = box.params["lap"]
            commands[-1] = ParsedCommand(T.BOX, {"lap": lap, "compound": tyre}, box.when,
                                         f"boxing lap {lap}, {tyre.lower()}s")  # fmt: skip
        elif found:
            commands += found
        else:
            unknown.append(clause)
    # a later "next lap" mode wins over the automatic return to the current mode
    later_modes = [c for c in commands if c.kind == T.SET_ENERGY_MODE and c.when == "next_lap"]
    if len(later_modes) > 1:
        auto = later_modes[0]
        commands = [c for c in commands if c is not auto]
    return ParseResult(tuple(commands), tuple(unknown))
