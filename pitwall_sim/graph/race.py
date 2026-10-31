"""Race comparison graph from the command line (Graphify track).

    python -m pitwall_sim.graph.race --run data/exports/suzuka_normal_s42
    python -m pitwall_sim.graph.race --run graphify-out/races/live_suzuka_s2_GAS_15l
    python -m pitwall_sim.graph.race --simulate --seed 2 --laps 15 --our GAS

``--run``: an export folder (``run.json``), a saved live race (``race_record.json``,
written next to every graph), or the folder holding one. ``--simulate``: run a live
race headless with an automatic engineer (answers every alert with its first
option, sends the demo radio call), compute the decision costs, then graph it.
Output: ``graphify-out/races/<run_id>/`` (``--out`` to change): ``graph.json``
(graphify schema), ``graph.html``, ``dashboard.html``, ``race_report.md``,
``race_record.json``, ``labels.json``, ``lib/`` (the vendored JS libraries).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR
from pitwall_sim.graph.race_graph import RaceGraphPaths, write_race_graph
from pitwall_sim.graph.record import RaceRecord, from_export, from_session
from pitwall_sim.live.session import LiveSession, LiveSetup

logger = logging.getLogger(__name__)
OUT_ROOT = DEFAULT_CONFIG_DIR.resolve().parent / "graphify-out" / "races"
DEMO_RADIO = "Save this lap, attack into turn 1 next lap"
"""The demo's radio call (docs/guides/DEMO_HACKATHON.md)."""


def graph_session(session: LiveSession, out_root: Path = OUT_ROOT) -> RaceGraphPaths:
    """Write the race graph of a finished live session (raises before the flag)."""
    record = from_session(session)
    return write_race_graph(record, out_root / record.run_id)


def load_run(path: Path, config_dir: Path = DEFAULT_CONFIG_DIR, alerts: Path | None = None,
             estimates: Path | None = None) -> RaceRecord:  # fmt: skip
    """Load a race record from an export folder or a saved ``race_record.json``."""
    if path.is_file():
        return RaceRecord.load(path)
    if (path / "race_record.json").exists():
        return RaceRecord.load(path / "race_record.json")
    if (path / "run.json").exists():
        return from_export(path, config_dir, alerts, estimates)
    raise FileNotFoundError(f"{path}: neither an export folder nor a saved race (race_record.json)")


def simulate(seed: int, laps: int, our: str, config_dir: Path = DEFAULT_CONFIG_DIR,
             radio_lap: int | None = 3, costs: bool = True, test_mode: bool = False,
             scripted_sc_lap: int | None = None) -> LiveSession:  # fmt: skip
    """Run a live race headless with an automatic engineer, to the flag (and its costs).

    The engineer answers every alert with its first option and, on ``radio_lap``,
    sends the demo radio call. Every call goes through the session (validation,
    snapshots), exactly as the pit wall's would.
    """
    session = LiveSession(LiveSetup(our_driver_id=our, seed=seed, laps=laps,
                                    test_mode=test_mode, scripted_sc_lap=scripted_sc_lap),
                          config_dir)  # fmt: skip
    said = False
    while session.advance(1.0):
        frame = session.frame()
        for alert in frame.alerts:
            if frame.options.get(alert.alert_id):
                session.call(alert.alert_id, 1)
        if radio_lap is not None and not said and frame.view.our_car.lap + 1 >= radio_lap:
            session.radio_message(DEMO_RADIO)
            said = True
    if costs:
        for index in range(len(session.call_log)):
            session.compute_cost(index)
    return session


def main(argv: list[str] | None = None) -> None:
    """Build a race graph from a run or a headless race."""
    parser = argparse.ArgumentParser(description="Race comparison graph (after the flag)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", type=Path, help="export folder or saved race (race_record.json)")
    src.add_argument("--simulate", action="store_true", help="run a live race headless first")
    parser.add_argument(
        "--out", type=Path, help="output folder (default graphify-out/races/<run_id>)"
    )
    parser.add_argument("--alerts", type=Path, help="export: an estimator's alerts.parquet")
    parser.add_argument("--estimates", type=Path, help="export: an estimator's estimates.parquet")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--laps", type=int, default=15)
    parser.add_argument("--our", default="GAS")
    parser.add_argument("--no-costs", action="store_true", help="simulate: skip the decision costs")
    parser.add_argument("--test-mode", action="store_true", help="simulate: Test mode on")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.simulate:
        session = simulate(args.seed, args.laps, args.our, args.config_dir,
                           costs=not args.no_costs, test_mode=args.test_mode)  # fmt: skip
        try:
            record = from_session(session)
        finally:
            session.close()
    else:
        record = load_run(args.run, args.config_dir, args.alerts, args.estimates)
    paths = write_race_graph(record, args.out or OUT_ROOT / record.run_id)
    logger.info("race graph written to %s", paths.folder)
    for path in (paths.graph_html, paths.dashboard, paths.report, paths.graph_json):
        if path is not None:
            print(path)


if __name__ == "__main__":
    main()
