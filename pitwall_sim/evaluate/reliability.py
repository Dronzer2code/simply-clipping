"""Confidence honesty: hit rate per confidence bin, and a calibration table for an estimator.

    python -m pitwall_sim.evaluate.reliability --sc-out data/sc_out/simply_clipping \
        --batch data/exports/batch --seeds 1-5 --column raw_confidence

A "hit" is an estimate within ``RIGHT_TOL_MJ`` of the true battery (owner
spec O-1 proposal, 0.5 MJ). For an honest estimator, confidence 0.8 hits 80 %
of the time. With ``--column raw_confidence`` the tool fits the table that maps
the estimator's raw score to its hit rate (equal-count bins, made monotonic)
and prints it for the estimator's config; tune seeds only (1-5).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from pitwall_sim.evaluate import RIGHT_TOL_MJ, Run, _truth_at

Array = npt.NDArray[np.float64]


def hits(run_dir: Path, est: pd.DataFrame, column: str) -> pd.DataFrame:
    """``score`` (the column) and ``hit`` per scored estimate of one run."""
    j = _truth_at(Run.load(run_dir), est)
    j = j[j["confidence"] > 0.0]
    hit = (j["energy_mj"] - j["battery_mj"]).abs() <= RIGHT_TOL_MJ
    return pd.DataFrame({"score": j[column].to_numpy(dtype=np.float64), "hit": hit})


def monotone(y: Array, w: Array) -> Array:
    """Pool-adjacent-violators: the closest non-decreasing sequence (weighted)."""
    blocks: list[list[float]] = []  # [value, weight, count]
    for v, wt in zip(y, w, strict=True):
        blocks.append([float(v), float(wt), 1.0])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, n2 = blocks.pop()
            v1, w1, n1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2])
    return np.concatenate([np.full(int(n), v) for v, _, n in blocks])


def table(scores: Array, hit: npt.NDArray[np.bool_], bins: int) -> list[list[float]]:
    """``[[mean score, hit rate], ...]`` over equal-count bins, hit rate non-decreasing."""
    order = np.argsort(scores, kind="stable")
    parts = np.array_split(order, bins)
    x = np.array([scores[p].mean() for p in parts if p.size])
    y = np.array([hit[p].mean() for p in parts if p.size])
    n = np.array([p.size for p in parts if p.size], dtype=np.float64)
    return [
        [round(float(a), 4), round(float(b), 4)] for a, b in zip(x, monotone(y, n), strict=True)
    ]


def seeds_arg(value: str) -> set[int]:
    """``1-5`` or ``1,3``."""
    out: set[int] = set()
    for part in value.split(","):
        lo, _, hi = part.partition("-")
        out |= set(range(int(lo), int(hi or lo) + 1))
    return out


def collect(batch: Path, sc_out: Path, seeds: set[int], column: str) -> pd.DataFrame:
    """Scores and hits over every run of ``batch`` with a seed in ``seeds``."""
    frames = []
    for run_dir in sorted(p for p in batch.iterdir() if (p / "run.json").exists()):
        seed = int(run_dir.name.rsplit("_s", 1)[-1])
        est_file = sc_out / run_dir.name / "estimates.parquet"
        if seed in seeds and est_file.exists():
            frames.append(hits(run_dir, pd.read_parquet(est_file), column))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def report(data: pd.DataFrame, bins: int) -> dict[str, Any]:
    """Hit rate per stated-confidence bin (fixed 0.1 bins) and the calibration error."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    k = np.clip(np.digitize(data["score"], edges) - 1, 0, bins - 1)
    rows = []
    ece = 0.0
    for b in range(bins):
        m = k == b
        if m.any():
            conf, rate = float(data["score"][m].mean()), float(data["hit"][m].mean())
            rows.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(m.sum()),
                         "stated": round(conf, 3), "hit_rate": round(rate, 3)})  # fmt: skip
            ece += m.mean() * abs(conf - rate)
    return {"bins": rows, "ece": float(ece)}


def main(argv: Sequence[str] | None = None) -> int:
    """Print the reliability table, and with ``--column`` a calibration table."""
    parser = argparse.ArgumentParser(description="Confidence honesty and calibration")
    parser.add_argument("--sc-out", type=Path, required=True, help="data/sc_out/<estimator>")
    parser.add_argument("--batch", type=Path, default=Path("data/exports/batch"))
    parser.add_argument("--seeds", default="1-5")
    parser.add_argument("--column", default="confidence")
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args(argv)
    data = collect(args.batch, args.sc_out, seeds_arg(args.seeds), args.column)
    if data.empty:
        print("no estimates found")
        return 1
    rep = report(data, args.bins)
    print(f"{args.column}: {len(data)} estimates, hit = within {RIGHT_TOL_MJ} MJ, "
          f"ECE {rep['ece']:.3f}")  # fmt: skip
    for row in rep["bins"]:
        print(
            f"  {row['bin']}  n {row['n']:7d}  stated {row['stated']:.2f}"
            f"  hit {row['hit_rate']:.2f}"
        )
    if args.column != "confidence":
        cal = table(data["score"].to_numpy(), data["hit"].to_numpy(dtype=bool), args.bins)
        print("calibration:", cal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
