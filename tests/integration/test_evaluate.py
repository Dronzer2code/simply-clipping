"""Sprint S-3: the scorer (hand-made truth for the rules, a short export for the baselines)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pitwall_sim.evaluate import Run, score_alerts, score_energy, score_incidents, score_states
from pitwall_sim.evaluate.__main__ import baselines, table
from pitwall_sim.export import export_race

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _run() -> Run:
    """Two cars for 100 s at 10 Hz: A's battery 3 MJ, B's 1 MJ; B taper-limited 40-60 s."""
    t = np.round(np.arange(0.0, 100.0, 0.1), 1)
    rows = []
    for driver, mj in (("A", 3.0), ("B", 1.0)):
        rows.append(pd.DataFrame({
            "driver": driver, "time_s": t, "battery_mj": mj, "energy_mode": "BALANCED",
            "state_true": np.where((t >= 20) & (t < 30), "CLIP", "DEPLOY"),
            "taper_active": (driver == "B") & (t >= 40) & (t < 60),
        }))  # fmt: skip
    events = pd.DataFrame([
        {"type": "overtake", "t_start_s": 50.0, "t_end_s": 50.0, "car_a": "A", "car_b": "B",
         "blue_flag": False, "scenario_target": False},
        {"type": "repass", "t_start_s": 60.0, "t_end_s": 80.0, "car_a": "A", "car_b": "B",
         "blue_flag": False, "scenario_target": True},
    ])  # fmt: skip
    info = {"scenario": "repass", "pair": ["A", "B"], "trap_cars": []}
    return Run(Path("."), info, pd.concat(rows, ignore_index=True), events, {}, 40.0)


def test_alert_recall_lead_precision_and_right_per_truth() -> None:
    alerts = pd.DataFrame([
        {"time_s": 44.0, "lap": 2, "type": "ATTACK", "car_a": "A", "car_b": "B", "confidence": 0.9},
        {"time_s": 90.0, "lap": 3, "type": "ATTACK", "car_a": "A", "car_b": "B", "confidence": 0.9},
        {"time_s": 70.0, "lap": 3, "type": "REPASS_RISK", "car_a": "A", "car_b": "B",
         "confidence": 1.0},
    ])  # fmt: skip
    s = score_alerts(_run(), alerts)
    attack = s["ATTACK"]
    assert attack["events"] == 1 and attack["recall"] == 1.0
    assert attack["lead_median_s"] == pytest.approx(6.0)  # 50 - 44
    assert attack["precision"] == 0.5  # the alert at 90 s is not followed by a pass
    assert attack["right_per_truth"] == 1.0  # B (1 MJ) below A (3 MJ)
    assert s["REPASS_RISK"]["recall"] == 1.0 and s["REPASS_RISK"]["lead_median_s"] == 10.0
    assert s["DEFEND"]["events"] == 0 and np.isnan(s["DEFEND"]["recall"])
    incident = score_incidents(_run(), alerts)
    assert incident is not None and incident["pass"] and incident["lead_s"] == 10.0


def test_energy_and_state_scores() -> None:
    t = np.arange(0.0, 100.0, 1.0)
    est = pd.DataFrame({
        "driver": "B", "time_s": t, "energy_mj": 1.5, "confidence": np.where(t < 50, 0.9, 0.2),
        "state": np.where((t >= 40) & (t < 60), "CLIP", "DEPLOY"),
    })  # fmt: skip
    run = _run()
    energy = score_energy(run, est)
    assert energy["overall"]["mae_mj"] == pytest.approx(0.5)
    assert energy["overall"]["bias_mj"] == pytest.approx(0.5)
    assert energy["confidence_ge_0.5"]["n"] == 50
    states = score_states(run, est)
    assert states["clip_precision"] == 0.0 and states["clip_recall"] == 0.0
    assert states["false_clip_during_taper"] == 20  # CLIP read during the taper
    assert states["confusion"]["DEPLOY"]["CLIP"] == 20


@pytest.mark.slow
def test_baselines_on_a_short_export(tmp_path: Path) -> None:
    export_race(tmp_path, seed=7, scenario="normal", laps=2, config_dir=CONFIG_DIR)
    reports = baselines(tmp_path)
    assert set(reports) == {"built-in", "dumb rule"}
    builtin = reports["built-in"]
    assert 0.0 < builtin["energy"]["overall"]["mae_mj"] < 4.0
    assert 0.0 <= builtin["state"]["accuracy"] <= 1.0
    est = pd.read_parquet(tmp_path / "baseline" / "builtin_estimates.parquet")
    assert set(est.columns) >= {"driver", "time_s", "energy_mj", "state", "confidence"}
    assert est["driver"].nunique() == 22
    lines = table(reports)
    assert any(line.startswith("energy MAE MJ") for line in lines)


def test_table_prints_counts_and_pass_fail_plainly() -> None:
    report = {"alerts": {"ATTACK": {"alerts": 39}}, "incident": {"pass": False}}
    lines = table({"x": report})
    assert next(line for line in lines if line.startswith("ATTACK alerts")).endswith("39")
    assert next(line for line in lines if line.startswith("incident pass")).endswith("no")


def test_no_alerts_score_zero_recall_for_the_runs_pov_car() -> None:
    run = _run()
    run.info["alert_pov"] = "A"
    empty = pd.DataFrame(columns=["time_s", "lap", "type", "car_a", "car_b", "confidence"])
    s = score_alerts(run, empty)
    assert s["ATTACK"]["events"] == 1 and s["ATTACK"]["recall"] == 0.0
