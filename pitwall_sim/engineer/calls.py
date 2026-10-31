"""Call the driver (sprint A-2): option buttons per alert -> Engineer Commands + radio.

Each option is a list of steps; a step sends normal Engineer Commands (validated,
radio latency) now, at the start of our next lap, or once our battery reaches a
level. The radio line for the alert and the driver's acknowledgement are
templates (no Gemma). Options (docs/planning/SPRINT.md A-2):

- ATTACK: [1] Attack now: ATTACK + SET_OVERTAKE_PERMISSION(allowed)
  [2] Charge, go next lap: HARVEST now; next lap back to our mode, then ATTACK
  [3] Ignore
- DEFEND: [1] Defend into <corner>: DEFEND(corner)  [2] Deploy on the straight:
  PUSH  [3] Let him go, save energy: HOLD + BALANCED
- REPASS_RISK: [1] Hold behind, harvest: HOLD + HARVEST, back to our mode at
  ``repass_recover_mj`` [2] Go anyway: ATTACK
- CLOSING_SPEED_RISK: [1] Warn driver (radio only)  [2] Lift: SET_LIFT_COAST(on,
  the coming straight), off again next lap

"Back to our mode" is the Energy Mode Our Car had when the call was made.
ATTACK drives in PUSH and DEFEND lasts until the threat has cleared (the engine,
owner sprint day 5), so neither option sends PUSH itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pitwall_sim.config.models import EnergyMode, TrackConfig
from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.observe.alerts import Alert
from pitwall_sim.observe.engineer_view import EngineerView

T = CommandType
Command = tuple[CommandType, dict[str, Any]]
When = Literal["now", "next_lap", "battery_at_least"]
#: REPASS_RISK [1] harvests until our battery is back to this (docs/planning/SPRINT.md A-2).
REPASS_RECOVER_MJ = 2.0


@dataclass(frozen=True)
class CallStep:
    """Commands sent at one moment of a call."""

    when: When
    commands: tuple[Command, ...]
    threshold_mj: float | None = None
    """``battery_at_least`` only."""


@dataclass(frozen=True)
class CallOption:
    """One button under an alert."""

    key: int
    """1, 2 or 3 (F1 / F2 / F3)."""
    label: str
    steps: tuple[CallStep, ...]
    radio: str
    """What the engineer says (empty: nothing sent, the alert is ignored)."""
    ack: str
    """The driver's template reply."""


def _why(alert: Alert) -> str:
    """Return the reason an ATTACK / DEFEND alert gives (the branch that fired)."""
    branch = alert.evidence.branch or "energy"
    if alert.type == "ATTACK":
        return "low on charge" if "energy" in branch else "clipped here last lap"
    return "has the battery" if "energy" in branch else "has more than we need"


def alert_line(alert: Alert) -> str:
    """Return the alert's headline, as it would be said on the radio.

    A plug-in provider may bring its own one-line call (attribute ``radio``,
    Simply Clipping SC-6); the pit wall then shows that.
    """
    own = getattr(alert, "radio", "")
    if isinstance(own, str) and own:
        return own
    rival, corner = alert.rival, alert.corner_id or "the next corner"
    if alert.type == "DEFEND" and "energy" not in (alert.evidence.branch or "energy"):
        return f"We're short for the straight - defend into {corner}"
    return {
        "ATTACK": f"{rival} {_why(alert)} - attack into {corner}",
        "DEFEND": f"{rival} {_why(alert)} - defend into {corner}",
        "REPASS_RISK": "Don't pass yet - you'll be empty on the straight",
        "CLOSING_SPEED_RISK": f"Big closing speed on {rival} - careful into {corner}",
    }[alert.type]


def options(alert: Alert, view: EngineerView, track: TrackConfig) -> list[CallOption]:
    """Return the call options for ``alert`` (A-2), as of ``view``."""
    mode = EnergyMode(view.our_car.energy_mode)
    corner = alert.corner_id
    if alert.type == "ATTACK":
        return [
            CallOption(1, "Attack now", (CallStep("now", (
                (T.ATTACK, {}), (T.SET_OVERTAKE_PERMISSION, {"allowed": True}))),),
                f"{alert.rival} {_why(alert)} - attack now.", "Copy, attacking."),
            CallOption(2, "Charge, go next lap", (
                CallStep("now", ((T.SET_ENERGY_MODE, {"mode": "HARVEST"}),)),
                CallStep("next_lap", ((T.SET_ENERGY_MODE, {"mode": mode.value}), (T.ATTACK, {})))),
                "Charge this lap, then go for him.", "Copy, charging, attack next lap."),
            _ignore(),
        ]  # fmt: skip
    if alert.type == "DEFEND":
        return [
            CallOption(1, f"Defend into {corner or 'next corner'}", (
                CallStep("now", ((T.DEFEND, {"corner_id": corner}),)),),
                f"{alert_line(alert)}.", f"Copy, defending {corner}."),
            CallOption(2, "Deploy on the straight", (
                CallStep("now", ((T.SET_ENERGY_MODE, {"mode": "PUSH"}),)),),
                "Deploy everything on the straight.", "Copy, deploying."),
            CallOption(3, "Let him go, save energy", (
                CallStep("now", ((T.HOLD_POSITION, {}),
                                 (T.SET_ENERGY_MODE, {"mode": "BALANCED"}))),),
                "Let him go, save the energy.", "Copy, letting him by."),
        ]  # fmt: skip
    if alert.type == "REPASS_RISK":
        return [
            CallOption(1, "Hold behind, harvest", (
                CallStep("now", ((T.HOLD_POSITION, {}), (T.SET_ENERGY_MODE, {"mode": "HARVEST"}))),
                CallStep("battery_at_least", ((T.SET_ENERGY_MODE, {"mode": mode.value}),),
                         REPASS_RECOVER_MJ)),
                "Don't pass yet - you'll be empty on the straight. Hold and charge.",
                "Copy, holding and charging."),
            CallOption(2, "Go anyway", (CallStep("now", ((T.ATTACK, {}),)),),
                       "Go anyway.", "Copy, going for it."),
        ]  # fmt: skip
    zone = _coming_straight(track, view.our_car.s_m)
    return [
        CallOption(1, "Warn driver", (), f"Big closing speed on {alert.rival} - careful.",
                   "Copy, eyes open."),
        CallOption(2, "Lift", (
            CallStep("now", ((T.SET_LIFT_COAST, {"enabled": True,
                                                 "zone_ids": [zone] if zone else None}),)),
            CallStep("next_lap", ((T.SET_LIFT_COAST, {"enabled": False}),))),
            "Lift and coast on the straight.", "Copy, lifting."),
    ]  # fmt: skip


def _ignore() -> CallOption:
    return CallOption(3, "Ignore", (), "", "")


def _coming_straight(track: TrackConfig, s_m: float) -> str | None:
    """Return the straight zone we are on, else the next one ahead."""
    length = float(track.official_length_m)
    best, best_d = None, float("inf")
    for z in track.zones:
        if z.type != "straight":
            continue
        if (s_m - z.s_start_m) % length <= (z.s_end_m - z.s_start_m) % length:
            return z.zone_id
        d = (z.s_start_m - s_m) % length
        if d < best_d:
            best, best_d = z.zone_id, d
    return best


@dataclass
class _Pending:
    step: CallStep
    lap: int
    """Our lap when the call was made."""


@dataclass
class CallRunner:
    """Sends a call's steps when they come due; ``issue`` returns a rejection reason or None."""

    issue: Callable[[CommandType, dict[str, Any]], str | None]
    pending: list[_Pending] = field(default_factory=list)

    def start(self, option: CallOption, view: EngineerView) -> list[str]:
        """Send the option's ``now`` step, keep the rest; return rejection reasons."""
        reasons = []
        for step in option.steps:
            if step.when == "now":
                reasons += self._send(step)
            else:
                self.pending.append(_Pending(step, view.our_car.lap))
        return reasons

    def update(self, view: EngineerView) -> list[str]:
        """Send follow-up steps that are due now; return rejection reasons."""
        reasons: list[str] = []
        keep = []
        for p in self.pending:
            due = (p.step.when == "next_lap" and view.our_car.lap > p.lap) or (
                p.step.when == "battery_at_least"
                and view.our_car.battery_mj >= (p.step.threshold_mj or 0.0)
            )
            if due:
                reasons += self._send(p.step)
            else:
                keep.append(p)
        self.pending = keep
        return reasons

    def _send(self, step: CallStep) -> list[str]:
        out = []
        for kind, params in step.commands:
            reason = self.issue(kind, params)
            if reason is not None:
                out.append(f"{kind}: {reason}")
        return out
