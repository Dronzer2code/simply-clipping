"""Headless alert check (sprint A-1): run a race, list every alert Our Car would get.

Usage::

    python -m pitwall_sim.observe.alerts_check --seed 42            # Our Car on pole
    python -m pitwall_sim.observe.alerts_check --seed 7 --our NOR
"""

from __future__ import annotations

import argparse
import collections
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR
from pitwall_sim.observe.alerts import ALERT_TYPES, Alert, make_provider
from pitwall_sim.observe.engineer_view import EngineerViewBuilder
from pitwall_sim.race.engine import RaceEngine, RaceSetup


@dataclass
class AlertRun:
    """Every alert fired in one race, in order, and the engine at the flag."""

    alerts: list[Alert]
    engine: RaceEngine


def run_alerts(setup: RaceSetup, config_dir: Path = DEFAULT_CONFIG_DIR) -> AlertRun:
    """Race with Our Car = ``setup.our_driver_id``; collect each alert when it fires."""
    engine = RaceEngine(setup, config_dir)
    assert setup.our_driver_id is not None
    builder = EngineerViewBuilder(engine, setup.our_driver_id)
    provider = make_provider(
        engine.app.alerts, engine.track, engine.rules.power, engine.app.feed.rate_hz
    )
    seen: dict[str, Alert] = {}
    while not engine.finished:
        engine.tick()
        for alert in provider.update(builder.build()):
            seen.setdefault(alert.alert_id, alert)
    return AlertRun(sorted(seen.values(), key=lambda a: a.created_t), engine)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the alerts of one race and the count per type."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rules", default="2026_post_miami")
    parser.add_argument("--our", help="Our Car driver_id (default: the car on pole)")
    parser.add_argument("--laps", type=int)
    parser.add_argument("--fuel-kg", type=float, default=110.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    probe = RaceEngine(RaceSetup(rule_set_id=args.rules, seed=args.seed, laps=1))
    our = args.our or probe.driver_ids[int(probe._classification[0])]
    run = run_alerts(
        RaceSetup(rule_set_id=args.rules, seed=args.seed, laps=args.laps,
                  fuel_kg=args.fuel_kg, our_driver_id=our)
    )  # fmt: skip
    e = run.engine
    team = e.team_ids[e.driver_ids.index(our)]
    print(f"Our Car {our} ({team}), seed {args.seed}, {args.rules}: {len(run.alerts)} alerts")
    print("   t s  lap  type                rival  conf  our MJ  rival MJ  gap s   dv km/h  why")
    for a in run.alerts:
        ev = a.evidence
        head = f"{a.created_t:6.0f} {a.lap:4d}  {a.type:18s}  {a.rival:5s}  {a.confidence:4.2f}"
        print(f"{head}  {ev.our_mj:6.2f}  {_f(ev.rival_mj, 8)}  {_f(ev.gap_s, 6)}"
              f"  {_f(ev.dv_kmh, 8)}  {ev.branch or ''}")  # fmt: skip
    counts = collections.Counter(a.type for a in run.alerts)
    print("per type:", {t: counts.get(t, 0) for t in ALERT_TYPES})
    branches = collections.Counter((a.type, a.evidence.branch) for a in run.alerts
                                   if a.evidence.branch)  # fmt: skip
    print("per branch:", {f"{t} {b}": n for (t, b), n in sorted(branches.items())})
    return 0


def _f(value: float | None, width: int) -> str:
    return f"{value:{width}.2f}" if value is not None else " " * (width - 1) + "-"


if __name__ == "__main__":
    sys.exit(main())
