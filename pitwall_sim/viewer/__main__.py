"""Replay viewer CLI (sprint S-2).

Usage::

    python -m pitwall_sim.viewer --seed 42                    # record a race, then play it
    python -m pitwall_sim.viewer --run data/runs/suzuka_2026_post_miami_s42
    python -m pitwall_sim.viewer --seed 7 --rules 2026_pre_miami --record-only
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, ConfigError
from pitwall_sim.race.engine import RaceSetup
from pitwall_sim.viewer.record import REPLAY_FILE, Replay, record

logger = logging.getLogger("pitwall_sim.viewer")


def main(argv: Sequence[str] | None = None) -> int:
    """Record (unless ``--run`` exists) and open the replay window."""
    parser = argparse.ArgumentParser(description="pitwall_sim replay viewer")
    parser.add_argument("--run", type=Path, help="a recorded run directory to play")
    parser.add_argument("--track", default="suzuka")
    parser.add_argument("--rules", default="2026_post_miami")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--laps", type=int, help="race distance (default: the track's)")
    parser.add_argument("--fuel-kg", type=float, default=110.0,
                        help="start fuel per car (default 110 kg until T-02B)")  # fmt: skip
    parser.add_argument("--rain", choices=("auto", "dry", "rain"), default="auto")
    parser.add_argument("--record-only", action="store_true", help="record, do not open a window")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("pitwall_sim.race").setLevel(logging.WARNING)  # no per-event lines

    name = f"{args.track}_{args.rules}_s{args.seed}" + (f"_l{args.laps}" if args.laps else "")
    run = args.run or Path("data/runs") / name
    if not (run / REPLAY_FILE).exists():
        if args.run is not None and not args.run.exists():
            logger.error("no recorded run at %s", args.run)
            return 1
        logger.info("recording %s (one headless race, ~10-20 s) ...", run)
        setup = RaceSetup(
            track_id=args.track, rule_set_id=args.rules, seed=args.seed, laps=args.laps,
            fuel_kg=args.fuel_kg, rain=args.rain,
        )  # fmt: skip
        try:
            record(setup, args.config_dir).save(run)
        except (ConfigError, FileNotFoundError) as exc:
            logger.error("%s", exc)
            return 1
        logger.info("recorded -> %s", run)
    if args.record_only:
        return 0
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415  (only when a window opens)

    from pitwall_sim.viewer.app import ReplayWindow  # noqa: PLC0415

    app = QApplication.instance() or QApplication(sys.argv)
    window = ReplayWindow(Replay.load(run))
    window.resize(1280, 860)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
