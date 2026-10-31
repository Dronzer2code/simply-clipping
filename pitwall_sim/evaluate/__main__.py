"""CLI for the scorer (sprint S-3).

    python -m pitwall_sim.evaluate --run data/exports/<run_id> --baseline
    python -m pitwall_sim.evaluate --run data/exports/<run_id> --estimates est.parquet \
        --alerts al.parquet

``--baseline`` scores the sim's built-in Radar (on the exported feed), the
built-in simply_clipping_lite alerts (recorded for the run's point-of-view car)
and the dumb rule "car ahead slower on this straight -> ATTACK". Prints a table
and writes ``evaluate_report.json`` into the run folder (or ``--report``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from pitwall_sim.evaluate import ALERT_TYPES, evaluate
from pitwall_sim.evaluate.baseline import builtin_radar, dumb_alerts


def baselines(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Score the built-in Radar + alerts and the dumb rule on ``run_dir``."""
    cache = run_dir / "baseline" / "builtin_estimates.parquet"
    if cache.exists():
        est = pd.read_parquet(cache)
    else:
        est = builtin_radar(run_dir)
        cache.parent.mkdir(parents=True, exist_ok=True)
        est.to_parquet(cache, index=False)
    info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    alerts_file = run_dir / "baseline" / "builtin_alerts.parquet"
    builtin = pd.read_parquet(alerts_file) if alerts_file.exists() else None
    out = {"built-in": evaluate(run_dir, est, builtin)}
    if info.get("alert_pov"):
        out["dumb rule"] = evaluate(run_dir, None, dumb_alerts(run_dir, info["alert_pov"]))
    return out


def _f(x: Any, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "-"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return str(x)
    return f"{100 * x:.0f}%" if pct else f"{x:.2f}"


def table(reports: dict[str, dict[str, Any]]) -> list[str]:
    """Return the printed comparison table, one column per estimator."""
    names = list(reports)
    rows: list[tuple[str, list[str]]] = []

    def add(label: str, get: Any, pct: bool = False) -> None:
        vals = []
        for n in names:
            try:
                vals.append(_f(get(reports[n]), pct))
            except (KeyError, TypeError):
                vals.append("-")
        rows.append((label, vals))

    add("energy MAE MJ", lambda r: r["energy"]["overall"]["mae_mj"])
    add("energy p90 MJ", lambda r: r["energy"]["overall"]["p90_mj"])
    add("energy bias MJ", lambda r: r["energy"]["overall"]["bias_mj"])
    add("MAE, conf >= 0.5", lambda r: r["energy"]["confidence_ge_0.5"]["mae_mj"])
    add("MAE, conf < 0.5", lambda r: r["energy"]["confidence_lt_0.5"]["mae_mj"])
    add("state accuracy", lambda r: r["state"]["accuracy"], True)
    add("CLIP precision", lambda r: r["state"]["clip_precision"], True)
    add("CLIP recall", lambda r: r["state"]["clip_recall"], True)
    add("false CLIP in taper", lambda r: r["state"]["false_clip_share_during_taper"], True)
    for kind in ALERT_TYPES:
        add(f"{kind} alerts", lambda r, k=kind: r["alerts"][k]["alerts"])
        add(f"{kind} recall", lambda r, k=kind: r["alerts"][k]["recall"], True)
        add(f"{kind} precision", lambda r, k=kind: r["alerts"][k]["precision"], True)
        add(f"{kind} lead median s", lambda r, k=kind: r["alerts"][k]["lead_median_s"])
    for kind in ("ATTACK", "DEFEND"):
        add(f"{kind} right per truth", lambda r, k=kind: r["alerts"][k]["right_per_truth"], True)
    add("incident pass", lambda r: r["incident"]["pass"])
    width = max(len(label) for label, _ in rows)
    lines = [" " * width + "  " + "  ".join(f"{n:>12s}" for n in names)]
    lines += [f"{label:<{width}s}  " + "  ".join(f"{v:>12s}" for v in vals) for label, vals in rows]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Score estimates / alerts (and the baselines) on one export."""
    parser = argparse.ArgumentParser(description="Score battery estimates and alerts (S-3)")
    parser.add_argument("--run", type=Path, required=True, help="export folder")
    parser.add_argument("--estimates", type=Path, help="estimates.parquet")
    parser.add_argument("--alerts", type=Path, help="alerts.parquet")
    parser.add_argument("--cda-fit", type=Path, help="cda_fit.json")
    parser.add_argument("--name", default="estimator", help="column name for --estimates")
    parser.add_argument("--baseline", action="store_true", help="also score the baselines")
    parser.add_argument("--report", type=Path, help="default: <run>/evaluate_report.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    reports: dict[str, dict[str, Any]] = {}
    if args.estimates or args.alerts or args.cda_fit:
        reports[args.name] = evaluate(
            args.run,
            pd.read_parquet(args.estimates) if args.estimates else None,
            pd.read_parquet(args.alerts) if args.alerts else None,
            json.loads(args.cda_fit.read_text(encoding="utf-8")) if args.cda_fit else None,
        )  # fmt: skip
    if args.baseline or not reports:
        reports.update(baselines(args.run))
    print("\n".join(table(reports)))
    report = args.report or args.run / "evaluate_report.json"
    report.write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
