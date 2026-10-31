"""Hosted-LLM command reading for the team radio (hackathon H2).

Free phrasing ("hold him off till the hairpin then go for it into 130R") ->
tool calls -> :class:`~pitwall_sim.engineer.radio_parser.ParseResult`, the same
shape the keyword parser produces. One tool per Engineer Command type, with the
parameters of ``engineer/commands.py`` plus ``when`` (``now`` / ``next_lap``).

The LLM only proposes: the session sends every command through
``commands.validate`` and the queue (HR-07). The prompt carries Our Car's own
data, public timing and the track's corner names only (HR-03: no Rival Ground
Truth, no radar internals).
"""

from __future__ import annotations

import logging
from typing import Any

from pitwall_sim.config.models import Compound, EnergyMode, EngineerConfig
from pitwall_sim.engineer.commands import CommandContext, CommandType
from pitwall_sim.engineer.radio_parser import ParsedCommand, ParseResult, When
from pitwall_sim.observe.engineer_view import EngineerView
from pitwall_sim.radio.hosted_llm import LLMProvider, Tool, ToolCall, call_with_timeout

logger = logging.getLogger(__name__)
T = CommandType

SYSTEM = (
    "You are the radio link between a Formula 1 race engineer and the driver of Our Car "
    "(2026 rules: Energy Modes PUSH / BALANCED / HARVEST, Overtake Mode, no DRS). Turn the "
    "engineer's message into tool calls, one per instruction, in the order spoken. Use "
    "when=next_lap only for instructions meant for the next lap; everything else is now. "
    "BOX takes the absolute lap number (this lap = the current lap). Corners and zones: use "
    "only the ids listed. If the message holds no instruction you can map to a tool, call no "
    "tool. Never invent data."
)


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    when = {"type": "string", "enum": ["now", "next_lap"],
            "description": "now (default) or at the start of Our Car's next lap"}  # fmt: skip
    return {"type": "object", "properties": {**props, "when": when}, "required": required,
            "additionalProperties": False}  # fmt: skip


def tools(ctx: CommandContext, cfg: EngineerConfig) -> tuple[Tool, ...]:
    """Engineer Commands as tools (types and parameters of ``engineer/commands.py``)."""
    corners = sorted(ctx.corner_ids)
    zones = sorted(ctx.zone_ids)
    ot_zones = sorted(ctx.overtake_zone_ids)
    compounds = sorted(c.value for c in ctx.compounds) or [c.value for c in Compound]
    lap = {"type": "integer", "minimum": ctx.lap, "maximum": ctx.race_laps}
    boolean = {"type": "boolean"}
    return (
        Tool(T.SET_ENERGY_MODE, "Set the Energy Mode (save/harvest, push, balanced).",
             _obj({"mode": {"type": "string", "enum": [m.value for m in EnergyMode]}},
                  ["mode"])),
        Tool(T.SET_OVERTAKE_PERMISSION, "Allow or forbid Overtake Mode, optionally on a lap "
             "or in one overtaking zone.",
             _obj({"allowed": boolean, "lap": lap,
                   "zone_id": {"type": "string", "enum": ot_zones}}, ["allowed"])),
        Tool(T.SET_LIFT_COAST, "Lift and coast on or off, optionally in some zones.",
             _obj({"enabled": boolean,
                   "zone_ids": {"type": "array", "items": {"type": "string", "enum": zones}}},
                  ["enabled"])),
        Tool(T.BOX, "Pit stop at the end of a lap, fitting a compound.",
             _obj({"lap": lap, "compound": {"type": "string", "enum": compounds}},
                  ["lap", "compound"])),
        Tool(T.CANCEL_BOX, "Cancel the planned pit stop (stay out).", _obj({}, [])),
        Tool(T.DEFEND, "Defend against the car behind, optionally covering one corner "
             "(hold him off).",
             _obj({"corner_id": {"type": "string", "enum": corners}}, [])),
        Tool(T.ATTACK, "Attack the car ahead (go for it, send it).", _obj({}, [])),
        Tool(T.HOLD_POSITION, "Hold position: do not attack.", _obj({}, [])),
        Tool(T.LET_TEAMMATE_BY, "Let the teammate behind through.", _obj({}, [])),
        Tool(T.PUSH_LAP, "Qualifying-style push for some laps.",
             _obj({"laps": {"type": "integer", "minimum": 1,
                            "maximum": cfg.push_lap_max_laps}}, ["laps"])),
        Tool(T.MANAGE_TYRES, "Tyre management on or off.", _obj({"enabled": boolean},
                                                                ["enabled"])),
    )  # fmt: skip


def prompt(text: str, view: EngineerView, our: str, ctx: CommandContext,
           corners: list[tuple[str, str, list[str]]]) -> str:  # fmt: skip
    """Build the user message: the engineer's words, Our Car's data, public facts only."""
    car, timing = view.our_car, view.timing
    order = timing.order
    place = order.index(our) + 1 if our in order else None
    lines = [
        f'Engineer: "{text}"',
        f"Our Car: lap {ctx.lap} of {ctx.race_laps}, P{place}, {car.compound} tyres "
        f"{car.tyre_age_laps} laps old ({car.tyre_wear:.0%} worn), battery "
        f"{car.battery_mj:.1f} MJ, Energy Mode {car.energy_mode}, "
        f"pit stop planned: {'yes' if ctx.box_pending else 'no'}.",
    ]
    if place is not None:  # public timing: who is ahead / behind and the gaps
        for label, k in (("ahead", place - 2), ("behind", place)):
            if 0 <= k < len(order):
                rival = order[k]
                gaps = timing.gap_to_leader_s
                gap = gaps.get(rival, 0.0) - gaps.get(our, 0.0)
                lines.append(f"Car {label}: {rival} (P{k + 1}), gap {abs(gap):.1f} s.")
    lines.append(f"Track status: {view.track_status.status}.")
    lines.append("Corners: " + "; ".join(
        f"{cid} = {name}" + (f" ({', '.join(aliases)})" if aliases else "")
        for cid, name, aliases in corners))  # fmt: skip
    lines.append("Overtaking zones: " + ", ".join(sorted(ctx.overtake_zone_ids)) + ".")
    lines.append("Compounds available: " + ", ".join(sorted(c.value for c in ctx.compounds)))
    return "\n".join(lines)


def ack_for(kind: CommandType, params: dict[str, Any], when: When) -> str:
    """Return the driver's words for a command (template, like the keyword parser's)."""
    text = {
        T.SET_ENERGY_MODE: {"PUSH": "pushing", "HARVEST": "saving",
                            "BALANCED": "balanced"}.get(str(params.get("mode")), "mode set"),
        T.SET_OVERTAKE_PERMISSION: "overtake mode on" if params.get("allowed")
        else "no overtake mode",
        T.SET_LIFT_COAST: "lift and coast" if params.get("enabled") else "no lift and coast",
        T.BOX: f"boxing lap {params.get('lap')}, {str(params.get('compound', '')).lower()}s",
        T.CANCEL_BOX: "staying out",
        T.DEFEND: "defending" + (f" {params['corner_id']}" if params.get("corner_id") else ""),
        T.ATTACK: "attacking",
        T.HOLD_POSITION: "holding position",
        T.LET_TEAMMATE_BY: "letting him by",
        T.PUSH_LAP: "push lap",
        T.MANAGE_TYRES: "managing tyres" if params.get("enabled") else "tyre management off",
    }[kind]  # fmt: skip
    return text + (" next lap" if when == "next_lap" else "")


def to_result(calls: tuple[ToolCall, ...]) -> ParseResult:
    """Tool calls -> proposed commands (unknown tools dropped; parameters unchecked here)."""
    out: list[ParsedCommand] = []
    unknown: list[str] = []
    for call in calls:
        try:
            kind = CommandType(call.name)
        except ValueError:
            unknown.append(call.name)
            continue
        params = dict(call.arguments)
        when: When = "next_lap" if params.pop("when", "now") == "next_lap" else "now"
        if kind == T.BOX:
            when = "now"  # the stop lap is in its parameters
        out.append(ParsedCommand(kind, params, when, ack_for(kind, params, when)))
    return ParseResult(tuple(out), tuple(unknown))


def interpret(provider: LLMProvider, user_prompt: str, tool_set: tuple[Tool, ...],
              timeout_s: float) -> ParseResult | None:  # fmt: skip
    """Ask the LLM (at most ``timeout_s``); its proposed commands, or None (keyword parser)."""
    try:
        reply = call_with_timeout(
            lambda: provider.complete(SYSTEM, user_prompt, tool_set, timeout_s), timeout_s
        )
        result = to_result(reply.tool_calls)
    except Exception as exc:  # noqa: BLE001 (any failure -> keyword parser)
        logger.info("radio LLM failed (%s): keyword parser", type(exc).__name__)
        return None
    return result if result.commands else None
