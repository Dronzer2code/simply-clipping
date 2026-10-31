"""F12 Engineer Command schema, validator and queue (T-060; TRD ENGINEER COMMANDS, PF-07).

A command is built from a type and raw parameters (UI buttons or, in R3, the
radio parser), checked by :func:`validate` against public facts only
(:class:`CommandContext`: what the race engineer can see, never Rival Ground
Truth), and queued in :class:`CommandQueue` until ``effective_at_s`` = issue
time + ``radio.radio_latency_s``. An invalid command is rejected with a reason
for the UI and the radio clarification; the LLM never changes race state
directly (HR-07): its output goes through :func:`validate` too.
"""

from __future__ import annotations

import bisect
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pitwall_sim.config.models import Compound, EnergyMode, EngineerConfig


class CommandType(StrEnum):
    """Engineer Command types (TRD ENGINEER COMMANDS)."""

    SET_ENERGY_MODE = "SET_ENERGY_MODE"
    SET_OVERTAKE_PERMISSION = "SET_OVERTAKE_PERMISSION"
    SET_LIFT_COAST = "SET_LIFT_COAST"
    BOX = "BOX"
    CANCEL_BOX = "CANCEL_BOX"
    DEFEND = "DEFEND"
    ATTACK = "ATTACK"
    HOLD_POSITION = "HOLD_POSITION"
    LET_TEAMMATE_BY = "LET_TEAMMATE_BY"
    PUSH_LAP = "PUSH_LAP"
    MANAGE_TYRES = "MANAGE_TYRES"


@dataclass(frozen=True)
class EngineerCommand:
    """One engineer instruction, applied at ``effective_at_s`` (TRD ENGINEER COMMANDS)."""

    command_id: str
    """uuid4."""
    issued_at_s: float
    """Sim time."""
    source: Literal["UI", "RADIO"]
    type: CommandType
    params: dict[str, Any]
    """Validated per type (T-060)."""
    effective_at_s: float
    """``issued_at_s + radio_latency_s`` (``app.yaml: radio.radio_latency_s``)."""


@dataclass(frozen=True)
class CommandContext:
    """Public facts a command is checked against (Our Car's own state + track config)."""

    lap: int
    """Our Car's current lap (laps completed + 1 while racing)."""
    race_laps: int
    zone_ids: frozenset[str]
    """Every zone on the track (lift and coast)."""
    overtake_zone_ids: frozenset[str]
    """Overtaking zones (Overtake Mode permission)."""
    corner_ids: frozenset[str]
    compounds: frozenset[Compound]
    """Compounds the car may fit."""
    box_pending: bool = False
    past_pit_entry: bool = False
    """In the pit lane already: a stop can no longer be cancelled."""
    teammate_gap_behind_s: float | None = None
    """Gap to the teammate behind (public timing); ``None`` if not behind / retired."""


@dataclass(frozen=True)
class Validation:
    """Result of :func:`validate`: normalised parameters, or the reason for rejection."""

    ok: bool
    params: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


class _Invalid(ValueError):
    """A rejection reason."""


def _keys(
    params: Mapping[str, Any], required: set[str], optional: frozenset[str] | set[str] = frozenset()
) -> None:
    unknown = sorted(set(params) - required - set(optional))
    if unknown:
        raise _Invalid(f"unknown parameter(s): {', '.join(unknown)}")
    missing = sorted(required - set(params))
    if missing:
        raise _Invalid(f"missing parameter(s): {', '.join(missing)}")


def _bool(params: Mapping[str, Any], key: str) -> bool:
    value = params[key]
    if not isinstance(value, bool):
        raise _Invalid(f"{key} must be true or false")
    return value


def _int(params: Mapping[str, Any], key: str) -> int:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Invalid(f"{key} must be a whole number")
    return value


def _choice[T: StrEnum](value: Any, kind: type[T], key: str) -> T:
    try:
        return kind(value)
    except ValueError:
        options = ", ".join(m.value for m in kind)
        raise _Invalid(f"{key} must be one of {options}") from None


def _energy(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, {"mode"})
    return {"mode": _choice(p["mode"], EnergyMode, "mode")}


def _overtake(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, {"allowed"}, {"lap", "zone_id"})
    out: dict[str, Any] = {"allowed": _bool(p, "allowed"), "lap": None, "zone_id": None}
    if p.get("lap") is not None:
        out["lap"] = _int(p, "lap")
        if not ctx.lap <= out["lap"] <= ctx.race_laps:
            raise _Invalid(f"lap must be {ctx.lap}..{ctx.race_laps}")
    if p.get("zone_id") is not None:
        if p["zone_id"] not in ctx.overtake_zone_ids:
            raise _Invalid(f"no overtaking zone {p['zone_id']} on this track")
        out["zone_id"] = p["zone_id"]
    return out


def _lift(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, {"enabled"}, {"zone_ids"})
    zones = p.get("zone_ids")
    if zones is not None:
        if not isinstance(zones, list | tuple) or not all(isinstance(z, str) for z in zones):
            raise _Invalid("zone_ids must be a list of zone ids")
        unknown = sorted(set(zones) - ctx.zone_ids)
        if unknown:
            raise _Invalid(f"no zone(s) {', '.join(unknown)} on this track")
        zones = list(zones)
    return {"enabled": _bool(p, "enabled"), "zone_ids": zones}


def _box(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, {"lap", "compound"})
    lap = _int(p, "lap")
    if lap < ctx.lap:
        raise _Invalid(f"lap {lap} has already started (current lap {ctx.lap})")
    if lap > ctx.race_laps:
        raise _Invalid(f"the race has {ctx.race_laps} laps")
    compound = _choice(p["compound"], Compound, "compound")
    if compound not in ctx.compounds:
        raise _Invalid(f"{compound} tyres are not available")
    if ctx.past_pit_entry:
        raise _Invalid("the car is already in the pit lane")
    return {"lap": lap, "compound": compound}


def _cancel_box(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, set())
    if not ctx.box_pending:
        raise _Invalid("no stop is pending")
    if ctx.past_pit_entry:
        raise _Invalid("the car is already past the pit entry")
    return {}


def _defend(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, set(), {"corner_id"})
    corner = p.get("corner_id")
    if corner is not None and corner not in ctx.corner_ids:
        raise _Invalid(f"no corner {corner} on this track")
    return {"corner_id": corner}


def _none(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, set())
    return {}


def _let_by(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, set())
    gap = ctx.teammate_gap_behind_s
    if gap is None or gap > cfg.let_teammate_by_gap_s:
        raise _Invalid(f"the teammate is not within {cfg.let_teammate_by_gap_s:g} s behind")
    return {}


def _push(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, {"laps"})
    laps = _int(p, "laps")
    if not 1 <= laps <= cfg.push_lap_max_laps:
        raise _Invalid(f"laps must be 1..{cfg.push_lap_max_laps}")
    return {"laps": laps}


def _manage(p: Mapping[str, Any], ctx: CommandContext, cfg: EngineerConfig) -> dict[str, Any]:
    _keys(p, {"enabled"})
    return {"enabled": _bool(p, "enabled")}


_CHECKS: dict[
    CommandType, Callable[[Mapping[str, Any], CommandContext, EngineerConfig], dict[str, Any]]
] = {
    CommandType.SET_ENERGY_MODE: _energy,
    CommandType.SET_OVERTAKE_PERMISSION: _overtake,
    CommandType.SET_LIFT_COAST: _lift,
    CommandType.BOX: _box,
    CommandType.CANCEL_BOX: _cancel_box,
    CommandType.DEFEND: _defend,
    CommandType.ATTACK: _none,
    CommandType.HOLD_POSITION: _none,
    CommandType.LET_TEAMMATE_BY: _let_by,
    CommandType.PUSH_LAP: _push,
    CommandType.MANAGE_TYRES: _manage,
}


def validate(
    command_type: CommandType | str,
    params: Mapping[str, Any],
    ctx: CommandContext,
    cfg: EngineerConfig,
) -> Validation:
    """Check one command's parameters (TRD table); never raises."""
    try:
        kind = _choice(command_type, CommandType, "command")
        if not isinstance(params, Mapping):
            raise _Invalid("parameters must be a mapping")
        return Validation(True, _CHECKS[kind](params, ctx, cfg))
    except _Invalid as exc:
        return Validation(False, reason=str(exc))


def make_command(
    command_type: CommandType | str,
    params: Mapping[str, Any],
    ctx: CommandContext,
    cfg: EngineerConfig,
    issued_at_s: float,
    latency_s: float,
    source: Literal["UI", "RADIO"] = "UI",
    command_id: str | None = None,
) -> EngineerCommand | Validation:
    """Build a command due at ``issued_at_s + latency_s``, or return the failed check."""
    checked = validate(command_type, params, ctx, cfg)
    if not checked.ok:
        return checked
    return EngineerCommand(
        command_id=command_id or str(uuid.uuid4()),
        issued_at_s=issued_at_s,
        source=source,
        type=CommandType(command_type),
        params=checked.params,
        effective_at_s=issued_at_s + latency_s,
    )


class CommandQueue:
    """Pending commands in ``effective_at_s`` order (equal times keep issue order)."""

    def __init__(self) -> None:
        """Start empty."""
        self._items: list[tuple[float, int, EngineerCommand]] = []
        self._count = 0

    def __len__(self) -> int:
        """Return the number of pending commands."""
        return len(self._items)

    def push(self, command: EngineerCommand) -> None:
        """Queue a validated command."""
        bisect.insort(self._items, (command.effective_at_s, self._count, command))
        self._count += 1

    def due(self, t_s: float) -> list[EngineerCommand]:
        """Remove and return the commands effective at or before ``t_s``, in order."""
        k = bisect.bisect_right(self._items, (t_s, float("inf")))
        out = [c for _, _, c in self._items[:k]]
        del self._items[:k]
        return out

    def pending(self) -> list[EngineerCommand]:
        """Return the queued commands, in order (not removed)."""
        return [c for _, _, c in self._items]
