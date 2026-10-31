"""T-023: Straight / Corner Mode aero, fuel burn, tyre grip and wear."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pitwall_sim.car.aero import CORNER_MODE, STRAIGHT_MODE, aero_mode, aero_params, cda, cla
from pitwall_sim.car.fuel import burn, fuel_flow_w, fuel_params, max_ice_power_w
from pitwall_sim.car.tyres import (
    TyreParams,
    f_wear,
    mu_tyre,
    step_wear,
    tyre_params,
    tyre_temp_c,
    wear_rate_per_s,
)
from pitwall_sim.config.loader import (
    ConfigError,
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound
from pitwall_sim.race.state import AERO_MODES
from pitwall_sim.track.zones import zone_mask
from tests.unit._zones_helper import zone_length_m

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _team():  # type: ignore[no-untyped-def]
    return load_team_performance(CONFIG_DIR).teams["mercedes"]


# --------------------------------------------------------------------------- #
# Aero: CdA switches by zone tag (T-023 acceptance)
# --------------------------------------------------------------------------- #


def test_cda_switches_by_zone_tag() -> None:
    p = aero_params(_team(), load_app(CONFIG_DIR).aero)
    track = load_track("suzuka", CONFIG_DIR)
    s = np.arange(0.0, 5807.0, 1.0)
    allowed = zone_mask(track, s, tag="straight_mode_allowed")

    modes = np.array([aero_mode(bool(a), 1.0, p) for a in allowed])
    drag = np.array([cda(int(m), p) for m in modes])

    assert (drag[allowed] == p.cda_straight).all()
    assert (drag[~allowed] == p.cda_corner).all()
    assert allowed.sum() == zone_length_m(track, "SM1") + zone_length_m(track, "SM2")


def test_straight_mode_needs_near_full_throttle() -> None:
    p = aero_params(_team(), load_app(CONFIG_DIR).aero)

    assert aero_mode(True, p.straight_mode_throttle_min, p) == STRAIGHT_MODE
    assert aero_mode(True, p.straight_mode_throttle_min - 0.01, p) == CORNER_MODE
    assert aero_mode(False, 1.0, p) == CORNER_MODE


def test_mode_codes_match_the_state_mirror_and_downforce_switches() -> None:
    p = aero_params(_team(), load_app(CONFIG_DIR).aero)

    assert AERO_MODES[STRAIGHT_MODE] == "STRAIGHT_MODE"
    assert AERO_MODES[CORNER_MODE] == "CORNER_MODE"
    assert cla(STRAIGHT_MODE, p) == p.cla_straight
    assert cla(CORNER_MODE, p) == p.cla_corner
    # Straight Mode trades downforce for less drag.
    assert p.cda_straight < p.cda_corner and p.cla_straight < p.cla_corner


# --------------------------------------------------------------------------- #
# Fuel: mass decreases monotonically (T-023 acceptance)
# --------------------------------------------------------------------------- #


@settings(max_examples=100, deadline=None)
@given(st.lists(st.floats(min_value=-1e5, max_value=1e6, allow_nan=False), max_size=300))
def test_fuel_mass_decreases_monotonically(p_ice_sequence: list[float]) -> None:
    p = fuel_params(load_rule_set("2026_post_miami", CONFIG_DIR), _team())
    fuel = 70.0

    for p_ice in p_ice_sequence:
        new = burn(fuel, p_ice, 0.05, p)
        assert 0.0 <= new <= fuel
        if p_ice >= 1.0 and fuel > 0.0:  # below ~1 W the burn is lost in float rounding
            assert new < fuel
        fuel = new


def test_fuel_burn_matches_energy_over_density() -> None:
    p = fuel_params(load_rule_set("2026_post_miami", CONFIG_DIR), _team())
    p_ice_w = 300e3

    burned = 70.0 - burn(70.0, p_ice_w, 60.0, p)

    # 300 kW at 50% -> 600 kW of fuel for 60 s = 36 MJ; at 43 MJ/kg -> 0.837 kg.
    assert burned == pytest.approx(p_ice_w / p.ice_efficiency * 60.0 / p.energy_density_j_per_kg)
    assert burned == pytest.approx(36.0 / 43.0)


def test_fuel_flow_limit_caps_ice_power() -> None:
    p = fuel_params(load_rule_set("2026_post_miami", CONFIG_DIR), _team())

    assert p.max_energy_flow_w == pytest.approx(3000e6 / 3600)
    assert max_ice_power_w(p) == pytest.approx(0.5 * 3000e6 / 3600)
    assert fuel_flow_w(10e6, p) == pytest.approx(p.max_energy_flow_w)
    assert burn(1e-6, 400e3, 10.0, p) == 0.0  # never negative


# --------------------------------------------------------------------------- #
# Tyres: wear increases monotonically (T-023 acceptance), grip from wear
# --------------------------------------------------------------------------- #


def _tyre(compound: Compound = Compound.MEDIUM) -> TyreParams:
    return tyre_params(load_tyres(CONFIG_DIR), compound)


_forces = st.floats(min_value=-5e4, max_value=5e4, allow_nan=False)


@settings(max_examples=100, deadline=None)
@given(st.lists(st.tuples(_forces, _forces, st.floats(0.0, 100.0)), max_size=300))
def test_wear_increases_monotonically(loads: list[tuple[float, float, float]]) -> None:
    p = _tyre()
    wear = 0.0

    for f_long, f_lat, v in loads:
        new = step_wear(wear, wear_rate_per_s(f_long, f_lat, v, 1.0, 1.0, p), 0.05)
        assert wear <= new <= 1.0
        # More wear never adds grip.
        assert mu_tyre(new, tyre_temp_c(p), p) <= mu_tyre(wear, tyre_temp_c(p), p)
        wear = new


def test_wear_rate_scales_with_compound_track_and_management() -> None:
    soft, hard = _tyre(Compound.SOFT), _tyre(Compound.HARD)
    args = (10e3, 10e3, 60.0)

    assert wear_rate_per_s(*args, 1.0, 1.0, soft) > wear_rate_per_s(*args, 1.0, 1.0, hard)
    base = wear_rate_per_s(*args, 1.0, 1.0, soft)
    assert wear_rate_per_s(*args, 2.0, 1.0, soft) == pytest.approx(2 * base)
    assert wear_rate_per_s(*args, 1.0, 0.8, soft) == pytest.approx(0.8 * base)  # MANAGE_TYRES
    # Normalisation: 30 laps of ~90 MJ tyre work wear a k_wear = 1 tyre to ~0.9.
    medium = _tyre(Compound.MEDIUM)
    assert medium.k_wear * 30 * 90e6 / medium.wear_norm_j == pytest.approx(0.9)


def test_f_wear_has_a_cliff_and_is_continuous() -> None:
    p = _tyre(Compound.SOFT)
    eps = 1e-9

    assert f_wear(0.0, p) == 1.0
    assert f_wear(p.cliff_w - eps, p) == pytest.approx(f_wear(p.cliff_w, p), abs=1e-6)
    slope_before = (f_wear(p.cliff_w - 0.01, p) - f_wear(p.cliff_w - 0.02, p)) / 0.01
    slope_after = (f_wear(p.cliff_w + 0.02, p) - f_wear(p.cliff_w + 0.01, p)) / 0.01
    assert slope_after < slope_before < 0  # steeper after the cliff
    assert f_wear(5.0, p) == f_wear(1.0, p) >= 0.0


def test_mvp_temperature_is_the_optimum() -> None:
    p = _tyre()

    assert tyre_temp_c(p) == p.t_optimal_c
    assert mu_tyre(0.0, tyre_temp_c(p), p) == p.mu_base


def test_placeholders_are_refused() -> None:
    tyres = load_tyres(CONFIG_DIR)
    soft = tyres.compounds[Compound.SOFT].model_copy(update={"k_wear": "UNKNOWN"})
    broken = tyres.model_copy(update={"compounds": {**tyres.compounds, Compound.SOFT: soft}})

    with pytest.raises(ConfigError, match="SOFT.k_wear"):
        tyre_params(broken, Compound.SOFT)
    with pytest.raises(ConfigError, match="cda_corner"):
        aero_params(_team().model_copy(update={"cda_corner": "UNKNOWN"}), load_app(CONFIG_DIR).aero)
