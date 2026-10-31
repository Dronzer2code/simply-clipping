"""F13 Strategy Predictor (R2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PredictorOutput:
    """Strategy Predictor result shown in the EngineerView (F13, R2; empty until then)."""
