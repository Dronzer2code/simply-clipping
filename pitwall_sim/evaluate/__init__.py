"""Scorer for battery estimates and alerts on an export (sprint S-3, SPRINT.md Parts 1, 5).

Sprint texts: docs/planning/SPRINT.md.

Contract (docs/spec/SIMPLY_CLIPPING_BRIDGE.md): ``estimates.parquet`` (driver, time_s,
energy_mj, state, confidence; optional since_anchor_s), ``alerts.parquet``
(time_s, lap, type, car_a = the car the alert is for, car_b = the rival,
confidence; optional branch) and optional ``cda_fit.json``
({driver: {"straight": m2, "corner": m2}}).

Metrics:

- energy: MAE, p90 and bias vs the true battery; by Energy Mode; confidence
  >= 0.5 vs < 0.5 (is confidence honest?); by time since the last anchor (drift).
- state: confusion matrix vs ``state_true``; CLIP precision / recall; false
  CLIPs while the MGU-K is limited by the speed taper.
- CdA: fitted vs true per car (% error); the cda_trap cars apart.
- alerts, per type: recall on true events (an alert for the same pair within
  ``window_laps`` before the event), lead time (median, share >= 5 s, share
  < 1 s = useless), precision (a matching event within ``window_laps`` after the
  alert), alerts per race (flagged over 100), and "right per Ground Truth" for
  ATTACK / DEFEND (the rival's true battery below / above the car's own).
- incidents (repass, closing_speed scenarios): did an alert for the target pair
  fire before the event?

Events per alert type: ATTACK - car_a passes car_b; DEFEND - car_b passes car_a;
RE-PASS RISK - car_a passed car_b and was re-passed (the re-pass is the event);
CLOSING-SPEED RISK - a closing-speed episode between the two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

STATES = ("DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE")
ALERT_TYPES = ("ATTACK", "DEFEND", "REPASS_RISK", "CLOSING_SPEED_RISK")
WINDOW_LAPS = 2.0
GOOD_LEAD_S, USELESS_LEAD_S = 5.0, 1.0
ALERTS_PER_RACE_FLAG = 100
ANCHOR_BINS = (0.0, 30.0, 60.0, 120.0, 300.0, np.inf)
RIGHT_TOL_MJ = 0.5
"""An estimate within this of the true battery is a hit (owner spec O-1 proposal)."""
CONF_BINS = 10


@dataclass
class Run:
    """An export folder's Ground Truth."""

    path: Path
    info: dict[str, Any]
    truth: pd.DataFrame
    events: pd.DataFrame
    car_params: dict[str, Any]
    lap_s: float
    """Median lap time (the alert windows' lap)."""

    @classmethod
    def load(cls, path: Path) -> Run:
        """Read ``run.json`` and ``truth/`` of an export."""
        info = json.loads((path / "run.json").read_text(encoding="utf-8"))
        truth = pd.read_parquet(path / "truth" / "ground_truth.parquet", columns=[
            "driver", "time_s", "battery_mj", "energy_mode", "state_true", "taper_active",
        ])  # fmt: skip
        events = pd.read_parquet(path / "truth" / "events.parquet")
        params = json.loads((path / "truth" / "car_params.json").read_text(encoding="utf-8"))
        laps = pd.read_parquet(path / "feed" / "laps.parquet")
        lap_s = float(laps["LapTime"].dt.total_seconds().median()) if len(laps) else 100.0
        return cls(path, info, truth, events, params, lap_s)


def _truth_at(run: Run, frame: pd.DataFrame) -> pd.DataFrame:
    """Return each row joined with the truth sample at or just before its (driver, time_s)."""
    out = []
    for driver, rows in frame.groupby("driver", sort=False):
        t = run.truth[run.truth["driver"] == driver]
        if t.empty:
            continue
        k = np.clip(np.searchsorted(t["time_s"].to_numpy(), rows["time_s"].to_numpy(),
                                    side="right") - 1, 0, len(t) - 1)  # fmt: skip
        picked = t.iloc[k].reset_index(drop=True)
        picked.index = rows.index
        out.append(rows.join(picked.drop(columns=["driver", "time_s"]), how="inner"))
    return pd.concat(out) if out else frame.iloc[0:0]


def _stats(err: pd.Series) -> dict[str, float]:
    a = err.abs()
    return {"n": int(a.size), "mae_mj": float(a.mean()) if a.size else float("nan"),
            "p90_mj": float(a.quantile(0.9)) if a.size else float("nan"),
            "bias_mj": float(err.mean()) if a.size else float("nan")}  # fmt: skip


def score_energy(run: Run, est: pd.DataFrame) -> dict[str, Any]:
    """Energy error of the estimates vs the true battery."""
    j = _truth_at(run, est)
    j = j[j["confidence"] > 0.0]  # an estimate the estimator calls unknown is not scored
    err = j["energy_mj"] - j["battery_mj"]
    out: dict[str, Any] = {"overall": _stats(err)}
    out["by_energy_mode"] = {m: _stats(err[j["energy_mode"] == m])
                             for m in sorted(j["energy_mode"].unique())}  # fmt: skip
    out["confidence_ge_0.5"] = _stats(err[j["confidence"] >= 0.5])
    out["confidence_lt_0.5"] = _stats(err[j["confidence"] < 0.5])
    out["honesty"] = _honesty(j["confidence"].to_numpy(dtype=np.float64),
                              (err.abs() <= RIGHT_TOL_MJ).to_numpy())  # fmt: skip
    if "since_anchor_s" in j and j["since_anchor_s"].notna().any():
        bins = pd.cut(j["since_anchor_s"], ANCHOR_BINS, right=False)
        out["by_time_since_anchor_s"] = {
            str(b): _stats(err[bins == b]) for b in bins.cat.categories
        }
    out["per_car_mae_mj"] = {str(d): float(e.abs().mean()) for d, e in err.groupby(j["driver"])}
    return out


def _honesty(conf: np.ndarray, hit: np.ndarray) -> dict[str, Any]:
    """Is confidence honest? Hit rate (within ``RIGHT_TOL_MJ``) per 0.1 bin; ECE."""
    if conf.size == 0:
        return {"hit_rate": float("nan"), "ece": float("nan"), "bins": []}
    k = np.clip((conf * CONF_BINS).astype(int), 0, CONF_BINS - 1)
    bins, ece = [], 0.0
    for b in range(CONF_BINS):
        m = k == b
        if m.any():
            stated, rate = float(conf[m].mean()), float(hit[m].mean())
            bins.append({"bin": b / CONF_BINS, "n": int(m.sum()), "stated": stated, "hit": rate})
            ece += float(m.mean()) * abs(stated - rate)
    return {"hit_rate": float(hit.mean()), "ece": ece, "bins": bins}


def score_states(run: Run, est: pd.DataFrame) -> dict[str, Any]:
    """Estimated state vs ``state_true``."""
    j = _truth_at(run, est)
    j = j[j["state"].isin(STATES)]
    matrix = pd.crosstab(j["state_true"], j["state"]).reindex(index=STATES, columns=STATES,
                                                              fill_value=0)  # fmt: skip
    clip_est, clip_true = j["state"] == "CLIP", j["state_true"] == "CLIP"
    taper = j["taper_active"] & ~clip_true
    return {
        "confusion": {
            str(k): {str(c): int(v) for c, v in row.items()} for k, row in matrix.iterrows()
        },  # fmt: skip
        "accuracy": float((j["state"] == j["state_true"]).mean()) if len(j) else float("nan"),
        "clip_precision": float((clip_est & clip_true).sum() / max(clip_est.sum(), 1)),
        "clip_recall": float((clip_est & clip_true).sum() / max(clip_true.sum(), 1)),
        "false_clip_during_taper": int((clip_est & taper).sum()),
        "false_clip_share_during_taper": float((clip_est & taper).sum() / max(taper.sum(), 1)),
    }


def score_cda(run: Run, cda_fit: dict[str, Any]) -> dict[str, Any]:
    """Fitted CdA vs the true one per car (% error); trap cars apart."""
    rows = {}
    for driver, fit in cda_fit.items():
        true = run.car_params.get(driver)
        if true is None:
            continue
        rows[driver] = {mode: 100.0 * (float(fit[mode]) / true[f"cda_{mode}_m2"] - 1.0)
                        for mode in ("straight", "corner")
                        if fit.get(mode) is not None and np.isfinite(fit[mode])}  # fmt: skip
    trap = set(run.info.get("trap_cars") or [])

    def mean(cars: set[str], mode: str = "straight", absolute: bool = False) -> float:
        vals = [abs(v[mode]) if absolute else v[mode]
                for d, v in rows.items() if d in cars and mode in v]  # fmt: skip
        return float(np.mean(vals)) if vals else float("nan")

    plain = set(rows) - trap
    return {"per_car_pct": rows, "mean_pct_straight": mean(plain),
            "mean_abs_pct_straight": mean(plain, absolute=True),
            "mean_pct_corner": mean(plain, "corner"),
            "mean_abs_pct_corner": mean(plain, "corner", absolute=True),
            "trap_mean_pct_straight": mean(trap)}  # fmt: skip


def _events_for(run: Run, kind: str) -> pd.DataFrame:
    """Events as (t_s, car_a = the car the alert would be for, car_b = the rival)."""
    ev = run.events
    if kind in ("ATTACK", "DEFEND"):
        ot = ev[(ev["type"] == "overtake") & ~ev["blue_flag"]]
        a, b = ("car_a", "car_b") if kind == "ATTACK" else ("car_b", "car_a")
        return pd.DataFrame({"t_s": ot["t_start_s"], "car_a": ot[a], "car_b": ot[b]})
    if kind == "REPASS_RISK":
        rp = ev[ev["type"] == "repass"]
        return pd.DataFrame({"t_s": rp["t_end_s"], "car_a": rp["car_a"], "car_b": rp["car_b"]})
    cs = ev[ev["type"] == "closing_speed"]
    both = pd.concat([
        pd.DataFrame({"t_s": cs["t_start_s"], "car_a": cs["car_a"], "car_b": cs["car_b"]}),
        pd.DataFrame({"t_s": cs["t_start_s"], "car_a": cs["car_b"], "car_b": cs["car_a"]}),
    ])  # fmt: skip
    return both


def score_alerts(
    run: Run, alerts: pd.DataFrame, window_laps: float = WINDOW_LAPS
) -> dict[str, Any]:
    """Recall, lead time and precision per alert type, for the cars the alerts are for."""
    window = window_laps * run.lap_s
    povs = set(alerts["car_a"]) or ({run.info["alert_pov"]} if run.info.get("alert_pov") else set())
    out: dict[str, Any] = {"alerts": int(len(alerts)), "alerts_per_pov_car": {}}
    for pov in povs:
        n = int((alerts["car_a"] == pov).sum())
        out["alerts_per_pov_car"][pov] = {"n": n, "flag_over_100": n > ALERTS_PER_RACE_FLAG}
    for kind in ALERT_TYPES:
        al = alerts[alerts["type"] == kind]
        ev = _events_for(run, kind)
        ev = ev[ev["car_a"].isin(povs)]
        leads = []
        for e in ev.itertuples():
            hit = al[(al["car_a"] == e.car_a) & (al["car_b"] == e.car_b)
                     & (al["time_s"] <= e.t_s) & (al["time_s"] >= e.t_s - window)]  # fmt: skip
            if len(hit):
                leads.append(e.t_s - float(hit["time_s"].min()))
        followed = 0
        for a in al.itertuples():
            m = ev[(ev["car_a"] == a.car_a) & (ev["car_b"] == a.car_b)
                   & (ev["t_s"] >= a.time_s) & (ev["t_s"] <= a.time_s + window)]  # fmt: skip
            followed += bool(len(m))
        lead = np.asarray(leads)
        row: dict[str, Any] = {
            "alerts": int(len(al)), "events": int(len(ev)),
            "recall": float(len(lead) / len(ev)) if len(ev) else float("nan"),
            "precision": float(followed / len(al)) if len(al) else float("nan"),
            "lead_median_s": float(np.median(lead)) if lead.size else float("nan"),
            "lead_share_ge_5s": float((lead >= GOOD_LEAD_S).mean()) if lead.size else float("nan"),
            "lead_share_lt_1s": (
                float((lead < USELESS_LEAD_S).mean()) if lead.size else float("nan")
            ),
        }  # fmt: skip
        if kind in ("ATTACK", "DEFEND") and len(al):
            row.update(_right(run, al, kind))
        out[kind] = row
    return out


def _right(run: Run, al: pd.DataFrame, kind: str) -> dict[str, Any]:
    """Return the share of alerts the true batteries agree with, overall and per branch.

    ATTACK: the rival's true battery below ours; DEFEND: above.
    """
    pov = _truth_at(run, al.assign(driver=al["car_a"])[["driver", "time_s"]])["battery_mj"]
    rival = _truth_at(run, al.assign(driver=al["car_b"])[["driver", "time_s"]])["battery_mj"]
    diff = (rival - pov).reindex(al.index)
    right = diff < 0.0 if kind == "ATTACK" else diff > 0.0
    out: dict[str, Any] = {"right_per_truth": float(right[diff.notna()].mean())}
    if "branch" in al:
        out["right_per_truth_by_branch"] = {
            str(b): float(right[(al["branch"] == b) & diff.notna()].mean())
            for b in sorted(al["branch"].dropna().unique()) if b
        }  # fmt: skip
    return out


def score_incidents(run: Run, alerts: pd.DataFrame) -> dict[str, Any] | None:
    """Check the repass / closing_speed target: an alert for the pair before the event."""
    scenario = run.info.get("scenario")
    pair = run.info.get("pair")
    if scenario not in ("repass", "closing_speed") or not pair:
        return None
    kind = "REPASS_RISK" if scenario == "repass" else "CLOSING_SPEED_RISK"
    ev = run.events[(run.events["type"] == ("repass" if scenario == "repass" else "closing_speed"))
                    & run.events["scenario_target"]]  # fmt: skip
    if ev.empty:
        return {"type": kind, "pass": None, "note": "the race did not produce the target event"}
    first = ev.iloc[0]
    event_t = float(first["t_end_s"])
    a, b = pair
    hit = alerts[(alerts["type"] == kind) & (alerts["car_a"] == a) & (alerts["car_b"] == b)
                 & (alerts["time_s"] <= event_t)
                 & (alerts["time_s"] >= event_t - WINDOW_LAPS * run.lap_s)]  # fmt: skip
    return {
        "type": kind,
        "event_t_s": event_t,
        "pass": bool(len(hit)),
        "lead_s": float(event_t - hit["time_s"].min()) if len(hit) else None,
    }


def evaluate(
    run_dir: Path, estimates: pd.DataFrame | None = None, alerts: pd.DataFrame | None = None,
    cda_fit: dict[str, Any] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Score one estimator's outputs on one export."""
    run = Run.load(run_dir)
    out: dict[str, Any] = {"run": run.info.get("scenario"), "seed": run.info.get("seed")}
    if estimates is not None:
        out["energy"] = score_energy(run, estimates)
        out["state"] = score_states(run, estimates)
    if cda_fit is not None:
        out["cda"] = score_cda(run, cda_fit)
    if alerts is not None:
        out["alerts"] = score_alerts(run, alerts)
        incidents = score_incidents(run, alerts)
        if incidents is not None:
            out["incident"] = incidents
    return out
