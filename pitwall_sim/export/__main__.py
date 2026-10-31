"""CLI for the race export (sprints S-1, S-4).

python -m pitwall_sim.export --seed 42 --scenario normal --out data/exports/suzuka_normal_s42
python -m pitwall_sim.export --seed 42 --scenario all --out data/exports/s42
python -m pitwall_sim.export --batch 5 --scenario all --out data/exports/batch

``--batch N`` (sprint S-4) runs seeds 1..N (or ``--seeds 6-10``) x the scenarios
into ``<out>/<scenario>_s<seed>``, skips runs that already have a run.json
(resumable), scores each run (baselines) and rewrites ``--results``
(docs/results/SC_RESULTS.md) after every run, so a stopped batch still has numbers.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from pitwall_sim.export import export_race
from pitwall_sim.export.scenarios import SCENARIOS


def main(argv: Sequence[str] | None = None) -> int:
    """Export one scenario (or all of them, one folder each), or run a batch."""
    parser = argparse.ArgumentParser(description="Race export for Simply Clipping (sprint S-1)")
    parser.add_argument("--track", default="suzuka")
    parser.add_argument("--rules", default="2026_post_miami")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario", default="normal", choices=[*SCENARIOS, "all"])
    parser.add_argument("--laps", type=int, help="race distance (default: the track's)")
    parser.add_argument("--fuel-kg", type=float, default=110.0)
    parser.add_argument("--out", type=Path, help="default: data/exports/<track>_<scenario>_s<seed>")
    parser.add_argument("--batch", type=int, help="run seeds 1..N x the scenarios (S-4)")
    parser.add_argument("--seeds", help="batch seeds as a range, e.g. 6-10")
    parser.add_argument("--results", type=Path, default=Path("docs/results/SC_RESULTS.md"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.batch or args.seeds:
        return batch(args)
    todo = SCENARIOS if args.scenario == "all" else (args.scenario,)
    for scenario in todo:
        out = args.out or Path("data/exports") / f"{args.track}_{scenario}_s{args.seed}"
        if args.scenario == "all" and args.out is not None:
            out = args.out / scenario
        info = export_race(out, args.seed, scenario, args.track, args.rules, args.laps,
                           args.fuel_kg)  # fmt: skip
        t = info["targets"]
        print(f"{scenario:14s} -> {out}  ({info['laps']} laps, {info['wall_s']:.0f} s)  "
              f"target produced: {t['produced']}  ({t['target']})")  # fmt: skip
    return 0


def batch(args: argparse.Namespace) -> int:
    """Run (or resume) a batch, scoring and rewriting the results after every run."""
    from pitwall_sim.evaluate.batch import score_run, write_results

    if args.seeds:
        lo, _, hi = args.seeds.partition("-")
        seeds = list(range(int(lo), int(hi or lo) + 1))
    else:
        seeds = list(range(1, args.batch + 1))
    todo = SCENARIOS if args.scenario == "all" else (args.scenario,)
    out_root = args.out or Path("data/exports/batch")
    total = len(seeds) * len(todo)
    started = time.perf_counter()
    done = 0
    for scenario in todo:  # a whole scenario first: partial results cover it
        for seed in seeds:
            out = out_root / f"{scenario}_s{seed}"
            done += 1
            if (out / "run.json").exists():
                print(f"[{done}/{total}] {scenario} seed {seed}: exists, skipped", flush=True)
            else:
                info = export_race(out, seed, scenario, args.track, args.rules, args.laps,
                                   args.fuel_kg)  # fmt: skip
                print(f"[{done}/{total}] {scenario} seed {seed}: {info['wall_s']:.0f} s, "
                      f"target produced {info['targets']['produced']}", flush=True)  # fmt: skip
            score_run(out)
            minutes = (time.perf_counter() - started) / 60.0
            header = (
                f"Batch `{out_root.as_posix()}`: {done}/{total} runs ({len(seeds)} seeds x "
                f"{len(todo)} scenarios), {minutes:.0f} min this session. Mean ± spread over "
                "seeds. The built-in column is the target Simply Clipping must beat."
            )
            write_results(out_root, args.results, header)
    return 0


if __name__ == "__main__":
    sys.exit(main())
