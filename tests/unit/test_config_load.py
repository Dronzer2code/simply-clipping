"""T-002..T-005: config models, loader, Rule Sets, grids and app defaults."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pytest

from pitwall_sim.config.loader import (
    ConfigError,
    check_grid_against_teams,
    format_unresolved,
    load_app,
    load_grid,
    load_model,
    load_race_config,
    load_rule_set,
    load_team_performance,
    load_tyres,
    resolve_harvest_limit_mj,
    unresolved_keys,
)
from pitwall_sim.config.models import Compound, RuleSet, TrackConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

RULE_SET_IDS = ("2026_pre_miami", "2026_post_miami")
GRID_IDS = ("real_2026", "fictional")
DRIVERS_PER_GRID = 22


# --------------------------------------------------------------------------- #
# T-003: test_rules_load
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_set_id", RULE_SET_IDS)
def test_rules_load(rule_set_id: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Both Rule Sets load, validate, and report their unresolved keys.

    docs/spec/TRD.md RULE SET VALUES leaves several 2026 values UNRESOLVED and
    CLAUDE.md forbids agents deciding them, so this test does not fail on them:
    it prints the list so every task report can quote it (HR-09).
    """
    rules = load_rule_set(rule_set_id, CONFIG_DIR)

    assert rules.rule_set_id == rule_set_id
    assert rules.power.p_ice_max_kw_nominal == 400
    assert rules.power.p_k_max_kw == 350
    assert rules.overtake.activation_gap_s == 1.0
    assert rules.energy.e_usable_max_mj == 4.0

    unresolved = unresolved_keys(rules, f"config/rules/{rule_set_id}.yaml")
    with capsys.disabled():
        print(f"\n{rule_set_id}: {len(unresolved)} unresolved keys")
        print(format_unresolved(unresolved))

    # Owner decision round 3 resolved the last open rule values.
    assert not unresolved


def test_pre_miami_values_match_the_reference_source() -> None:
    """Pre-Miami values follow Formula1.com per owner decision 2026-10-19.

    Values that article does not state must stay UNRESOLVED, so this test pins
    both halves: what is now verified, and what must remain a placeholder.
    """
    pre = load_rule_set("2026_pre_miami", CONFIG_DIR)

    assert pre.effective_from == date(2026, 3, 8)  # Australian GP
    assert pre.power.p_ice_max_kw_nominal == 400
    assert pre.power.p_k_max_kw == 350
    # MGU-K deployment tapers from 290 km/h to zero at 355 km/h.
    assert pre.power.boost_taper_start_kmh == 290
    assert pre.power.boost_taper_end_kmh == 355
    # Overtake mode: 350 kW up to 337 km/h, ~0.5 MJ extra, within 1 s.
    assert pre.overtake.taper_start_kmh == 337
    assert pre.overtake.extra_energy_mj_per_lap == 0.5
    assert pre.overtake.activation_gap_s == 1.0
    # Braking energy recovery ~8.5 MJ per lap.
    assert pre.energy.harvest_max_mj_per_lap_race == 8.5

    # Owner decision round 2: no per-lap deploy limit, no counter reset.
    assert pre.energy.deploy_max_mj_per_lap is None
    assert pre.energy.energy_counter_reset == "none"


def test_post_miami_keeps_the_trd_values() -> None:
    """Post-Miami: TRD Miami changes, plus unchanged pre-Miami values (round 2)."""
    pre = load_rule_set("2026_pre_miami", CONFIG_DIR)
    post = load_rule_set("2026_post_miami", CONFIG_DIR)

    assert post.effective_from == date(2026, 5, 3)  # Miami GP
    # No Miami change announced: tapers and Overtake extra energy carry over.
    assert post.power.boost_taper_start_kmh == pre.power.boost_taper_start_kmh == 290
    assert post.power.boost_taper_end_kmh == pre.power.boost_taper_end_kmh == 355
    assert post.overtake.taper_start_kmh == pre.overtake.taper_start_kmh == 337
    assert post.overtake.taper_end_kmh == pre.overtake.taper_end_kmh == 355
    assert post.overtake.extra_energy_mj_per_lap == 0.5
    # Race harvest default 8.5 MJ (9.0 MJ with Overtake) in both Rule Sets.
    assert post.energy.harvest_max_mj_per_lap_race == 8.5
    assert post.energy.deploy_max_mj_per_lap is None


@pytest.mark.parametrize("rule_set_id", RULE_SET_IDS)
def test_round_3_rule_values(rule_set_id: str) -> None:
    """Owner decision round 3: mass, fuel energy flow and track limits, both Rule Sets."""
    rules = load_rule_set(rule_set_id, CONFIG_DIR)

    assert rules.car.min_mass_kg == 768
    assert rules.fuel.max_fuel_energy_flow_mj_per_h == 3000
    # B/W flag on the 3rd offence, 5 s penalty from the 4th.
    assert rules.race.track_limits_warnings_before_penalty == 3


def test_rule_sets_differ_where_the_docs_say_they_differ() -> None:
    """The two Rule Sets carry the post-Miami changes from TRD RULE SET VALUES."""
    pre = load_rule_set("2026_pre_miami", CONFIG_DIR)
    post = load_rule_set("2026_post_miami", CONFIG_DIR)

    # Zone caps: single value pre-Miami, split by zone tag post-Miami.
    assert pre.power.zone_caps_kw.acceleration_zone == pre.power.zone_caps_kw.other == 350
    assert post.power.zone_caps_kw.acceleration_zone == 350
    assert post.power.zone_caps_kw.other == 250

    # Boost net addition cap: none pre-Miami, 150 kW post-Miami.
    assert pre.power.boost_net_cap_kw is None
    assert post.power.boost_net_cap_kw == 150

    # Qualifying recharge and super-clip power both change.
    assert pre.energy.harvest_max_mj_per_lap_quali == 8.0
    assert post.energy.harvest_max_mj_per_lap_quali == 7.0
    assert pre.energy.superclip_power_kw == 250
    assert post.energy.superclip_power_kw == 350

    # Formation-lap counter reset is phased in after Miami.
    assert post.energy.energy_counter_reset == "formation_lap_start"


# --------------------------------------------------------------------------- #
# T-002: validation and unresolved-key reporting
# --------------------------------------------------------------------------- #


def test_wrong_type_fails_with_a_clear_error(tmp_path: Path) -> None:
    """A Rule Set with a non-numeric power value is rejected, naming the key."""
    good = (CONFIG_DIR / "rules" / "2026_post_miami.yaml").read_text(encoding="utf-8")
    bad_path = tmp_path / "broken.yaml"
    bad_path.write_text(
        good.replace("p_k_max_kw: 350", 'p_k_max_kw: "very fast"'), encoding="utf-8"
    )

    with pytest.raises(ConfigError) as exc_info:
        load_model(bad_path, RuleSet)

    message = str(exc_info.value)
    assert "broken.yaml" in message
    assert "RuleSet" in message
    assert "power.p_k_max_kw" in message


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """An unexpected key is an error, not a silently ignored typo."""
    good = (CONFIG_DIR / "rules" / "2026_post_miami.yaml").read_text(encoding="utf-8")
    bad_path = tmp_path / "extra.yaml"
    bad_path.write_text(good + "\nmystery_section: 1\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="mystery_section"):
        load_model(bad_path, RuleSet)


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    """A YAML file whose top level is not a mapping fails with a clear error."""
    bad_path = tmp_path / "list.yaml"
    bad_path.write_text("- 1\n- 2\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="top level must be a mapping"):
        load_model(bad_path, RuleSet)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    """A missing config file fails with a clear error naming the path."""
    with pytest.raises(ConfigError, match="cannot be read"):
        load_model(tmp_path / "absent.yaml", RuleSet)


def test_loader_reports_unresolved_keys_across_every_file() -> None:
    """load_race_config returns one entry per UNRESOLVED / UNKNOWN value."""
    loaded = load_race_config("2026_post_miami", "real_2026", "suzuka", config_dir=CONFIG_DIR)

    assert loaded.unresolved, "expected the known open items to be reported"
    assert all(key.placeholder in {"UNRESOLVED", "UNKNOWN"} for key in loaded.unresolved)

    reported = {(key.source, key.key) for key in loaded.unresolved}
    assert ("config/tracks/suzuka.yaml", "abrasiveness") in reported  # F20 calibration
    # T-051 set the last Radar constant.
    assert ("config/app.yaml", "radar.confidence_half_life_s") not in reported

    # Resolved by the owner on 2026-10-19: these must no longer be placeholders.
    assert ("config/app.yaml", "debrief.score_scale_s") not in reported
    assert ("config/app.yaml", "radio.model_variant") not in reported
    assert ("config/app.yaml", "radio.model_path") not in reported
    # Round 3: no rule value is left open.
    assert not any(key.source.startswith("config/rules/") for key in loaded.unresolved)
    # Round 2: Radar spec starting values and the race harvest default.
    assert ("config/app.yaml", "radar.mass_kg") not in reported
    assert (
        "config/rules/2026_post_miami.yaml",
        "energy.harvest_max_mj_per_lap_race",
    ) not in reported


# --------------------------------------------------------------------------- #
# T-004: grids, team performance, tyres
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("grid_id", GRID_IDS)
def test_grid_has_22_drivers_and_known_teams(grid_id: str) -> None:
    """Each grid fields 22 cars and every team_id has a performance entry."""
    grid = load_grid(grid_id, CONFIG_DIR)
    teams = load_team_performance(CONFIG_DIR)

    assert grid.grid_id == grid_id
    assert len(grid.driver_ids) == DRIVERS_PER_GRID
    assert len(set(grid.driver_ids)) == DRIVERS_PER_GRID, "driver_id values must be unique"
    assert len(set(grid.team_ids)) == len(grid.team_ids), "team_id values must be unique"

    check_grid_against_teams(grid, teams)
    for team_id in grid.team_ids:
        assert team_id in teams.teams


@pytest.mark.parametrize("grid_id", GRID_IDS)
def test_grid_driver_numbers_are_unique(grid_id: str) -> None:
    """Two cars cannot carry the same number."""
    grid = load_grid(grid_id, CONFIG_DIR)
    numbers = [d.number for t in grid.teams for d in t.drivers]
    assert len(set(numbers)) == len(numbers)


def test_grid_missing_from_performance_is_rejected() -> None:
    """A grid team with no performance entry fails the cross-file check."""
    grid = load_grid("fictional", CONFIG_DIR)
    teams = load_team_performance(CONFIG_DIR)
    dropped = grid.team_ids[0]
    teams.teams.pop(dropped)

    with pytest.raises(ConfigError, match=dropped):
        check_grid_against_teams(grid, teams)


def test_real_grid_has_a_colour_and_pu_maker_for_every_team() -> None:
    """FastF1 session data has no 2026 TeamColor, so these come from config."""
    grid = load_grid("real_2026", CONFIG_DIR)

    for team in grid.teams:
        assert team.color_hex.startswith("#"), f"{team.team_id} has no colour"
        assert len(team.color_hex) == 7
        assert team.pu_maker not in {"UNKNOWN", "UNRESOLVED"}, team.team_id

    # Both grids must be colour-complete so the UI never needs the fallback.
    assert not unresolved_keys(grid, "config/grid/real_2026.yaml")


def test_real_grid_colours_are_the_fastf1_2026_colours() -> None:
    """Owner decision round 3: FastF1 3.8.3 plotting constants, 2026, official."""
    grid = load_grid("real_2026", CONFIG_DIR)
    by_id = {team.team_id: team.color_hex for team in grid.teams}

    assert by_id == {
        "red_bull": "#3671C6",
        "ferrari": "#E80020",
        "mercedes": "#27F4D2",
        "mclaren": "#FF8000",
        "rb": "#6692FF",
        "audi": "#FF2D00",
        "alpine": "#0093CC",
        "haas": "#B6BABD",
        "williams": "#64C4FF",
        "aston_martin": "#229971",
        "cadillac": "#444444",
    }


def test_real_grid_pu_makers_match_the_owner_table() -> None:
    """The 2026 engine supply the owner confirmed."""
    grid = load_grid("real_2026", CONFIG_DIR)
    by_id = {team.team_id: team.pu_maker for team in grid.teams}

    assert by_id == {
        "mclaren": "Mercedes",
        "ferrari": "Ferrari",
        "red_bull": "Red Bull Ford Powertrains",
        "mercedes": "Mercedes",
        "aston_martin": "Honda",
        "alpine": "Mercedes",
        "williams": "Mercedes",
        "rb": "Red Bull Ford Powertrains",
        "haas": "Ferrari",
        "audi": "Audi",
        "cadillac": "Ferrari",
    }


def test_tyres_cover_every_compound() -> None:
    """config/tyres.yaml has one entry per compound named in TRD Tyres."""
    tyres = load_tyres(CONFIG_DIR)
    assert set(tyres.compounds) == set(Compound)


# --------------------------------------------------------------------------- #
# T-005: app.yaml defaults
# --------------------------------------------------------------------------- #


def test_app_defaults_match_the_trd() -> None:
    """config/app.yaml carries the defaults stated in docs/spec/TRD.md."""
    app = load_app(CONFIG_DIR)

    assert app.sim.dt_s == 0.05
    assert app.sim.decision_tick_s == 1.0
    assert app.feed.rate_hz == 4
    assert app.ui.refresh_hz == 10

    assert app.feed.drop_p == 0.05
    assert app.feed.speed_noise_kmh == 0.5
    assert app.feed.throttle_noise_pct == 1.0
    assert app.feed.position_noise_m == 1.0

    assert app.radar.resample_hz == 10
    assert app.radar.savgol_window == 7
    assert app.radar.savgol_order == 2

    assert app.predictor.n_samples == 16
    assert app.predictor.horizon_laps == 15

    assert app.debrief.k_alternatives == 4
    assert app.debrief.n_seeds == 8

    assert app.radio.radio_latency_s == 1.0
    assert app.radio.parse_timeout_s == 2.0
    assert app.radio.reply_timeout_s == 1.5
    assert app.calibration.speed_rmse_kmh == 15  # owner round 15

    assert app.paths.fastf1_cache == "data/fastf1_cache"


def test_app_carries_the_owner_decisions() -> None:
    """Values the owner fixed on 2026-10-19."""
    app = load_app(CONFIG_DIR)

    assert app.ui.window_title == "We Are Racing, Not Testing"
    assert app.debrief.score_scale_s == 20
    assert app.radio.model_variant == "gemma-3-270m-it"
    assert app.radio.model_path == "models/gemma-3-270m-it-pitwall.gguf"
    assert app.ui.fallback_palette, "a fallback palette is required for missing colours"


def test_debrief_score_scale_gives_the_owners_curve() -> None:
    """Score 100*exp(-loss/score_scale_s) with scale 20: 5 s -> 78, 10 s -> 61, 20 s -> 37."""
    scale = load_app(CONFIG_DIR).debrief.score_scale_s
    assert not isinstance(scale, str)

    def score(loss_s: float) -> int:
        return round(100.0 * math.exp(-loss_s / scale))

    assert score(5.0) == 78
    assert score(10.0) == 61
    assert score(20.0) == 37


def test_radar_starts_from_the_radar_spec_values() -> None:
    """Round 2: Radar constants are the Radar spec values, finalised in T-051."""
    radar = load_app(CONFIG_DIR).radar

    assert radar.mass_kg == 800
    assert radar.p_ice_kw == 400
    assert radar.p_elec_max_kw == 350
    assert radar.e_max_mj == 4.0
    assert radar.eta == 0.92
    assert radar.rho == 1.18
    assert radar.c_rr == 0.012
    assert radar.min_confidence == 0.5


# --------------------------------------------------------------------------- #
# Race harvest limit: user value -> track override -> Rule Set default
# --------------------------------------------------------------------------- #


def _track(harvest_mj: float | None) -> TrackConfig:
    unknown = "UNKNOWN"
    return TrackConfig.model_validate(
        {
            "track_id": "test",
            "fastf1_event": "Test",
            "official_length_m": 5000.0,
            "geometry_source": {"year": 2026, "session": "Q", "driver": "fastest"},
            "pit": {"entry_s_m": 0, "exit_s_m": 0, "lane_speed_kmh": 80, "lane_loss_s": unknown},
            "abrasiveness": unknown,
            "weather": {"rain_p_per_race": unknown, "transition_matrix": unknown},
            "events": {"incident_rate_per_lap": unknown, "sc_share": unknown},
            "evolution_per_lap": unknown,
            **({} if harvest_mj is None else {"harvest_max_mj_per_lap_race": harvest_mj}),
        }
    )


@pytest.mark.parametrize("rule_set_id", RULE_SET_IDS)
def test_harvest_limit_falls_back_to_the_rule_set_default(rule_set_id: str) -> None:
    rules = load_rule_set(rule_set_id, CONFIG_DIR)

    assert resolve_harvest_limit_mj(rules) == 8.5
    assert resolve_harvest_limit_mj(rules, _track(None)) == 8.5


def test_harvest_limit_track_override_then_user_value() -> None:
    rules = load_rule_set("2026_post_miami", CONFIG_DIR)

    assert resolve_harvest_limit_mj(rules, _track(7.0)) == 7.0
    assert resolve_harvest_limit_mj(rules, _track(7.0), user_value_mj=9.0) == 9.0
    with pytest.raises(ConfigError, match="positive"):
        resolve_harvest_limit_mj(rules, _track(7.0), user_value_mj=0.0)


def test_track_harvest_override_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _track(0.0)
