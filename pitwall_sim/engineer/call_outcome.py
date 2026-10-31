"""Does a call change the race? Fork at an alert: answer it vs ignore it (sprint A-5).

For each seed, race until Our Car's first alert of a type, snapshot, then run
paired forks for ``laps`` of Our Car: one answers with the option, one ignores
the alert. Each pair shares a fresh overtake RNG stream (``variants`` pairs per
alert, common random numbers), so the only difference within a pair is the call;
the reseeding happens in these analysis forks only, never in a race.

DEFEND: kept = Our Car still ahead of the rival. ATTACK: passed = Our Car ahead
of the rival (which was ahead when the alert fired).

    python -m pitwall_sim.engineer.call_outcome --type DEFEND --seeds 20
    python -m pitwall_sim.engineer.call_outcome --type ATTACK --seeds 20
    python -m pitwall_sim.engineer.call_outcome --overtakes 5     # overtakes per race
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR
from pitwall_sim.engineer.calls import CallRunner, options
from pitwall_sim.engineer.commands import CommandType, EngineerCommand, make_command
from pitwall_sim.observe.alerts import Alert, AlertType, make_provider
from pitwall_sim.observe.engineer_view import EngineerView, EngineerViewBuilder
from pitwall_sim.race.engine import RaceEngine, RaceSetup

MAX_WAIT_LAPS = 50
#: Midfield cars used as Our Car in turn (alerts need fights).
DEFAULT_CARS = ("GAS", "ALO", "HUL", "OCO", "LAW", "ALB", "BEA", "SAI")


@dataclass(frozen=True)
class Outcome:
    """One alert: how often Our Car ended ahead of the rival, answered vs ignored."""

    seed: int
    our: str
    alert: Alert
    ahead_answered: int
    ahead_ignored: int
    variants: int


def _ahead(engine: RaceEngine, a: str, b: str) -> bool:
    rank = {engine.driver_ids[int(i)]: k for k, i in enumerate(engine._classification)}
    return rank[a] < rank[b]


def _follow(engine: RaceEngine, our: str, laps: int, runner: CallRunner | None) -> None:
    builder = EngineerViewBuilder(engine, our)
    i = engine.driver_ids.index(our)
    end = int(engine.st.lap[i]) + laps
    while int(engine.st.lap[i]) < end and not engine.finished:
        engine.tick()
        if runner is not None and runner.pending:
            runner.update(builder.build())


def first_alert(
    seed: int, our: str, kind: AlertType, min_lap: int = 1,
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[RaceEngine, Alert, EngineerView] | None:  # fmt: skip
    """Race ``seed`` until Our Car's first ``kind`` alert from lap ``min_lap`` on."""
    engine = RaceEngine(RaceSetup(seed=seed, fuel_kg=110.0, our_driver_id=our), config_dir)
    builder = EngineerViewBuilder(engine, our)
    provider = make_provider(
        engine.app.alerts, engine.track, engine.rules.power, engine.app.feed.rate_hz
    )
    i = engine.driver_ids.index(our)
    while not engine.finished and engine.st.lap[i] < MAX_WAIT_LAPS:
        engine.tick()
        view = builder.build()
        fired = provider.update(view)
        if engine.st.lap[i] + 1 < min_lap:
            continue
        alert = next((a for a in fired if a.type == kind), None)
        if alert is not None:
            return engine, alert, view
    return None


def _issuer(engine: RaceEngine) -> Callable[[CommandType, dict[str, object]], str | None]:
    def issue(kind: CommandType, params: dict[str, object]) -> str | None:
        cmd = make_command(kind, params, engine.command_context(), engine.app.engineer,
                           engine.t, engine.app.radio.radio_latency_s)  # fmt: skip
        if isinstance(cmd, EngineerCommand):
            engine.submit(cmd)
            return None
        return cmd.reason

    return issue


def outcome(
    seed: int, our: str, kind: AlertType, key: int = 1, laps: int = 2, min_lap: int = 1,
    variants: int = 10, config_dir: Path = DEFAULT_CONFIG_DIR,
) -> Outcome | None:  # fmt: skip
    """Paired forks at Our Car's first ``kind`` alert; None if the race has none."""
    found = first_alert(seed, our, kind, min_lap, config_dir)
    if found is None:
        return None
    engine, alert, view = found
    snap = engine.snapshot()
    option = next(o for o in options(alert, view, engine.track) if o.key == key)
    ahead = [0, 0]
    for k in range(variants):
        for arm, answer in enumerate((True, False)):
            fork = RaceEngine.from_snapshot(snap)
            fork.overtake.rng = np.random.default_rng([seed, k])  # same draws in both arms
            runner = None
            if answer:
                runner = CallRunner(_issuer(fork))
                runner.start(option, view)
            _follow(fork, our, laps, runner)
            ahead[arm] += _ahead(fork, our, alert.rival)
    return Outcome(seed, our, alert, ahead[0], ahead[1], variants)


def overtakes_per_race(seed: int, config_dir: Path = DEFAULT_CONFIG_DIR) -> int:
    """Successful on-track passes (blue flags excluded) in one full race."""
    engine = RaceEngine(RaceSetup(seed=seed, fuel_kg=110.0), config_dir)
    engine.run()
    return sum(1 for e in engine.overtake.events if e.success and not e.blue_flag)


def main(argv: Sequence[str] | None = None) -> int:
    """Print answered vs ignored over seeds (or overtakes per race)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--type", default="DEFEND")
    parser.add_argument("--our", help="Our Car (default: midfield cars in turn)")
    parser.add_argument("--option", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--laps", type=int, default=2)
    parser.add_argument("--min-lap", type=int, default=1)
    parser.add_argument("--variants", type=int, default=10)
    parser.add_argument("--overtakes", type=int, help="count overtakes in this many races")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.overtakes:
        counts = [overtakes_per_race(s, args.config_dir) for s in range(args.overtakes)]
        print(f"overtakes per race: {counts}  mean {np.mean(counts):.1f}")
        return 0
    found = []
    for s in range(args.seeds):
        our = args.our or DEFAULT_CARS[s % len(DEFAULT_CARS)]
        r = outcome(
            s, our, args.type, args.option, args.laps, args.min_lap, args.variants, args.config_dir
        )
        if r is None:
            print(f"seed {s:2d}  {our}: no {args.type} alert")
            continue
        found.append(r)
        a_ = r.alert
        head = f"seed {s:2d}  {our} vs {a_.rival} lap {a_.lap:2d} conf {a_.confidence:.2f}"
        print(f"{head}  ahead: answered {r.ahead_answered}/{r.variants}"
              f"  ignored {r.ahead_ignored}/{r.variants}")  # fmt: skip
    n = sum(r.variants for r in found)
    if n:
        a = sum(r.ahead_answered for r in found) / n
        b = sum(r.ahead_ignored for r in found) / n
        print(f"{len(found)} alerts x {args.variants} forks: Our Car ahead {a:.0%} answered vs "
              f"{b:.0%} ignored ({100 * (a - b):+.0f} points)")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
