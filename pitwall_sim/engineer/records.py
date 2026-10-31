"""Hackathon shared data contracts (TRD DATA CONTRACTS, docs/HACKATHON_SCOPE.md).

Plain dataclasses with no simulator imports, so the engine, the live session, the
UI and the post-race Reveal can all use them:

- :class:`RadioEvent`: one radio message, from the engineer or the driver.
- :class:`CallRecord`: one engineer call (an alert option, a button or a radio
  command) with the snapshot taken when it was made (H1 decision cost).
- :class:`CallCost`: what that call cost against the best alternative (H1).
- :class:`StrategyResult`: one candidate pit plan of the strategy panel (H5).

None of them carries Rival Ground Truth (HR-03): ``StrategyResult`` is built
from Radar Estimates and public tyre data only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type RadioSender = Literal["ENGINEER", "DRIVER"]
type RadioSource = Literal["TEXT", "VOICE", "TEMPLATE", "LLM"]
type PitPlan = Literal["STAY_OUT", "BOX_NOW", "BOX_+1", "BOX_+2", "BOX_+3"]


@dataclass(frozen=True)
class RadioEvent:
    """One radio message (replaces TRD ``RadioMessage``)."""

    t_s: float
    sender: RadioSender
    text: str
    source: RadioSource
    """How it was made: typed, spoken, a template or an LLM reply."""
    command_ids: tuple[str, ...] = ()
    """Engineer Commands the message created."""
    is_fallback: bool = False
    """A template stood in for a failed parser / LLM step."""


@dataclass(frozen=True)
class CallRecord:
    """One engineer call: an alert option, a button or a radio command."""

    t_s: float
    lap: int
    """Our Car's lap when the call was made (1-based)."""
    alert_id: str | None
    """The alert answered, or None for a button / radio command."""
    command_ids: tuple[str, ...]
    option_label: str
    """The alert option's label, or the command type for a button / radio command."""
    snapshot_id: str
    """The race snapshot taken when the call was made (forks for the decision cost)."""


@dataclass(frozen=True)
class CallCost:
    """What one call cost against the best option (after the flag, H1)."""

    call_id: str
    """The ``CallRecord`` (its ``snapshot_id`` + position in the call log)."""
    your_outcome_s: float
    """Our Car's race time at the horizon after the call as made (mean over seeds)."""
    best_option_label: str
    best_outcome_s: float
    delta_s: float
    """``your_outcome_s - best_outcome_s``: positive = the call lost time."""
    n_seeds: int


@dataclass(frozen=True)
class StrategyResult:
    """One pit plan as the strategy panel shows it (H5)."""

    plan: PitPlan
    compound: str | None
    """Tyre fitted at the stop (None for STAY_OUT)."""
    expected_position: float
    """Mean position after the stop (over the forks)."""
    gain_vs_ahead_s: float | None
    """Undercut (> 0) or overcut (< 0) gain on the car ahead, seconds; None without one."""
    car_ahead: str | None = None
    n_forks: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)
