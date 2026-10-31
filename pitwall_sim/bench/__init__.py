"""Test bench for an external estimator (Simply Clipping): export -> plug-in -> score -> report.

    python -m pitwall_sim.bench --sc-module my_clipping --scenario all --seeds 6-10

For each scenario and seed: export the race (``pitwall_sim.export``; reused if
it exists), write the track's public layout, call the plug-in's
``run(feed_dir, out_dir, our, own_file, layout_file)``, score its files next
to the baselines (built-in Radar + built-in alerts, dumb ATTACK rule) and
write the report. Every step is skipped when its output already exists.

The plug-in is loaded by name (``importlib``); the simulator never imports it.
The same module can serve the live pit wall: ``create(cfg, track)`` with
``alerts.provider: external:<module>`` (docs/spec/SIMPLY_CLIPPING_BRIDGE.md).
"""

from __future__ import annotations

import importlib
import json
import logging
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitwall_sim.evaluate.batch import score_run, write_results
from pitwall_sim.export import export_race
from pitwall_sim.export.layout import layout
from pitwall_sim.export.scenarios import SCENARIOS, Scenario

logger = logging.getLogger(__name__)

PluginRun = Callable[[Path, Path, str | None, Path | None, Path], None]
"""``run(feed_dir, out_dir, our, own_file, layout_file)``."""


@dataclass(frozen=True)
class BenchSetup:
    """What to run."""

    module: str
    scenarios: tuple[Scenario, ...]
    seeds: tuple[int, ...]
    exports: Path = Path("data/exports/batch")
    sc_out: Path = Path("data/sc_out")
    name: str = ""
    """The plug-in's column in the report (default: the module name)."""
    report: Path | None = None
    """Default: ``<sc_out>/<name>/BENCH_REPORT.md``."""
    track: str = "suzuka"
    rules: str = "2026_post_miami"
    rerun: bool = False
    """Run the plug-in again on runs it already did (after changing it)."""


def plugin_run(module: str) -> PluginRun:
    """Load ``module`` by name and return its ``run`` function."""
    loaded = importlib.import_module(module)
    run = getattr(loaded, "run", None)
    if not callable(run):
        raise ValueError(f"{module} has no run(feed_dir, out_dir, our, own_file, layout_file)")
    fn: PluginRun = run
    return fn


def layout_file(track: str, folder: Path = Path("data/tracks")) -> Path:
    """Return the track's public layout JSON file (written once)."""
    path = folder / f"{track}_layout.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(layout(track)), encoding="utf-8")
    return path


def bench(setup: BenchSetup, say: Callable[[str], None] = print) -> Path:
    """Run the whole bench; return the report's path."""
    run = plugin_run(setup.module)
    name = setup.name or setup.module.rsplit(".", 1)[-1]
    report = setup.report or setup.sc_out / name / "BENCH_REPORT.md"
    track_layout = layout_file(setup.track)
    total = len(setup.scenarios) * len(setup.seeds)
    done = 0
    ran: set[str] = set()  # the report covers only the runs this bench ran
    started = time.perf_counter()
    for scenario in setup.scenarios:
        for seed in setup.seeds:
            done += 1
            run_dir = setup.exports / f"{scenario}_s{seed}"
            if not (run_dir / "run.json").exists():
                export_race(run_dir, seed, scenario, setup.track, setup.rules)
            info: dict[str, Any] = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            out = setup.sc_out / name / run_dir.name
            if setup.rerun or not (out / "estimates.parquet").exists():
                out.mkdir(parents=True, exist_ok=True)
                our = info.get("alert_pov")
                own = run_dir / "truth" / "ground_truth.parquet" if our else None
                t0 = time.perf_counter()
                run(run_dir / "feed", out, our, own, track_layout)
                took = time.perf_counter() - t0
                say(f"[{done}/{total}] {run_dir.name}: {name} ran in {took:.0f} s")
            else:
                say(f"[{done}/{total}] {run_dir.name}: {name} output exists")
            score_run(run_dir, setup.sc_out, rescore=setup.rerun, names={name})
            minutes = (time.perf_counter() - started) / 60.0
            header = (
                f"Bench: `{setup.module}` on {done}/{total} runs ({len(setup.seeds)} seeds x "
                f"{len(setup.scenarios)} scenarios, `{setup.exports.as_posix()}`), "
                f"{minutes:.0f} min. Mean ± spread over seeds; the built-in and dumb-rule "
                "columns are the baselines."
            )
            ran.add(run_dir.name)
            write_results(setup.exports, report, header, only=ran,
                          title=f"BENCH_REPORT — {name} vs the baselines")  # fmt: skip
            cda = cda_table(setup.exports, ran, name)
            if cda:
                with report.open("a", encoding="utf-8") as fh:
                    fh.write("\n" + cda)
    return report


def cda_table(exports: Path, runs: set[str], name: str) -> str:
    """Markdown: the plug-in's CdA fit error per car (%, mean over the runs; trap cars apart)."""
    per_car: dict[str, dict[str, list[float]]] = {}
    trap_cars: set[str] = set()
    for run in sorted(runs):
        path = exports / run / "evaluate_report.json"
        if not path.exists():
            continue
        cda = json.loads(path.read_text(encoding="utf-8")).get(name, {}).get("cda")
        if not cda:
            continue
        info = json.loads((exports / run / "run.json").read_text(encoding="utf-8"))
        trap = set(info.get("trap_cars") or [])
        for driver, modes in cda["per_car_pct"].items():
            key = f"{driver} (trap)" if driver in trap else driver
            if driver in trap:
                trap_cars.add(key)
            for mode, pct in modes.items():
                per_car.setdefault(key, {}).setdefault(mode, []).append(float(pct))
    if not per_car:
        return ""
    lines = [f"## CdA fit error per car ({name}, % vs true, mean ± spread over the runs)", "",
             "| car | straight | corner | runs |", "| --- | --- | --- | --- |"]  # fmt: skip

    def cell(vals: list[float]) -> str:
        if not vals:
            return "-"
        return f"{statistics.fmean(vals):+.1f} ± {statistics.pstdev(vals):.1f}"

    for car in sorted(per_car, key=lambda c: (c in trap_cars, c)):
        modes = per_car[car]
        n = max(len(v) for v in modes.values())
        lines.append(f"| {car} | {cell(modes.get('straight', []))} | "
                     f"{cell(modes.get('corner', []))} | {n} |")  # fmt: skip
    return "\n".join(lines) + "\n"


def scenarios_arg(value: str) -> tuple[Scenario, ...]:
    """``all`` or a comma-separated list of scenarios."""
    if value == "all":
        return SCENARIOS
    chosen = tuple(s.strip() for s in value.split(","))
    bad = [s for s in chosen if s not in SCENARIOS]
    if bad:
        raise ValueError(f"unknown scenario(s) {bad}; choose from {SCENARIOS}")
    return chosen  # type: ignore[return-value]


def seeds_arg(value: str) -> tuple[int, ...]:
    """``6-10``, ``3`` or ``1,4,7``."""
    seeds: list[int] = []
    for part in value.split(","):
        lo, _, hi = part.partition("-")
        seeds += range(int(lo), int(hi or lo) + 1)
    return tuple(seeds)
