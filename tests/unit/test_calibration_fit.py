"""T-026 calibration fit helpers: objective, bounds, optimiser, config writers."""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from pitwall_sim.calibration.compare import TeamResult, TrackArrays
from pitwall_sim.calibration.fit import (
    G_MS2,
    FitContext,
    FitResult,
    _fit_from_json,
    _fit_to_json,
    apply,
    bound_hits,
    calibration_notes,
    drag_order_penalty,
    fit,
    load_checkpoint,
    objective,
    on_bounds,
    plausibility,
    plausibility_penalty,
    save_checkpoint,
    set_soft_mu,
    set_team_value,
    verdict,
    write_config,
)
from pitwall_sim.car.lap_sim import LapResult
from pitwall_sim.config.loader import (
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_objective_weights_both_targets() -> None:
    app = load_app(CONFIG_DIR)  # 2 % and 15 km/h (owner round 15)
    assert objective(100.0, 100.0, 0.0, app) == 0.0
    assert objective(102.0, 100.0, 0.0, app) == pytest.approx(1.0)
    assert objective(100.0, 100.0, 15.0, app) == pytest.approx(1.0)
    assert objective(98.0, 100.0, 7.5, app) == pytest.approx(1.25)


def test_bounds_hits_are_reported() -> None:
    bounds = load_app(CONFIG_DIR).calibration.bounds
    assert on_bounds({"cla_corner": 2.5, "cda_corner": 1.0}, bounds) == ("cla_corner",)
    assert on_bounds({"pu_power_scale": 1.0299}, bounds) == ("pu_power_scale",)
    assert on_bounds({"pu_power_scale": 1.0}, bounds) == ()


def test_bounds_cover_every_fitted_coefficient() -> None:
    bounds = load_app(CONFIG_DIR).calibration.bounds
    assert set(bounds) == {
        "mu_base_soft", "long_grip_ratio", "cla_corner", "cda_straight", "cda_corner",
        "pu_power_scale", "k_load",
    }  # fmt: skip
    assert bounds["k_load"] == (0.05, 0.30)  # owner round 14
    assert bounds["pu_power_scale"] == (0.97, 1.03)  # owner round 10
    assert all(lo < hi for lo, hi in bounds.values())


def test_fit_finds_a_known_minimum_within_bounds() -> None:
    bounds = {"a": (0.0, 10.0), "b": (-5.0, 5.0)}

    def cost(v: dict[str, float]) -> float:
        return (v["a"] - 3.0) ** 2 + (v["b"] + 1.0) ** 2

    result = fit(("a", "b"), {"a": 9.0, "b": 4.0}, bounds, cost, 500)

    assert result.values["a"] == pytest.approx(3.0, abs=0.02)
    assert result.values["b"] == pytest.approx(-1.0, abs=0.02)
    assert result.on_bound == ()


def test_fit_stops_at_a_bound_and_says_so() -> None:
    result = fit(("a",), {"a": 5.0}, {"a": (0.0, 10.0)}, lambda v: (v["a"] - 20.0) ** 2, 300)

    assert result.values["a"] == pytest.approx(10.0, abs=0.01)
    assert result.on_bound == ("a",)


def test_apply_puts_mu_on_soft_and_the_rest_on_the_team() -> None:
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    tyres = load_tyres(CONFIG_DIR)

    team2, tyres2 = apply(team, tyres, {"mu_base_soft": 1.9, "cla_corner": 5.1})

    assert tyres2.compounds[Compound.SOFT].mu_base == 1.9
    assert tyres2.compounds[Compound.MEDIUM].mu_base == tyres.compounds[Compound.MEDIUM].mu_base
    assert team2.cla_corner == 5.1 and team.cla_corner != 5.1


def test_writers_change_only_their_line() -> None:
    text = (CONFIG_DIR / "teams" / "performance.yaml").read_text(encoding="utf-8")

    new = set_team_value(text, "ferrari", "cla_corner", 4.98765, "# CALIBRATED test")
    changed = [(a, b) for a, b in zip(text.splitlines(), new.splitlines(), strict=True) if a != b]

    assert changed == [(changed[0][0], "    cla_corner: 4.9877 # CALIBRATED test")]
    assert yaml.safe_load(new)["teams"]["ferrari"]["cla_corner"] == pytest.approx(4.9877)
    before = yaml.safe_load(text)["teams"]["mercedes"]["cla_corner"]
    assert yaml.safe_load(new)["teams"]["mercedes"]["cla_corner"] == before  # untouched

    tyres = (CONFIG_DIR / "tyres.yaml").read_text(encoding="utf-8")
    new_tyres = set_soft_mu(tyres, 1.8123, "# CALIBRATED test")
    data = yaml.safe_load(new_tyres)["compounds"]
    assert data["SOFT"]["mu_base"] == pytest.approx(1.8123)
    assert data["MEDIUM"]["mu_base"] == yaml.safe_load(tyres)["compounds"]["MEDIUM"]["mu_base"]


def test_write_config_round_trips_and_neutral_teams(tmp_path: Path) -> None:
    shutil.copytree(CONFIG_DIR, tmp_path / "config")
    config = tmp_path / "config"
    bounds = load_app(config).calibration.bounds
    team_ids = list(load_team_performance(config).teams)
    grip = {"mu_base_soft": 1.85, "long_grip_ratio": 1.05}
    shared = {"cla_corner": 4.6, "cda_straight": 0.62, "cda_corner": 1.1}
    per_team = {"mercedes": {"cla_corner": 4.9, "cda_straight": 0.6, "cda_corner": 1.05,
                             "pu_power_scale": 1.01}}  # fmt: skip

    write_config(config, "suzuka", grip, shared, per_team, team_ids, bounds)

    teams = load_team_performance(config).teams  # still valid config
    assert teams["mercedes"].cla_corner == 4.9 and teams["mercedes"].pu_power_scale == 1.01
    assert teams["aurora"].cla_corner == 4.6 and teams["aurora"].pu_power_scale == 1.0
    assert all(t.long_grip_ratio == 1.05 for t in teams.values())
    assert load_tyres(config).compounds[Compound.SOFT].mu_base == 1.85
    text = (config / "teams" / "performance.yaml").read_text(encoding="utf-8")
    assert "cla_corner: 4.9000 # CALIBRATED T-026 suzuka (bounds 2.5-6)" in text
    assert "# F02 / FR-SIM-02 per-team power unit" in text  # header comments kept


def test_bound_hits_report_the_direction() -> None:
    bounds = load_app(CONFIG_DIR).calibration.bounds
    hits = bound_hits({"cda_straight": 0.9998, "pu_power_scale": 0.97, "cla_corner": 4.5}, bounds)

    assert hits == [("cda_straight", 0.9998, "upper"), ("pu_power_scale", 0.97, "lower")]


def test_provisional_values_are_marked(tmp_path: Path) -> None:
    shutil.copytree(CONFIG_DIR, tmp_path / "config")
    config = tmp_path / "config"
    bounds = load_app(config).calibration.bounds
    grip = {"mu_base_soft": 1.85, "long_grip_ratio": 1.0}
    shared = {"cla_corner": 4.6, "cda_straight": 0.62, "cda_corner": 1.1}

    write_config(config, "suzuka", grip, shared, {}, list(load_team_performance(config).teams),
                 bounds, provisional=True)  # fmt: skip

    perf = (config / "teams" / "performance.yaml").read_text(encoding="utf-8")
    tyres = (config / "tyres.yaml").read_text(encoding="utf-8")
    assert "# CALIBRATED-PROVISIONAL (T-026, RMSE limit relaxed) suzuka bounds 2.5-6" in perf
    assert "mu_base: 1.8500 # CALIBRATED-PROVISIONAL (T-026, RMSE limit relaxed)" in tyres
    assert not re.search(r"^\s+\w+: [\d.]+ # CALIBRATED T-026", perf, flags=re.MULTILINE)


def test_calibration_notes_list_results_and_bound_hits() -> None:
    bounds = load_app(CONFIG_DIR).calibration.bounds
    report = {
        "track_id": "suzuka",
        "rule_set_id": "2026_pre_miami",
        "provisional": True,
        "stage1": {"mu_base_soft": 2.2, "long_grip_ratio": 0.99},
        "per_team": {"mercedes": {"cda_straight": 0.9998, "pu_power_scale": 1.01}},
        "results": [
            {
                "team_id": "mercedes",
                "target_s": 88.778,
                "lap_time_s": 88.771,
                "delta_pct": -0.01,
                "speed_rmse_kmh": 19.4,
                "real_position": 1,
                "sim_position": 1,
            }
        ],  # fmt: skip
        "extras": {
            "pole_team": "mercedes",
            "pole_lap_greedy_s": 88.3,
            "pole_lap_policy_s": 88.8,
            "pole_corner_min_kmh_sim_vs_real": {"130R (T15)": [328.8, float("nan")]},
        },  # fmt: skip
    }

    notes = calibration_notes(report, bounds, 20.0)

    assert "## suzuka (2026_pre_miami), PROVISIONAL" in notes
    assert "speed RMSE ≤ 20 km/h" in notes
    assert "| mercedes | 88.778 | 88.771 | -0.01 | 19.4 | 1 | 1 |" in notes
    assert (
        "| stage 1 (shared) | `mu_base_soft` | 2.2000 | 1.3-2.2 | toward the upper bound |" in notes
    )
    assert "| mercedes | `cda_straight` | 0.9998 | 0.4-1 | toward the upper bound |" in notes
    assert "no valid sample" in notes


def test_straight_mode_drag_may_not_exceed_corner_mode_drag() -> None:
    bounds = load_app(CONFIG_DIR).calibration.bounds

    assert drag_order_penalty({"cda_straight": 0.6, "cda_corner": 1.1}) == 0.0
    assert drag_order_penalty({"cda_straight": 1.0, "cda_corner": 0.8}) == pytest.approx(400.0)
    assert drag_order_penalty({"cla_corner": 4.0}) == 0.0  # not fitting both drags
    hits = on_bounds({"cda_straight": 0.9, "cda_corner": 0.9}, bounds)
    assert "cda_straight<=cda_corner" in hits


def test_checkpoint_round_trip_and_key_mismatch(tmp_path: Path) -> None:
    """T-02A: progress survives an interruption, but only for the same fit."""
    path = tmp_path / "ck.json"
    key = {"track": "suzuka", "rules": "2026_pre_miami", "grid": "real_2026"}
    fitted = FitResult({"cla_corner": 4.5, "pu_power_scale": 1.0}, 2.5, 120, ("pu_power_scale",))

    fresh = load_checkpoint(path, key)
    assert fresh == {"key": key, "stage1": None, "teams": {}}
    fresh["teams"]["mercedes"] = _fit_to_json(fitted)
    save_checkpoint(path, fresh)

    resumed = load_checkpoint(path, key)
    assert _fit_from_json(resumed["teams"]["mercedes"]) == fitted
    other = load_checkpoint(path, {**key, "rules": "2026_post_miami"})
    assert other["teams"] == {}  # a different fit starts fresh


def _ctx_and_lap(v_corner_ms: float) -> tuple[FitContext, LapResult]:
    """1 km grid with one 100 m-radius corner at 400-600 m; constant 50 m/s elsewhere."""
    app = load_app(CONFIG_DIR)
    s = np.arange(1000.0)
    kappa = np.where((s >= 400) & (s <= 600), 0.01, 0.0)
    v = np.where((s >= 400) & (s <= 600), v_corner_ms, 50.0)
    arrays = TrackArrays(s, kappa, np.zeros(1000, bool), np.zeros(1000, bool), 1000.0)
    ctx = FitContext(
        arrays, load_track("suzuka", CONFIG_DIR), load_rule_set("2026_pre_miami", CONFIG_DIR),
        load_tyres(CONFIG_DIR), app,
    )  # fmt: skip
    lap = LapResult(s, v, np.cumsum(1.0 / v), np.zeros(1000), 20.0, 0.0, 0.0, 0.0, 0.0)
    return ctx, lap


def test_plausibility_is_a_constraint_in_the_fit() -> None:
    """Owner round 15 (b): zero inside the limits, growing with the excess."""
    cal = load_app(CONFIG_DIR).calibration
    ctx, ok = _ctx_and_lap(50.0)  # 2.55 g in the corner, no braking
    lat, brake, esses = plausibility(ctx, ok)
    assert lat == pytest.approx(2500 * 0.01 / G_MS2) and brake == 0.0 and esses == 0.0
    assert plausibility_penalty(ctx, ok) == 0.0

    ctx, fast = _ctx_and_lap(80.0)  # 6.5 g lateral; and 30 m/s lost in 1 m at 600 m
    lat, brake, _ = plausibility(ctx, fast)
    assert lat > cal.max_lateral_g and brake > cal.max_braking_g
    assert plausibility_penalty(ctx, fast) > plausibility_penalty(*_ctx_and_lap(70.0)) > 0.0

    esses = replace(ctx, esses_real={"T5": (500.0, 260.0)})  # sim 288 km/h: +28 km/h
    _, _, excess = plausibility(esses, fast)
    assert excess == pytest.approx(80.0 * 3.6 - 260.0)
    assert plausibility_penalty(esses, fast) > plausibility_penalty(ctx, fast)


def test_verdict_follows_the_round_15_acceptance() -> None:
    app = load_app(CONFIG_DIR)

    def result(team: str, rmse: float, ok: bool = True, pos: int = 1) -> TeamResult:
        return TeamResult(team, 90.0, 90.1, 0.1, rmse, ok, rmse <= 15, pos, pos, 0.0, 0.0)

    def report(plausible: bool = True, stage1: list[str] | None = None) -> dict[str, Any]:
        return {"extras": {"plausibility": {"plausible": plausible},
                           "on_bound": {"stage 1": stage1 or []}}}  # fmt: skip

    good = [result("a", 12.0), result("b", 14.0, pos=2)]
    assert verdict(good, report(), app) == "PASS"
    assert verdict([*good, result("c", 18.0, pos=3)], report(), app) == "ACCEPTED"
    assert verdict([*good, result("c", 21.0, pos=3)], report(), app) == "FAIL"
    assert verdict(good, report(plausible=False), app) == "FAIL"
    assert verdict(good, report(stage1=["k_load"]), app) == "FAIL"  # shared tyre coefficient
    assert verdict(good, report(stage1=["cda_corner"]), app) == "PASS"  # nuisance aero only
    assert verdict([result("a", 12.0, ok=False)], report(), app) == "FAIL"
