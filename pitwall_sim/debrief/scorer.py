"""F16 debrief scorer, light version (hackathon E2): the engineer score out of 100.

TRD DEBRIEF AND SCORING (PF-16)::

    loss_d = outcome[user] - outcome[best]          per Decision Point d
    score  = 100 * exp(-sum(loss_d) / debrief.score_scale_s)

The hackathon's Decision Points are the calls the engineer made (H1): each
:class:`~pitwall_sim.engineer.records.CallCost` already holds ``delta_s`` =
the call as made minus the best option, over paired seeds (``live/costs.py``),
so ``loss_d = delta_s``. The scale is ``debrief.score_scale_s`` in
``config/app.yaml`` (owner decision 2026-10-19: 20 s, so 5 s lost -> 78 points).

Headless (no Qt, no engine): the Reveal tab and the tests call
:func:`engineer_score` with the costs computed so far. Post-race only: costs
use Ground Truth, which is allowed after the flag (HR-03).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from pitwall_sim.engineer.records import CallCost

BEST_TIE_S = 0.05
"""A call within this of the best option counts as a best call (same as ``live.costs``)."""


@dataclass(frozen=True)
class EngineerScore:
    """The engineer score and its parts (TRD DEBRIEF AND SCORING)."""

    score: float
    """``100 * exp(-total_loss_s / scale_s)``, 0..100."""
    total_loss_s: float
    """Sum of the per-call losses (each ``max(delta_s, 0)``)."""
    scale_s: float
    """``debrief.score_scale_s``."""
    n_calls: int
    """Calls scored."""
    n_best: int
    """Calls within ``BEST_TIE_S`` of their best option."""
    worst_call_id: str | None
    """The call that lost the most time (None without a losing call)."""
    worst_loss_s: float
    worst_best_option: str | None
    """The option that would have been best at the worst call."""

    def breakdown(self) -> str:
        """One line: score, calls, time lost, worst call, the formula."""
        if self.n_calls == 0:
            return "no calls to score: 100 by the formula (nothing lost)"
        line = f"{self.n_calls} calls, {self.n_best} best, {self.total_loss_s:.1f} s lost in total"
        if self.worst_call_id is not None:
            line += f" (worst +{self.worst_loss_s:.1f} s, best was {self.worst_best_option})"
        return line + (
            f"   score = 100 x exp(-{self.total_loss_s:.1f} / {self.scale_s:g}) = {self.score:.0f}"
        )


def score_from_loss(total_loss_s: float, scale_s: float) -> float:
    """Return ``100 * exp(-total_loss_s / scale_s)`` (PF-16)."""
    if not scale_s > 0.0:
        raise ValueError(f"debrief.score_scale_s must be > 0, got {scale_s!r}")
    return 100.0 * math.exp(-max(total_loss_s, 0.0) / scale_s)


def engineer_score(
    costs: Iterable[CallCost], scale_s: float, best_tie_s: float = BEST_TIE_S
) -> EngineerScore:
    """Score the engineer's calls from their decision costs (H1 ``CallCost``).

    Each call's loss is ``max(delta_s, 0)`` (a call cannot beat the best option it
    was compared with; a negative value would only be rounding). No calls: the sum
    is empty, so the score is 100 with ``n_calls`` 0.
    """
    items = list(costs)
    losses = [max(c.delta_s, 0.0) for c in items]
    total = float(sum(losses))
    worst = max(range(len(items)), key=lambda k: losses[k]) if items else None
    losing = worst is not None and losses[worst] > best_tie_s
    return EngineerScore(
        score=score_from_loss(total, scale_s),
        total_loss_s=total,
        scale_s=float(scale_s),
        n_calls=len(items),
        n_best=sum(loss <= best_tie_s for loss in losses),
        worst_call_id=items[worst].call_id if losing and worst is not None else None,
        worst_loss_s=losses[worst] if losing and worst is not None else 0.0,
        worst_best_option=items[worst].best_option_label if losing and worst is not None else None,
    )
