"""T-025: single-car lap simulation with battery, harvest and fuel."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.car.battery import BatteryParams, battery_params
from pitwall_sim.car.fuel import FuelParams, fuel_params
from pitwall_sim.car.lap_sim import LapResult, simulate_lap
from pitwall_sim.car.speed_profile import ProfileParams, reference_params, reference_profile
from pitwall_sim.config.loader import (
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound
from pitwall_sim.track.builder import TrackModel, read_track_model
from pitwall_sim.track.zones import zone_mask

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
QUALI_LIMIT_MJ = 8.0  # 2026_pre_miami energy.harvest_max_mj_per_lap_quali


@pytest.fixture(scope="module")
def setup() -> tuple[TrackModel, ProfileParams, BatteryParams, FuelParams]:
    rules = load_rule_set("2026_pre_miami", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    track = load_track("suzuka", CONFIG_DIR)
    prof = reference_params(
        rules, team, load_tyres(CONFIG_DIR), Compound.SOFT, load_app(CONFIG_DIR), track, 10.0
    )
    assert rules.energy.harvest_max_mj_per_lap_quali == QUALI_LIMIT_MJ
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    return model, prof, battery_params(rules, team, QUALI_LIMIT_MJ), fuel_params(rules, team)


def _run(
    model: TrackModel, prof: ProfileParams, batt: BatteryParams, fuel: FuelParams, start_j: float
) -> LapResult:
    track = load_track("suzuka", CONFIG_DIR)
    return simulate_lap(
        model.s_m,
        model.curvature_per_m,
        zone_mask(track, model.s_m, tag="straight_mode_allowed"),
        zone_mask(track, model.s_m, tag="acceleration_zone"),
        model.length_m,
        prof,
        batt,
        fuel,
        battery_start_j=start_j,
        fuel_kg=10.0,
    )


def test_unlimited_energy_reproduces_the_speed_profile(setup) -> None:  # type: ignore[no-untyped-def]
    model, prof, batt, fuel = setup
    unlimited = batt._replace(e_usable_max_j=1e15, harvest_limit_j=1e15)
    lap = _run(model, prof, unlimited, fuel, 1e14)
    profile = reference_profile(model, load_track("suzuka", CONFIG_DIR), prof)

    assert lap.lap_time_s == pytest.approx(profile.lap_time_s, rel=1e-9)
    assert np.allclose(lap.v_ms, profile.v_ref_ms, atol=1e-9)


def test_real_battery_limits_deployment(setup) -> None:  # type: ignore[no-untyped-def]
    model, prof, batt, fuel = setup
    lap = _run(model, prof, batt, fuel, batt.e_usable_max_j)
    profile = reference_profile(model, load_track("suzuka", CONFIG_DIR), prof)

    assert lap.lap_time_s > profile.lap_time_s  # 4 MJ cannot feed 350 kW all lap
    assert np.all(lap.battery_j >= 0.0)
    assert np.all(lap.battery_j <= batt.e_usable_max_j)
    assert lap.harvested_j <= QUALI_LIMIT_MJ * 1e6 + 1e-6
    # Energy balance over the lap.
    assert lap.battery_end_j == pytest.approx(
        batt.e_usable_max_j + lap.harvested_j - lap.drawn_j, abs=1e-3
    )
    assert np.all(np.diff(lap.t_s) > 0.0)
    assert 0.0 < lap.fuel_used_kg < 10.0


def test_no_mgu_k_is_slower_and_draws_nothing(setup) -> None:  # type: ignore[no-untyped-def]
    model, prof, batt, fuel = setup
    with_k = _run(model, prof, batt, fuel, batt.e_usable_max_j)
    ice_only = _run(model, prof._replace(deploy_fraction=0.0), batt, fuel, batt.e_usable_max_j)

    assert ice_only.drawn_j == 0.0
    assert ice_only.lap_time_s > with_k.lap_time_s


def test_braking_recharges_the_battery(setup) -> None:  # type: ignore[no-untyped-def]
    model, prof, batt, fuel = setup
    lap = _run(model, prof, batt, fuel, 0.0)  # start empty: only harvest can add energy

    slowing = np.diff(lap.v_ms) < 0.0
    braking = np.diff(lap.v_ms) < -0.05
    charging = np.diff(lap.battery_j) > 0.0
    assert lap.harvested_j > 0.0
    assert np.all(slowing[charging])  # energy only comes in while the car slows (brakes)
    assert charging[braking].mean() > 0.9  # and nearly every braking metre harvests


def test_lap_time_is_the_integral_of_ds_over_v(setup) -> None:  # type: ignore[no-untyped-def]
    model, prof, batt, fuel = setup
    lap = _run(model, prof, batt, fuel, batt.e_usable_max_j)
    ds = model.length_m / model.s_m.size

    # Each step's time is ds over the mean speed (trapezoid on 1/v). The closing
    # step uses the speed at the end of the lap, which with a real battery is
    # not exactly the start speed, so it is checked through the total.
    v = lap.v_ms
    assert np.allclose(np.diff(lap.t_s), 2 * ds / (v[:-1] + v[1:]))
    assert lap.lap_time_s > lap.t_s[-1]
    assert lap.lap_time_s - lap.t_s[-1] == pytest.approx(ds / v[-1], rel=0.05)
    assert math.isfinite(lap.lap_time_s)


def test_unmet_deploy_counts_what_the_battery_could_not_supply(setup) -> None:  # type: ignore[no-untyped-def]
    model, prof, batt, fuel = setup
    empty = _run(model, prof, batt, fuel, 0.0)
    unlimited = _run(
        model, prof, batt._replace(e_usable_max_j=1e15, harvest_limit_j=1e15), fuel, 1e14
    )

    assert unlimited.unmet_deploy_j == pytest.approx(0.0, abs=1.0)
    assert empty.unmet_deploy_j > 1e6  # starting empty, most deployment goes unmet
