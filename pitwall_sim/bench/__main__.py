"""CLI: python -m pitwall_sim.bench --sc-module <module> --scenario all --seeds 6-10."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pitwall_sim.bench import BenchSetup, bench, scenarios_arg, seeds_arg


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bench and print where the report is."""
    parser = argparse.ArgumentParser(
        description="Export -> your estimator -> scorer -> report "
        "(docs/spec/SIMPLY_CLIPPING_BRIDGE.md)"
    )
    parser.add_argument("--sc-module", required=True, help="your package/module, e.g. my_clipping")
    parser.add_argument("--scenario", default="all", help="all, or e.g. normal,repass")
    parser.add_argument("--seeds", default="6-10", help="e.g. 6-10 (test set) or 1-5 (tune set)")
    parser.add_argument("--exports", type=Path, default=Path("data/exports/batch"))
    parser.add_argument("--sc-out", type=Path, default=Path("data/sc_out"))
    parser.add_argument("--name", default="", help="your column in the report")
    parser.add_argument("--report", type=Path, help="default: <sc-out>/<name>/BENCH_REPORT.md")
    parser.add_argument("--rerun", action="store_true", help="run your module again (changed it?)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if "." not in sys.path:
        sys.path.insert(0, ".")  # a module next to the repository root
    setup = BenchSetup(
        args.sc_module, scenarios_arg(args.scenario), seeds_arg(args.seeds), args.exports,
        args.sc_out, args.name, args.report, rerun=args.rerun,
    )  # fmt: skip
    report = bench(setup, lambda line: print(line, flush=True))
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
