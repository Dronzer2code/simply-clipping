"""T-021: powertrain tapers, zone caps, boost cap, deployment and Overtake mode."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.car.powertrain import (
    KMH_TO_MS,
    PowertrainParams,
    boost_cap_w,
    ice_power_w,
    mgu_k_allowed_w,
    mgu_k_deploy_w,
    overtake_available,
    overtake_extra_energy_j,
    powertrain_params,
    taper_boost,
    taper_overtake,
)
from pitwall_sim.config.loader import ConfigError, load_rule_set, load_team_performance, load_track
from pitwall_sim.track.zones import zone_mask

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
RULE_SET_IDS = ("2026_pre_miami", "2026_post_miami")


def _params(rule_set_id: str) -> PowertrainParams:
    rules = load_rule_set(rule_set_id, CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    return powertrain_params(rules, team)


@pytest.fixture(params=RULE_SET_IDS)
def params(request: pytest.FixtureRequest) -> PowertrainParams:
    return _params(request.param)


@pytest.mark.parametrize("rule_set_id", RULE_SET_IDS)
def test_taper(rule_set_id: str) -> None:
    """TRD test_taper: taper_boost / taper_overtake match the Rule Set knees."""
    rules = load_rule_set(rule_set_id, CONFIG_DIR)
    p = _params(rule_set_id)
    b0, b1 = rules.power.boost_taper_start_kmh, rules.power.boost_taper_end_kmh
    o0, o1 = rules.overtake.taper_start_kmh, rules.overtake.taper_end_kmh
    assert not isinstance(b0, str) and not isinstance(b1, str)
    assert not isinstance(o0, str) and not isinstance(o1, str)

    for taper, start, end in ((taper_boost, b0, b1), (taper_overtake, o0, o1)):
        assert taper(0.0, p) == 1.0
        assert taper(start * KMH_TO_MS, p) == 1.0
        assert taper((start + end) / 2 * KMH_TO_MS, p) == pytest.approx(0.5)
        assert taper(end * KMH_TO_MS, p) == 0.0
        assert taper((end + 10) * KMH_TO_MS, p) == 0.0

    # Both Rule Sets: boost 290 -> 355 km/h, Overtake 337 -> 355 km/h.
    assert (b0, b1, o0, o1) == (290, 355, 337, 355)


def test_taper_is_monotonic(params: PowertrainParams) -> None:
    v = np.linspace(0.0, 110.0, 500)
    boost = [taper_boost(x, params) for x in v]
    overtake = [taper_overtake(x, params) for x in v]

    assert all(a >= b for a, b in zip(boost, boost[1:], strict=False))
    # Overtake mode keeps full power to a higher speed, never less than normal.
    assert all(o >= b for o, b in zip(overtake, boost, strict=True))


def test_ice_power_scales_with_throttle(params: PowertrainParams) -> None:
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    full = 400_000.0 * float(team.pu_power_scale)  # 400 kW nominal x team scale (T-026)
    assert params.p_ice_max_w == pytest.approx(full)
    assert ice_power_w(0.0, params) == 0.0
    assert ice_power_w(0.5, params) == pytest.approx(0.5 * full)
    assert ice_power_w(1.0, params) == pytest.approx(full)
    assert ice_power_w(1.5, params) == pytest.approx(full)  # clamped


def test_pu_power_scale_multiplies_ice_power() -> None:
    rules = load_rule_set("2026_pre_miami", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]

    p = powertrain_params(rules, team.model_copy(update={"pu_power_scale": 0.97}))

    assert p.p_ice_max_w == pytest.approx(400_000.0 * 0.97)


@pytest.mark.parametrize(
    ("rule_set_id", "in_zone_kw", "elsewhere_kw"),
    [("2026_pre_miami", 350.0, 350.0), ("2026_post_miami", 350.0, 250.0)],
)
def test_zone_caps_applied_per_zone_tag(
    rule_set_id: str, in_zone_kw: float, elsewhere_kw: float
) -> None:
    """Suzuka: 350 kW on acceleration_zone straights; 250 kW elsewhere only post-Miami."""
    p = _params(rule_set_id)
    track = load_track("suzuka", CONFIG_DIR)
    s = np.array([100.0, 3000.0, 4500.0, 5200.0, 5700.0])  # SM1, Esses, SM2, ST3, T18
    accel = zone_mask(track, s, tag="acceleration_zone")

    allowed = [mgu_k_allowed_w(30.0, bool(a), False, False, 0.0, 0.0, p) for a in accel]

    assert list(accel) == [True, False, True, True, False]
    assert allowed == [in_zone_kw * 1e3 if a else elsewhere_kw * 1e3 for a in accel]


def test_allowed_is_the_lowest_limit(params: PowertrainParams) -> None:
    # Above the taper start the tapered MGU-K maximum is below the zone cap.
    v = (290 + 355) / 2 * KMH_TO_MS
    assert mgu_k_allowed_w(v, True, False, False, 0.0, 0.0, params) == pytest.approx(175_000.0)
    # Overtake mode uses its own taper: full 350 kW up to 337 km/h.
    v_ot = 330 * KMH_TO_MS
    assert mgu_k_allowed_w(v_ot, True, True, False, 0.0, 0.0, params) == pytest.approx(350_000.0)
    assert mgu_k_allowed_w(v_ot, True, False, False, 0.0, 0.0, params) < 350_000.0


def test_boost_cap_is_post_miami_only() -> None:
    pre, post = _params("2026_pre_miami"), _params("2026_post_miami")

    assert boost_cap_w(True, 500_000.0, 400_000.0, pre) == math.inf
    assert boost_cap_w(False, 500_000.0, 400_000.0, post) == math.inf


def test_boost_cap_limits_total_power_to_activation_plus_150_kw() -> None:
    """Owner decision: total power <= total power at activation + 150 kW."""
    post = _params("2026_post_miami")
    activation_total_w = 400_000.0 + 100_000.0  # full ICE + 100 kW MGU-K at activation

    # Same ICE power: the MGU-K may rise by 150 kW, to 250 kW.
    assert boost_cap_w(True, activation_total_w, 400_000.0, post) == pytest.approx(250_000.0)
    # ICE 50 kW lower: the MGU-K may make it up (total still activation + 150 kW).
    assert boost_cap_w(True, activation_total_w, 350_000.0, post) == pytest.approx(300_000.0)
    # Never negative.
    assert boost_cap_w(True, 0.0, 400_000.0, post) == 0.0

    allowed = mgu_k_allowed_w(30.0, True, False, True, activation_total_w, 400_000.0, post)
    assert allowed == pytest.approx(250_000.0)
    # Never above the zone cap: with a low ICE power the boost cap alone would
    # allow 550 kW, but the zone caps (350 kW / 250 kW) still bind.
    in_zone = mgu_k_allowed_w(30.0, True, False, True, activation_total_w, 100_000.0, post)
    off_zone = mgu_k_allowed_w(30.0, False, False, True, activation_total_w, 100_000.0, post)
    assert in_zone == pytest.approx(350_000.0)
    assert off_zone == pytest.approx(250_000.0)


def test_deploy_is_limited_by_fraction_and_battery() -> None:
    assert mgu_k_deploy_w(350_000.0, 0.5, 1e9) == pytest.approx(175_000.0)
    assert mgu_k_deploy_w(350_000.0, 1.0, 120_000.0) == pytest.approx(120_000.0)
    assert mgu_k_deploy_w(350_000.0, 2.0, 1e9) == pytest.approx(350_000.0)
    assert mgu_k_deploy_w(350_000.0, 1.0, -5.0) == 0.0


def test_overtake_mode_availability_and_energy(params: PowertrainParams) -> None:
    assert overtake_available(0.0, params)
    assert overtake_available(1.0, params)
    assert not overtake_available(1.01, params)
    assert not overtake_available(-0.1, params)

    assert overtake_extra_energy_j(True, True, params) == pytest.approx(0.5e6)
    assert overtake_extra_energy_j(True, False, params) == 0.0
    assert overtake_extra_energy_j(False, True, params) == 0.0


def test_team_cannot_exceed_the_rule_mgu_k_limit() -> None:
    rules = load_rule_set("2026_post_miami", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]

    p = powertrain_params(rules, team.model_copy(update={"p_k_max_kw": 400.0}))

    assert p.p_k_max_w == pytest.approx(350_000.0)


def test_placeholder_rule_values_are_refused() -> None:
    rules = load_rule_set("2026_post_miami", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    power = rules.power.model_copy(update={"boost_taper_end_kmh": "UNRESOLVED"})

    with pytest.raises(ConfigError, match="boost_taper_end_kmh"):
        powertrain_params(rules.model_copy(update={"power": power}), team)
