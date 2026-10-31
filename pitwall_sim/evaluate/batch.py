"""Batch scores (sprint S-4): every export of a batch, mean +- spread per scenario.

    python -m pitwall_sim.evaluate.batch --batch data/exports/batch \
        --write docs/results/SC_RESULTS.md

A batch folder holds one export per ``<scenario>_s<seed>``. Each run is scored
once (``evaluate_report.json`` in the run folder; skipped when it exists): the
baselines (built-in Radar + built-in alerts, dumb ATTACK rule) and every
estimator whose outputs are in ``<sc_out>/<name>/<run>/`` (``estimates.parquet``,
``alerts.parquet``, optional ``cda_fit.json``; ``python -m pitwall_sim.bench``
writes them). Seeds 1-5 are the tune set, 6-10 the test set (owner, day 7):
reported apart.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pitwall_sim.evaluate import evaluate

logger = logging.getLogger(__name__)

TUNE_SEEDS = range(1, 6)
TEST_SEEDS = range(6, 11)
REPORT = "evaluate_report.json"
DISPLAY = {"simply_clipping": "Simply Clipping"}
KEEP_SECTION = "## REAL RACE"
"""A section of the results file that a rewrite keeps (written by hand, not by the batch)."""
"""Column titles for estimator folders."""
Getter = Callable[[dict[str, Any]], Any]
METRICS: tuple[tuple[str, Getter, bool], ...] = (
    ("energy MAE MJ", lambda r: r["energy"]["overall"]["mae_mj"], False),
    ("energy p90 MJ", lambda r: r["energy"]["overall"]["p90_mj"], False),
    ("MAE conf>=0.5", lambda r: r["energy"]["confidence_ge_0.5"]["mae_mj"], False),
    ("within 0.5 MJ", lambda r: r["energy"]["honesty"]["hit_rate"], True),
    ("confidence ECE", lambda r: r["energy"]["honesty"]["ece"], True),
    ("CLIP precision", lambda r: r["state"]["clip_precision"], True),
    ("CLIP recall", lambda r: r["state"]["clip_recall"], True),
    ("false CLIP in taper", lambda r: r["state"]["false_clip_share_during_taper"], True),
    ("CdA abs err straight %", lambda r: r["cda"]["mean_abs_pct_straight"], False),
    ("CdA abs err corner %", lambda r: r["cda"]["mean_abs_pct_corner"], False),
    ("CdA trap err straight %", lambda r: r["cda"]["trap_mean_pct_straight"], False),
    ("ATTACK recall", lambda r: r["alerts"]["ATTACK"]["recall"], True),
    ("ATTACK precision", lambda r: r["alerts"]["ATTACK"]["precision"], True),
    ("ATTACK right", lambda r: r["alerts"]["ATTACK"]["right_per_truth"], True),
    ("ATTACK lead s (median)", lambda r: r["alerts"]["ATTACK"]["lead_median_s"], False),
    ("DEFEND recall", lambda r: r["alerts"]["DEFEND"]["recall"], True),
    ("DEFEND precision", lambda r: r["alerts"]["DEFEND"]["precision"], True),
    ("DEFEND right", lambda r: r["alerts"]["DEFEND"]["right_per_truth"], True),
    ("DEFEND lead s (median)", lambda r: r["alerts"]["DEFEND"]["lead_median_s"], False),
    ("REPASS recall", lambda r: r["alerts"]["REPASS_RISK"]["recall"], True),
    ("REPASS precision", lambda r: r["alerts"]["REPASS_RISK"]["precision"], True),
    ("CLOSING recall", lambda r: r["alerts"]["CLOSING_SPEED_RISK"]["recall"], True),
    ("CLOSING precision", lambda r: r["alerts"]["CLOSING_SPEED_RISK"]["precision"], True),
    ("alerts per race", lambda r: r["alerts"]["alerts"], False),
    ("incident pass", lambda r: r["incident"]["pass"], True),
)  # fmt: skip


def run_dirs(batch: Path) -> list[Path]:
    """Finished exports of a batch (those with a run.json)."""
    return sorted(p.parent for p in batch.glob("*/run.json"))


def score_run(
    run_dir: Path, sc_out: Path | None = None, rescore: bool = False,
    names: set[str] | None = None, rescore_baselines: bool = False,
) -> dict[str, Any]:  # fmt: skip
    """Score one export (cached in its ``evaluate_report.json``; SC versions added as found).

    ``rescore`` scores the estimators again (only those in ``names``, if given); the
    baselines are scored again only with ``rescore_baselines`` or when missing.
    """
    from pitwall_sim.evaluate.__main__ import baselines

    path = run_dir / REPORT
    reports: dict[str, Any] = {}
    if path.exists():
        reports = json.loads(path.read_text(encoding="utf-8"))
    if rescore_baselines or "built-in" not in reports:
        reports.update(baselines(run_dir))
    if sc_out is not None and sc_out.exists():
        for version in sorted(p for p in sc_out.iterdir() if p.is_dir()):
            out = version / run_dir.name
            name = version.name
            if names is not None and name not in names:
                continue
            if not (out / "estimates.parquet").exists() or (name in reports and not rescore):
                continue
            alerts = out / "alerts.parquet"
            cda = out / "cda_fit.json"
            reports[name] = evaluate(
                run_dir, pd.read_parquet(out / "estimates.parquet"),
                pd.read_parquet(alerts) if alerts.exists() else None,
                json.loads(cda.read_text(encoding="utf-8")) if cda.exists() else None,
            )  # fmt: skip
    path.write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
    return reports


def _value(report: dict[str, Any], get: Getter) -> float:
    try:
        v = get(report)
    except (KeyError, TypeError):
        return float("nan")
    if v is None:
        return float("nan")
    return float(v)


def aggregate(batch: Path, only: set[str] | None = None) -> dict[str, Any]:
    """Mean, spread and count per split, scenario, estimator and metric."""
    table: dict[str, Any] = {}
    for run_dir in run_dirs(batch):
        if only is not None and run_dir.name not in only:
            continue
        path = run_dir / REPORT
        if not path.exists():
            continue
        info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        seed, scenario = int(info["seed"]), str(info["scenario"])
        split = "tune" if seed in TUNE_SEEDS else "test" if seed in TEST_SEEDS else "other"
        produced = bool(info.get("targets", {}).get("produced", True))
        for name, report in json.loads(path.read_text(encoding="utf-8")).items():
            cell = table.setdefault(split, {}).setdefault(scenario, {}).setdefault(name, {})
            cell.setdefault("_seeds", []).append(seed)
            cell.setdefault("_target_produced", []).append(produced)
            for label, get, _ in METRICS:
                cell.setdefault(label, []).append(_value(report, get))
    out: dict[str, Any] = {}
    for split, scenarios in table.items():
        for scenario, names in scenarios.items():
            for name, cell in names.items():
                stats: dict[str, Any] = {}
                for label, _, _ in METRICS:
                    vals = np.asarray(cell[label], dtype=np.float64)
                    vals = vals[np.isfinite(vals)]
                    stats[label] = {
                        "mean": float(vals.mean()) if vals.size else None,
                        "spread": float(vals.std()) if vals.size > 1 else None,
                        "n": int(vals.size),
                    }  # fmt: skip
                stats["seeds"] = sorted(cell["_seeds"])
                stats["target_produced"] = int(sum(cell["_target_produced"]))
                out.setdefault(split, {}).setdefault(scenario, {})[name] = stats
    return out


def _cell(s: dict[str, Any], pct: bool) -> str:
    if s["mean"] is None:
        return "-"
    scale = 100.0 if pct else 1.0
    unit = "%" if pct else ""
    text = f"{scale * s['mean']:.0f}{unit}" if pct else f"{s['mean']:.2f}"
    if s["spread"] is not None:
        text += f" ± {scale * s['spread']:.0f}{unit}" if pct else f" ± {s['spread']:.2f}"
    return text


def markdown(
    agg: dict[str, Any],
    header: str = "",
    title: str = "SC_RESULTS.md — Simply Clipping test bench results",
) -> str:
    """Return the results tables (one per split and scenario; columns = estimators)."""
    lines = [f"# {title}", ""]
    if header:
        lines += [header, ""]
    for split in ("test", "tune", "other"):
        if split not in agg:
            continue
        seeds = {"test": " (seeds 6-10)", "tune": " (seeds 1-5)"}.get(split, "")
        lines += [f"## {split.upper()} SET{seeds}", ""]
        for scenario, names in sorted(agg[split].items()):
            cols = list(names)
            first = names[cols[0]]
            seeds = ", ".join(str(s) for s in first["seeds"])
            lines += [f"### {scenario} (seeds {seeds}; target produced in "
                      f"{first['target_produced']}/{len(first['seeds'])})", ""]  # fmt: skip
            lines.append("| metric | " + " | ".join(DISPLAY.get(c, c) for c in cols) + " |")
            lines.append("| --- | " + " | ".join("---" for _ in cols) + " |")
            for label, _, pct in METRICS:
                lines.append(f"| {label} | " + " | ".join(_cell(names[c][label], pct)
                                                         for c in cols) + " |")  # fmt: skip
            lines.append("")
    return "\n".join(lines)


def write_results(
    batch: Path, md_path: Path, header: str = "", only: set[str] | None = None,
    title: str = "SC_RESULTS.md — Simply Clipping test bench results",
) -> None:  # fmt: skip
    """Aggregate a batch (or only the runs named in ``only``) and write the markdown.

    The JSON (``evaluate_batch_report.json``, or ``<report>.json`` with ``only``)
    goes next to the batch / the report.
    """
    agg = aggregate(batch, only)
    json_path = (
        md_path.with_suffix(".json") if only is not None else batch / "evaluate_batch_report.json"
    )
    json_path.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    keep = ""  # a hand-written REAL RACE section (Simply Clipping SC-5) survives the rewrite
    if md_path.exists():
        old = md_path.read_text(encoding="utf-8")
        if "\n" + KEEP_SECTION in old:
            keep = "\n" + old[old.index("\n" + KEEP_SECTION) + 1 :]
    md_path.write_text(markdown(agg, header, title) + keep, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Score every export of a batch and write the results tables."""
    parser = argparse.ArgumentParser(description="Score a batch of exports (S-4)")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--sc-out", type=Path, default=Path("data/sc_out"))
    parser.add_argument("--write", type=Path, default=Path("docs/results/SC_RESULTS.md"))
    parser.add_argument("--rescore", action="store_true", help="score the estimators again")
    parser.add_argument("--rescore-baselines", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    for run_dir in run_dirs(args.batch):
        score_run(run_dir, args.sc_out, args.rescore, rescore_baselines=args.rescore_baselines)
    write_results(args.batch, args.write)
    print(f"{len(run_dirs(args.batch))} runs -> {args.write}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
