"""F10 Public Feed frame (TRD DATA CONTRACTS), apart from the feed's engine side.

The Radar imports frames from here, so it never depends on the simulation core
(import-linter contract ``radar-feed-only``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicFeedFrame:
    """One Rival telemetry sample (TRD DATA CONTRACTS)."""

    t_s: float
    driver_id: str
    speed_kmh: float
    throttle_pct: float
    brake: bool
    gear: int
    x_m: float
    y_m: float
    distance_m: float
