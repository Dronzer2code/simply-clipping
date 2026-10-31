"""T-022: battery bounds, per-lap limits, harvest sources and counter resets."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pitwall_sim.car.battery import (
    BatteryParams,
    available_deploy_w,
    battery_params,
    braking_harvest_w,
    lap_harvest_limit_j,
    part_throttle_harvest_w,
    reset_at_formation_lap,
    reset_at_timing_line,
    step,
    superclip_harvest_w,
)
from pitwall_sim.config.loader import (
    ConfigError,
    load_rule_set,
    load_team_performance,
    load_track,
    resolve_harvest_limit_mj,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
RULE_SET_IDS = ("2026_pre_miami", "2026_post_miami")
MJ = 1e6


def _params(rule_set_id: str = "2026_post_miami", **rule_overrides: object) -> BatteryParams:
    rules = load_rule_set(rule_set_id, CONFIG_DIR)
    if rule_overrides:
        rules = rules.model_copy(update={"energy": rules.energy.model_copy(update=rule_overrides)})
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    track = load_track("suzuka", CONFIG_DIR)
    return battery_params(rules, team, resolve_harvest_limit_mj(rules, track))


# --------------------------------------------------------------------------- #
# TRD test_battery_bounds (property): 0 <= battery <= E_usable_max every step
# --------------------------------------------------------------------------- #

_power = st.floats(min_value=-2e6, max_value=2e6, allow_nan=False)
_commands = st.lists(
    st.tuples(_power, _power, st.booleans(), st.floats(min_value=0.0, max_value=1.0)),
    min_size=1,
    max_size=400,
)


@settings(max_examples=150, deadline=None)
@given(commands=_commands, start_mj=st.floats(min_value=-1.0, max_value=6.0))
@pytest.mark.parametrize("rule_set_id", RULE_SET_IDS)
def test_battery_bounds(
    rule_set_id: str, commands: list[tuple[float, float, bool, float]], start_mj: float
) -> None:
    p = _params(rule_set_id)
    battery, harvest_lap, deploy_lap = start_mj * MJ, 0.0, 0.0

    for i, (p_harvest, p_deploy, overtake, dt) in enumerate(commands):
        if i % 50 == 49:  # a new lap now and then
            harvest_lap, deploy_lap = reset_at_timing_line()
        before = min(max(battery, 0.0), p.e_usable_max_j)
        r = step(battery, harvest_lap, deploy_lap, p_harvest, p_deploy, overtake, dt, p)
        battery, harvest_lap, deploy_lap = r.battery_j, r.harvest_lap_j, r.deploy_lap_j

        assert 0.0 <= battery <= p.e_usable_max_j
        assert r.harvested_j >= 0.0 and r.drawn_j >= 0.0
        # Energy is conserved: change = stored - drawn.
        assert battery == pytest.approx(before + r.harvested_j - r.drawn_j, abs=1e-6)


# --------------------------------------------------------------------------- #
# TRD test_lap_limits: per-lap counters never exceed the Rule Set limits
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_set_id", RULE_SET_IDS)
@pytest.mark.parametrize("overtake", [False, True])
def test_harvest_counter_stops_at_the_lap_limit(rule_set_id: str, overtake: bool) -> None:
    p = _params(rule_set_id)
    limit = lap_harvest_limit_j(overtake, p)
    battery, harvest_lap, deploy_lap = 0.0, 0.0, 0.0

    # Harvest hard all lap while deploying everything, so the window never fills.
    for _ in range(2000):
        r = step(battery, harvest_lap, deploy_lap, 350e3, 1e7, overtake, 0.05, p)
        battery, harvest_lap, deploy_lap = r.battery_j, r.harvest_lap_j, r.deploy_lap_j
        assert harvest_lap <= limit + 1e-6

    assert harvest_lap == pytest.approx(limit)
    # Owner decision round 2: 8.5 MJ, 9.0 MJ with Overtake active (Suzuka has no override).
    assert limit == pytest.approx((9.0 if overtake else 8.5) * MJ)


def test_deploy_counter_stops_at_a_rule_set_limit() -> None:
    """Both 2026 Rule Sets have no deploy limit; a Rule Set that sets one is honoured."""
    assert math.isinf(_params().deploy_limit_j)
    p = _params(deploy_max_mj_per_lap=1.0)
    battery, harvest_lap, deploy_lap = 4.0 * MJ, 0.0, 0.0

    for _ in range(500):
        r = step(battery, harvest_lap, deploy_lap, 0.0, 350e3, False, 0.05, p)
        battery, harvest_lap, deploy_lap = r.battery_j, r.harvest_lap_j, r.deploy_lap_j
        assert deploy_lap <= 1.0 * MJ + 1e-6

    assert deploy_lap == pytest.approx(1.0 * MJ)
    assert battery == pytest.approx(3.0 * MJ)


def test_battery_full_stops_harvest_but_not_the_lap_counter_room() -> None:
    p = _params()
    r = step(p.e_usable_max_j, 0.0, 0.0, 350e3, 0.0, False, 0.05, p)

    assert r.battery_j == p.e_usable_max_j
    assert r.harvested_j == 0.0
    assert r.harvest_lap_j == 0.0  # nothing stored, nothing counted


def test_deploy_uses_discharge_efficiency() -> None:
    p = _params()
    r = step(2.0 * MJ, 0.0, 0.0, 0.0, 100e3, False, 1.0, p)

    assert r.drawn_j == pytest.approx(100e3 / p.discharge_efficiency)
    assert r.battery_j == pytest.approx(2.0 * MJ - 100e3 / p.discharge_efficiency)


def test_available_power_cannot_overdraw() -> None:
    p = _params()
    battery = 0.01 * MJ
    power = available_deploy_w(battery, 0.0, 0.05, p)
    r = step(battery, 0.0, 0.0, 0.0, power, False, 0.05, p)

    assert r.battery_j == pytest.approx(0.0, abs=1e-6)
    assert available_deploy_w(0.0, 0.0, 0.05, p) == 0.0
    assert available_deploy_w(battery, 0.0, 0.0, p) == 0.0


# --------------------------------------------------------------------------- #
# Harvest sources
# --------------------------------------------------------------------------- #


def test_harvest_sources() -> None:
    p = _params()

    assert braking_harvest_w(400e3, p) == pytest.approx(400e3 * p.brake_harvest_share)
    assert braking_harvest_w(5e6, p) == pytest.approx(350e3)  # MGU-K limit
    assert braking_harvest_w(-1.0, p) == 0.0
    assert part_throttle_harvest_w(1e6, p) == pytest.approx(p.partial_harvest_max_w)
    assert part_throttle_harvest_w(-5.0, p) == 0.0


@pytest.mark.parametrize(("rule_set_id", "kw"), [("2026_pre_miami", 250), ("2026_post_miami", 350)])
def test_superclip_power_follows_the_rule_set(rule_set_id: str, kw: float) -> None:
    assert superclip_harvest_w(_params(rule_set_id)) == pytest.approx(kw * 1e3)


# --------------------------------------------------------------------------- #
# Counter resets
# --------------------------------------------------------------------------- #


def test_counters_reset_at_the_timing_line() -> None:
    assert reset_at_timing_line() == (0.0, 0.0)


@pytest.mark.parametrize(
    ("rule_set_id", "resets"), [("2026_pre_miami", False), ("2026_post_miami", True)]
)
def test_formation_lap_reset_follows_the_rule_set(rule_set_id: str, resets: bool) -> None:
    p = _params(rule_set_id)
    counters = reset_at_formation_lap(1.5 * MJ, 0.7 * MJ, p)

    assert counters == ((0.0, 0.0) if resets else (1.5 * MJ, 0.7 * MJ))


def test_track_override_sets_the_harvest_limit() -> None:
    rules = load_rule_set("2026_post_miami", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    track = load_track("suzuka", CONFIG_DIR).model_copy(update={"harvest_max_mj_per_lap_race": 7.0})

    p = battery_params(rules, team, resolve_harvest_limit_mj(rules, track))

    assert lap_harvest_limit_j(False, p) == pytest.approx(7.0 * MJ)
    assert lap_harvest_limit_j(True, p) == pytest.approx(7.5 * MJ)


def test_placeholder_values_are_refused() -> None:
    rules = load_rule_set("2026_post_miami", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]

    with pytest.raises(ConfigError, match="brake_harvest_share"):
        battery_params(rules, team.model_copy(update={"brake_harvest_share": "UNKNOWN"}), 8.5)
