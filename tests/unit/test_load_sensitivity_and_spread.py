"""Owner round 14 (T-02A): tyre load sensitivity and the energy-spreading deploy policy.

Coefficients come from config at test time.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.compare import rule_set_for_date, simulate_quali_lap, track_arrays
from pitwall_sim.calibration.deploy_policy import (
    EMPTY_J,
    PLAN_FLOOR_J,
    PolicyResult,
    feasible_budgets,
)
from pitwall_sim.car.deploy_allocation import DeployAllocation, allocate, full_throttle_runs
from pitwall_sim.car.dynamics import G_MS2, V_CORNER_CAP_MS, corner_speed_ms, load_factor
from pitwall_sim.config.loader import load_app, load_team_performance, load_track, load_tyres
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


# --------------------------------------------------------------------------- #
# Change 1: load sensitivity
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("radius", [20.0, 60.0, 120.0])
def test_corner_speed_balances_load_sensitive_grip(radius: float) -> None:
    mu, m, rho, cl, n_ref, k = 2.0, 800.0, 1.2, 4.5, 7850.0, 0.15
    v = corner_speed_ms(1.0 / radius, mu, m, rho, cl, n_ref, k)
    assert math.isfinite(v)
    normal = m * G_MS2 + 0.5 * rho * cl * v * v
    grip = mu * load_factor(normal, n_ref, k) * normal
    assert m * v * v / radius == pytest.approx(grip, rel=1e-9)


def test_load_sensitivity_removes_the_aero_singularity() -> None:
    mu, m, rho, cl, n_ref = 2.15, 773.0, 1.2, 4.84, 7580.6
    radius = 150.0  # above the k = 0 singular radius (~124 m): flat out without sensitivity
    assert corner_speed_ms(1.0 / radius, mu, m, rho, cl) == math.inf
    v = corner_speed_ms(1.0 / radius, mu, m, rho, cl, n_ref, 0.15)
    assert 60.0 < v < V_CORNER_CAP_MS  # finite: grip no longer outgrows the need
    # k = 0 keeps the closed form; more sensitivity, less grip at high load.
    closed = math.sqrt(mu * m * G_MS2 / (m / 40.0 - mu * 0.5 * rho * cl))
    assert corner_speed_ms(1.0 / 40.0, mu, m, rho, cl, n_ref, 0.0) == pytest.approx(closed)
    assert corner_speed_ms(1 / 80, mu, m, rho, cl, n_ref, 0.25) < corner_speed_ms(
        1 / 80, mu, m, rho, cl, n_ref, 0.05
    )
    assert load_factor(n_ref, n_ref, 0.2) == 1.0
    assert load_factor(2 * n_ref, n_ref, 0.2) == pytest.approx(2**-0.2)


# --------------------------------------------------------------------------- #
# Change 2: energy-spreading allocation and policy
# --------------------------------------------------------------------------- #


def test_runs_split_at_the_line_and_rank_slow_exits_first() -> None:
    full = np.zeros(1000, dtype=np.bool_)
    full[0:100] = full[300:400] = full[950:1000] = True
    runs = full_throttle_runs(full, 1.0)
    assert [(int(r[0]), int(r[-1])) for r in runs] == [(0, 99), (300, 399), (950, 999)]
    v = np.full(1000, 80.0)
    v[300] = 30.0  # slowest exit
    v[950] = 50.0
    alloc = allocate(
        v, full, np.zeros(1000, dtype=np.bool_), 1.0,
        _pt(), 1.0,
    )  # fmt: skip
    assert alloc.rank[300] == 0 and alloc.rank[950] == 1 and alloc.rank[0] == 2
    assert alloc.priority[300] == 0.0 and alloc.priority[500] == 1.0
    budgets = alloc.run_budgets(alloc.run_demand_j[0] + 0.5 * alloc.run_demand_j[1])
    assert budgets[0] == pytest.approx(alloc.run_demand_j[0])
    assert budgets[1] == pytest.approx(0.5 * alloc.run_demand_j[1])
    assert budgets[2] == 0.0


def _pt():  # type: ignore[no-untyped-def]
    from pitwall_sim.car.powertrain import powertrain_params

    rules = rule_set_for_date(date(2026, 3, 28), CONFIG_DIR)
    return powertrain_params(rules, load_team_performance(CONFIG_DIR).teams["mercedes"])


def test_feasible_budgets_never_empty_the_planned_battery() -> None:
    n = 1000
    rank = np.full(n, -1, dtype=np.int64)
    rank[100:200], rank[600:700] = 1, 0  # the late run ranks first
    alloc = DeployAllocation(rank, np.array([3e6, 3e6]), np.ones(n))
    harvest = np.zeros(n)
    harvest[400:450] = 2e6 / 50  # 2 MJ of braking between the runs
    budgets = feasible_budgets(alloc, 4e6, harvest, 4e6, 0.0)
    b, lowest = 4e6, math.inf
    draw = np.zeros(n)
    draw[600], draw[100] = budgets[0], budgets[1]
    for i in range(n - 1):
        b = min(4e6, b + harvest[i] - draw[i])
        lowest = min(lowest, b)
    assert lowest >= PLAN_FLOOR_J - 1.0
    assert budgets.sum() == pytest.approx(4e6 + 2e6 - PLAN_FLOOR_J, rel=0.02)


def test_spread_policy_keeps_energy_to_the_last_zone() -> None:
    app, track, perf, tyres = (
        load_app(CONFIG_DIR), load_track("suzuka", CONFIG_DIR),
        load_team_performance(CONFIG_DIR), load_tyres(CONFIG_DIR),
    )  # fmt: skip
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    arrays = track_arrays(model, track)
    rules = rule_set_for_date(date(2026, 3, 28), CONFIG_DIR)
    spread = simulate_quali_lap(arrays, track, rules, perf.teams["mercedes"], tyres, app, "policy")
    anywhere = simulate_quali_lap(
        arrays, track, rules, perf.teams["mercedes"], tyres, app, "anywhere"
    )
    assert isinstance(spread, PolicyResult) and isinstance(anywhere, PolicyResult)
    accel = arrays.accel_zone
    last_zone = int(np.flatnonzero(accel & ~np.roll(accel, 1)).max())
    assert spread.lap.battery_j[:last_zone].min() > EMPTY_J  # owner round 14
    assert spread.lap.lap_time_s < anywhere.lap.lap_time_s


# --------------------------------------------------------------------------- #
# Plausibility of the calibrated lap (runs once the PROVISIONAL marks are gone)
# --------------------------------------------------------------------------- #


def test_calibrated_lap_is_plausible() -> None:
    if "CALIBRATED-PROVISIONAL" in (CONFIG_DIR / "teams" / "performance.yaml").read_text("utf-8"):
        pytest.skip("Suzuka coefficients are still provisional (T-02A refit pending)")
    from pitwall_sim.calibration.compare import lap_of
    from pitwall_sim.calibration.fit import peak_accelerations_g

    app, track, perf, tyres = (
        load_app(CONFIG_DIR), load_track("suzuka", CONFIG_DIR),
        load_team_performance(CONFIG_DIR), load_tyres(CONFIG_DIR),
    )  # fmt: skip
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    arrays = track_arrays(model, track)
    rules = rule_set_for_date(date(2026, 3, 28), CONFIG_DIR)
    lap = lap_of(simulate_quali_lap(arrays, track, rules, perf.teams["mercedes"], tyres, app))
    lat_g, brake_g = peak_accelerations_g(lap, arrays.kappa)
    assert lat_g <= app.calibration.max_lateral_g
    assert brake_g <= app.calibration.max_braking_g
