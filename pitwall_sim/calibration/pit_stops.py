"""Pit-stop statistics from OpenF1 for ``app.yaml`` ``pit`` (T-035, TRD PIT LANE).

Stationary time ~ Normal(``stop_mean_s``, ``stop_sd_s``) clipped at
``stop_min_s``, plus a slow stop with probability ``slow_stop_p`` adding
``slow_stop_extra_s``. Fitted on one race's OpenF1 ``/pit`` rows
(``stop_duration``): stops above Q3 + 1.5 IQR count as slow; mean, SD and
minimum come from the others. ``lane_duration`` (pit entry to exit, stop
included) gives the speed-limited lane length for the track config:
(median lane time - mean stop) x lane speed.

Usage::

    python -m pitwall_sim.calibration.pit_stops --track suzuka

Prints a YAML fragment with its source; it does not edit the config.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, ConfigError, load_app, load_track
from pitwall_sim.track.openf1 import OpenF1Client, OpenF1Error, find_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PitStopStats:
    """Stationary-time distribution and pit-lane time of one race."""

    n_stops: int
    stop_mean_s: float
    stop_sd_s: float
    stop_min_s: float
    slow_stop_p: float
    slow_stop_extra_s: float
    lane_median_s: float


def pit_stop_stats(rows: Sequence[dict[str, Any]]) -> PitStopStats:
    """Fit the stop-time model to OpenF1 ``/pit`` rows.

    Raises:
        ValueError: Fewer than three rows have a ``stop_duration``.

    """
    stops = np.array([float(r["stop_duration"]) for r in rows if r.get("stop_duration")])
    lanes = np.array([float(r["lane_duration"]) for r in rows if r.get("lane_duration")])
    if stops.size < 3:
        raise ValueError(f"need at least 3 stop durations, got {stops.size}")
    q1, q3 = np.percentile(stops, [25, 75])
    slow_mask = stops > q3 + 1.5 * (q3 - q1)
    normal, slow = stops[~slow_mask], stops[slow_mask]
    mean = float(normal.mean())
    return PitStopStats(
        n_stops=int(stops.size),
        stop_mean_s=mean,
        stop_sd_s=float(normal.std(ddof=1)),
        stop_min_s=float(normal.min()),
        slow_stop_p=float(slow.size / stops.size),
        slow_stop_extra_s=float((slow - mean).mean()) if slow.size else 0.0,
        lane_median_s=float(np.median(lanes)) if lanes.size else float("nan"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print the pit-stop model for one track's race as a YAML fragment."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True, help="track_id, e.g. suzuka")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    client = OpenF1Client(app.openf1, Path(app.paths.openf1_cache))
    race_track = track.model_copy(
        update={"geometry_source": track.geometry_source.model_copy(update={"session": "R"})}
    )
    try:
        race = find_session(race_track, client)
        stats = pit_stop_stats(client.get("pit", [("session_key=", str(race["session_key"]))]))
    except (OpenF1Error, ValueError) as exc:
        logger.error("%s", exc)
        return 2
    print(
        f"# OpenF1 /pit stop_duration, session {race['session_key']} ({stats.n_stops} stops);"
        f" slow = above Q3 + 1.5 IQR; lane_duration median {stats.lane_median_s:.1f} s"
    )
    print(f"stop_mean_s: {stats.stop_mean_s:.2f}")
    print(f"stop_sd_s: {stats.stop_sd_s:.2f}")
    print(f"stop_min_s: {stats.stop_min_s:.2f}")
    print(f"slow_stop_p: {stats.slow_stop_p:.3f}")
    print(f"slow_stop_extra_s: {stats.slow_stop_extra_s:.2f}")
    lane_kmh = track.pit.lane_speed_kmh
    if isinstance(lane_kmh, (int, float)):
        limit_m = (stats.lane_median_s - stats.stop_mean_s) * lane_kmh / 3.6
        print(f"# track pit: (lane median - mean stop) x {lane_kmh} km/h")
        print(f"limit_length_m: {limit_m:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
