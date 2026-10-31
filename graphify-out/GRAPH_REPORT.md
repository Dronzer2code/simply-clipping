# Graph Report - F1  (2026-10-26)

## Corpus Check
- 155 files · ~144,880 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 2, .geojson 1, .parquet 1)

## Summary
- 3577 nodes · 8775 edges · 195 communities (132 shown, 63 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 1023 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `50af7630`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- RaceEngine
- test_deploy_policy.py
- engine.py
- calibration/compare.py
- load_app
- test_config_load.py
- fit.py
- test_powertrain.py
- state.py
- ReplayWindow
- call_outcome.py
- ai_driver.py
- test_snapshot.py
- builder.py
- TrackModel
- test_battery.py
- test_aero_fuel_tyres.py
- test_pit.py
- lap_sim.py
- rival_strategy.py
- LiveSession
- session.py
- loader.py
- speed_profile.py
- build_centre_line
- test_speed_profile.py
- test_alerts.py
- app.yaml
- pytest
- 2026_post_miami.yaml
- 2026_pre_miami.yaml
- PublicFeedFrame
- test_ai_driver.py
- WeatherModel
- numpy
- numpy
- RaceSetup
- TRD.md — Pit Wall Race Simulator (2026 Regulations)
- outline.py
- test_openf1.py
- R1 — MVP PROMPTS
- alerts.py
- EngineerView
- step_kernel.py
- DriverInstructions
- PitWallWindow
- commands.py
- PRD.md — Pit Wall Race Simulator (2026 Regulations)
- corner_sources.py
- pitwall_lite.py
- .__init__
- ._events
- accel_zones.py
- test_commands_effect.py
- test_mistakes.py
- dataclasses
- radar
- PROCESS_FLOW.md — Pit Wall Race Simulator (2026 Regulations)
- .timing_state
- SESSION_CONTEXT.md
- integration/test_rival_strategy.py
- test_radar.py
- test_info_barrier.py
- zone_mask
- R1 — MVP
- pathlib
- RadarBank
- calibration
- reference.py
- rival_strategy
- alpine
- aston_martin
- audi
- aurora
- brontes
- cadillac
- calder
- driftwood
- equinox
- ferrari
- fulcrum
- greystone
- haas
- halcyon
- ironwood
- juniper
- kestrel
- mclaren
- mercedes
- rb
- red_bull
- williams
- TrackConfig
- test_calls.py
- energy.py
- models.py
- StrictModel
- test_headless_runtime.py
- ai_driver
- alerts
- RadarEstimate
- mistakes
- drivers
- drivers
- suzuka.yaml
- test_accel_zones.py
- Quick start (Windows)
- overtake
- weather
- track_builder
- MVP.md — Pit Wall Race Simulator (2026 Regulations)
- PitConfig
- test_live.py
- SETUP.md — Pit Wall Race Simulator (2026 Regulations)
- UI_DESIGN.md — Pit Wall Race Simulator (2026 Regulations)
- test_step_kernel.py
- engineer
- openf1
- Calibration notes
- AlertCard
- CLAUDE.md — Agent Entry Point for `pitwall_sim`
- HARD
- INTERMEDIATE
- MEDIUM
- SOFT
- WET
- debrief
- SimThread
- draw_mistake
- GeometrySource
- feed
- paths
- pit
- TeamEntry
- ZoneCapsKw
- race_engine
- outline
- pit
- zones
- compounds
- load_factor
- decide
- geometry_source
- corners
- SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)
- events
- weather
- teams
- zone_difficulty
- RadioConfig
- DebriefConfig
- FuelRules
- LoadSensitivity
- PredictorConfig
- TrackWeatherConfig
- TrackEventsConfig
- SlipstreamConfig
- pitwall_sim

## God Nodes (most connected - your core abstractions)
1. `RaceEngine` - 178 edges
2. `TrackConfig` - 100 edges
3. `load_app()` - 99 edges
4. `Compound` - 99 edges
5. `load_track()` - 94 edges
6. `ConfigError` - 68 edges
7. `load_team_performance()` - 60 edges
8. `TrackModel` - 59 edges
9. `StrictModel` - 54 edges
10. `RaceSetup` - 54 edges

## Surprising Connections (you probably didn't know these)
- `T-02A round 13 diagnosis (2026-10-24), before the last fit` --references--> `load_team_references()`  [INFERRED]
  docs/CALIBRATION_NOTES.md → pitwall_sim/calibration/compare.py
- `Powertrain (`car/powertrain.py`)` --references--> `PowertrainParams`  [INFERRED]
  docs/TRD.md → pitwall_sim/car/powertrain.py
- `RULE SET VALUES` --references--> `boost_cap_w()`  [INFERRED]
  docs/TRD.md → pitwall_sim/car/powertrain.py
- `Block 7: UI` --references--> `resolve_harvest_limit_mj()`  [INFERRED]
  docs/TASKS.md → pitwall_sim/config/loader.py
- `Command bar` --references--> `CommandType`  [INFERRED]
  docs/UI_DESIGN.md → pitwall_sim/engineer/commands.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Sprint day 4 steps 1-4** — docs_session_context_day4_step1_radar_unknown, docs_session_context_day4_step2_alert_quality, docs_session_context_day4_step3_overtake_weights, docs_session_context_day4_step4_summary_presets [EXTRACTED 1.00]

## Communities (195 total, 63 thin omitted)

### Community 0 - "RaceEngine"
Cohesion: 0.04
Nodes (13): apply(), _battery(), rival_ahead(), RaceEngine, test_let_teammate_by(), _published(), race(), test_frame_rate_and_drop_rate_match_config() (+5 more)

### Community 1 - "test_deploy_policy.py"
Cohesion: 0.11
Nodes (27): acceleration_zone_index(), BoolArray, DeployPlan, FloatArray, _fund(), _harvest_per_point(), _in_zone(), IntArray (+19 more)

### Community 2 - "engine.py"
Cohesion: 0.08
Nodes (17): OPEN owner decision: structural DEFEND (hold until threat passes) / ATTACK (close the gap), OvertakeConfig, _close_hits(), crossed(), FloatArray, OvertakeModel, p_pass(), trigger_points() (+9 more)

### Community 3 - "calibration/compare.py"
Cohesion: 0.08
Nodes (23): BoolArray, DeployMode, FloatArray, load_team_references(), log_results(), order_ok(), positions(), section_coverage() (+15 more)

### Community 4 - "load_app"
Cohesion: 0.07
Nodes (45): main(), rule_set_for_date(), track_arrays(), aero_mode(), reference_params(), load_app(), load_model(), load_race_config() (+37 more)

### Community 5 - "test_config_load.py"
Cohesion: 0.04
Nodes (33): Battery (`car/battery.py`), check_grid_against_teams(), format_unresolved(), load_grid(), resolve_harvest_limit_mj(), unresolved_keys(), UnresolvedKey, _walk() (+25 more)

### Community 6 - "fit.py"
Cohesion: 0.04
Nodes (59): compare_teams(), lap_of(), ReferenceLap, speed_rmse_kmh(), apply(), bound_hits(), _calibrated_comment(), calibration_notes() (+51 more)

### Community 7 - "test_powertrain.py"
Cohesion: 0.09
Nodes (27): boost_cap_w(), ice_power_w(), linear_taper(), mgu_k_allowed_w(), mgu_k_deploy_w(), overtake_available(), overtake_extra_energy_j(), powertrain_params() (+19 more)

### Community 8 - "state.py"
Cohesion: 0.07
Nodes (21): _plan_key(), _shape_key(), AeroMode, CarArrays, CarState, CarStatus, _check_mirror_covers_car_state(), EnergyModeName (+13 more)

### Community 9 - "ReplayWindow"
Cohesion: 0.08
Nodes (9): ReplayWindow, main(), record(), Replay, app(), replay(), test_recording_round_trips(), test_viewer_plays_at_16x_fast_enough() (+1 more)

### Community 10 - "call_outcome.py"
Cohesion: 0.11
Nodes (9): _ahead(), first_alert(), _follow(), Outcome, outcome(), overtakes_per_race(), CallRunner, EngineerViewBuilder (+1 more)

### Community 11 - "ai_driver.py"
Cohesion: 0.07
Nodes (22): AI DRIVER (`driver/ai_driver.py`), Per-step order (`race/engine.py`), AiDriverConfig, BoolArray, CarPlan, decide_all(), deploy_fractions(), EnergyBalance (+14 more)

### Community 12 - "test_snapshot.py"
Cohesion: 0.09
Nodes (21): Block 4: Determinism and rivals, ARCHITECTURE PRINCIPLES, SNAPSHOT AND DETERMINISM (`race/snapshot.py`) — F09, TESTING, EngineerCommand, fork(), restore(), rng_states() (+13 more)

### Community 13 - "builder.py"
Cohesion: 0.10
Nodes (16): build_from_laps(), _Curve, _drop_repeated_points(), FloatArray, IntArray, load_laps_xy(), load_laps_xy_fastf1(), main() (+8 more)

### Community 14 - "TrackModel"
Cohesion: 0.07
Nodes (23): CALIBRATION (`calibration/compare.py`) — F20, load_reference_lap(), reference_from_lap(), _timestamp(), valid_car_samples(), project_path_to_s(), TrackModel, multiviewer_corners() (+15 more)

### Community 15 - "test_battery.py"
Cohesion: 0.11
Nodes (21): Block 2: Single-car physics, BatteryParams, BatteryStep, lap_harvest_limit_j(), part_throttle_harvest_w(), reset_at_formation_lap(), reset_at_timing_line(), step() (+13 more)

### Community 16 - "test_aero_fuel_tyres.py"
Cohesion: 0.15
Nodes (13): f_temp(), f_wear(), mu_tyre(), step_wear(), tyre_temp_c(), TyreParams, wear_rate_per_s(), test_f_wear_has_a_cliff_and_is_continuous() (+5 more)

### Community 17 - "test_pit.py"
Cohesion: 0.08
Nodes (17): PIT LANE (`race/pit.py`), FloatArray, PitEvent, PitLane, PitPhase, make_rngs(), exit_lap(), _first_two() (+9 more)

### Community 18 - "lap_sim.py"
Cohesion: 0.15
Nodes (10): run(), AeroParams, cda(), available_deploy_w(), braking_harvest_w(), BoolArray, FloatArray, IntArray (+2 more)

### Community 19 - "rival_strategy.py"
Cohesion: 0.09
Nodes (18): HARD RULES, PF-06 INFORMATION FLOW AND BARRIER, RIVAL STRATEGY AI (`race/rival_strategy.py`), battle_inputs(), BoolArray, _box(), decide(), decide_book() (+10 more)

### Community 20 - "LiveSession"
Cohesion: 0.08
Nodes (13): DAY 4 DETAILS, grid_order(), _Ack, CallSummary, LiveSession, LiveSetup, RadioLine, SummaryDialog (+5 more)

### Community 21 - "session.py"
Cohesion: 0.11
Nodes (10): alert_line(), CallOption, CallStep, _coming_straight(), _ignore(), options(), _why(), _ahead() (+2 more)

### Community 22 - "loader.py"
Cohesion: 0.07
Nodes (20): aero_params(), _value(), dirty_air_params(), DirtyAirParams, tyre_params(), LoadedConfig, AeroConfig, AppConfig (+12 more)

### Community 23 - "speed_profile.py"
Cohesion: 0.14
Nodes (22): _accel_jit(), _accel_ms2(), _backward_jit(), backward_pass(), _bool(), BoolArray, brake_decel_ms2(), corner_limits() (+14 more)

### Community 24 - "build_centre_line"
Cohesion: 0.08
Nodes (41): TrackBuilderConfig, build_centre_line(), pool_laps(), TrackValidationError, validate_length(), _limacon(), test_alignment_recovers_a_moved_mirrored_outline(), test_blend_weight_and_corner_blend() (+33 more)

### Community 25 - "test_speed_profile.py"
Cohesion: 0.07
Nodes (27): cla(), air_density(), car_mass_kg(), downforce_n(), drag_n(), drive_force_n(), ellipse_long_fraction(), normal_force_n() (+19 more)

### Community 26 - "test_alerts.py"
Cohesion: 0.10
Nodes (30): AlertsConfig, SimplyClippingLite, PublicWeather, _car(), cfg(), _clip_case(), _own_battery(), _pass() (+22 more)

### Community 27 - "app.yaml"
Cohesion: 0.06
Nodes (33): acceleration_zones, min_length_m, min_speed_change_kmh, reference_rule_set, aero, straight_mode_throttle_min, dirty_air, downforce_loss_max (+25 more)

### Community 28 - "pytest"
Cohesion: 0.14
Nodes (16): burn(), fuel_flow_w(), fuel_params(), FuelParams, max_ice_power_w(), _value(), reference_profile(), test_fuel_burn_matches_energy_over_density() (+8 more)

### Community 29 - "2026_post_miami.yaml"
Cohesion: 0.06
Nodes (30): car, min_mass_kg, effective_from, energy, deploy_max_mj_per_lap, e_usable_max_mj, energy_counter_reset, harvest_max_mj_per_lap_quali (+22 more)

### Community 30 - "2026_pre_miami.yaml"
Cohesion: 0.06
Nodes (30): car, min_mass_kg, effective_from, energy, deploy_max_mj_per_lap, e_usable_max_mj, energy_counter_reset, harvest_max_mj_per_lap_quali (+22 more)

### Community 31 - "PublicFeedFrame"
Cohesion: 0.11
Nodes (6): FeedConfig, PublicFeedFrame, BoolArray, FloatArray, PublicFeed, _Tick

### Community 32 - "test_ai_driver.py"
Cohesion: 0.13
Nodes (15): _lap(), _plan(), _shape(), _sit(), test_attack_and_defend_force_boost_and_lines(), test_attack_uses_all_the_grip_and_defend_keeps_deploy_for_the_straights(), test_boost_rules_by_mode(), test_energy_balance_corrects_a_steady_loss() (+7 more)

### Community 34 - "numpy"
Cohesion: 0.19
Nodes (16): LapResult, _anywhere_lap(), _lap(), test_budget_mode_clips_every_zone(), run(), test_clip_is_bounded_by_the_shortfall_and_picks_the_fastest_lap(), run(), test_energy_is_split_by_zone_length() (+8 more)

### Community 35 - "numpy"
Cohesion: 0.14
Nodes (12): feasible_budgets(), allocate(), BoolArray, deploy_demand_j(), DeployAllocation, FloatArray, full_throttle_runs(), IntArray (+4 more)

### Community 36 - "RaceSetup"
Cohesion: 0.07
Nodes (24): format_result(), RaceResult, RaceSetup, run_headless(), RunTiming, full_race(), _short(), test_a_car_out_of_fuel_retires() (+16 more)

### Community 37 - "TRD.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.06
Nodes (34): Active aero (`car/aero.py`), Alternate Race mode (F18), `config/app.yaml`, `config/grid/<grid>.yaml`, `config/rules/<rule_set>.yaml`, CONFIG SCHEMAS, `config/tracks/<track_id>.yaml`, CONTEXT (+26 more)

### Community 38 - "outline.py"
Cohesion: 0.13
Nodes (10): align_to_model(), apply_outline(), blend_corners(), blend_weight(), corner_windows(), densify(), FloatArray, outline_curvature() (+2 more)

### Community 39 - "test_openf1.py"
Cohesion: 0.07
Nodes (25): OpenF1Config, Fetch, FloatArray, load_lap_xy_openf1(), load_laps_xy_openf1(), RateLimiter, cfg(), _client() (+17 more)

### Community 40 - "R1 — MVP PROMPTS"
Cohesion: 0.08
Nodes (25): BUILD_PROMPTS.md — Pit Wall Race Simulator (2026 Regulations), OPERATOR RULES, P-00 SESSION START (prepend to every prompt), P-01 Foundation (T-001 → T-005), P-02 Track (T-010 → T-011), P-03 Single-car physics (T-020 → T-025), P-04 Calibration (T-026), P-05 Race (T-030 → T-036) (+17 more)

### Community 41 - "alerts.py"
Cohesion: 0.12
Nodes (6): PowerRules, _Estimate, _evidence(), make_provider(), _overlap_m(), _Straight

### Community 42 - "EngineerView"
Cohesion: 0.12
Nodes (5): S — Deadline sprint: alerts and calling the driver (owner, 2026-10-26 to 2026-10-31), AlertProvider, EngineerView, provider(), test_provider_reads_engineer_view_only()

### Community 43 - "step_kernel.py"
Cohesion: 0.06
Nodes (41): Dirty air and slipstream (`car/dirty_air.py`), Step kernel (`race/step_kernel.py`, `T-030`), BoolArray, downforce_scale(), drag_scale(), FloatArray, gaps_ahead_m(), IntArray (+33 more)

### Community 44 - "DriverInstructions"
Cohesion: 0.23
Nodes (12): RivalStrategyConfig, DriverInstructions, cfg(), _plan(), test_battle_flags_use_the_radar_estimate(), test_battle_inputs_read_only_positions_gaps_and_radar(), test_compiled_decisions_match_the_scalar_rules(), test_harvest_hysteresis_reads_the_battery_at_the_line() (+4 more)

### Community 46 - "commands.py"
Cohesion: 0.08
Nodes (33): ENGINEER COMMANDS (`engineer/commands.py`) — F12, EngineerConfig, _issuer(), issue(), _bool(), _box(), _cancel_box(), _choice() (+25 more)

### Community 47 - "PRD.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.08
Nodes (24): CONSTRAINTS, CONTEXT, DECISIONS LOG, Engineer controls (`F12`), Extras (`F14`, `F16`, `F17`, `F18`), FEATURES, FUNCTIONAL REQUIREMENTS, GLOSSARY (CANONICAL TERMS) (+16 more)

### Community 48 - "corner_sources.py"
Cohesion: 0.07
Nodes (11): quali_fuel_kg(), write_report(), choose_sources(), CornerSource, implied_radius_m(), main(), write_corners(), cfg() (+3 more)

### Community 52 - "accel_zones.py"
Cohesion: 0.22
Nodes (6): derive_zones(), DerivedZone, FloatArray, main(), reference_speed_kmh(), turning_points()

### Community 53 - "test_commands_effect.py"
Cohesion: 0.08
Nodes (25): EnergyMode, AlertRun, run_alerts(), OvertakeEvent, engine(), _engine(), _fork(), _issue() (+17 more)

### Community 54 - "test_mistakes.py"
Cohesion: 0.18
Nodes (8): MistakesConfig, cfg(), _engine(), test_mistakes_are_deterministic_and_change_the_race(), test_mistakes_in_a_race_use_only_their_stream(), test_outcomes_follow_the_shares(), test_rate_scales_with_wear_wetness_and_consistency(), p()

### Community 55 - "dataclasses"
Cohesion: 0.21
Nodes (3): PURPOSE, PredictorOutput, RadioMessage

### Community 56 - "radar"
Cohesion: 0.09
Nodes (23): radar, anchor_min_s, c_rr, confidence_half_life_s, e_max_mj, eta, fit_max_speed_kmh, fit_min_samples (+15 more)

### Community 57 - "PROCESS_FLOW.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.09
Nodes (22): CONTEXT, FLOW INDEX, OPEN ITEMS, PF-01 OFFLINE: TRACK BUILD, PF-02 OFFLINE: CALIBRATION, PF-03 APP START AND RACE SETUP, PF-04 SIMULATION TICK, PF-05 CLOCK AND UI REFRESH (+14 more)

### Community 59 - "SESSION_CONTEXT.md"
Cohesion: 0.24
Nodes (5): Deadline sprint (until 2026-10-31): days 1-4 done, next day 5 README quick start + polish (S-6), Known issue: Radar after anchor MAE ~1.44 MJ, bias -1.41 MJ (anchors on super-clips), not tuned, Known issue: timing tests (headless runtime, step kernel budget, UI 16x frame) fail under machine load, Parked until after the sprint: S-1, S-3, S-4, T-02B/C/D, T-038, T-062, R3-R5, Short races show almost no ATTACK/DEFEND alerts (Radar confidence <0.4 before anchors)

### Community 60 - "integration/test_rival_strategy.py"
Cohesion: 0.22
Nodes (4): _battle(), race(), _Recorder, test_mvp10_rivals_pit_and_change_energy_mode_unaided()

### Community 61 - "test_radar.py"
Cohesion: 0.13
Nodes (9): RIVAL BATTERY RADAR (`observe/radar/`) — F11, estimate_batch(), RadarEstimator, test_compiled_radar_matches_the_python_reference(), test_engine_radar_equals_a_standalone_estimator(), test_incremental_equals_batch(), test_radar_uses_its_own_constants(), test_savgol_weights_and_confidence_half_life() (+1 more)

### Community 62 - "test_info_barrier.py"
Cohesion: 0.25
Nodes (4): test_info_barrier(), test_view_contents(), view_and_engine(), _walk()

### Community 63 - "zone_mask"
Cohesion: 0.11
Nodes (9): Zone, _Timing, _in_zone(), zone_ids_mask(), zone_mask(), test_filter_by_type_and_tag(), test_needs_a_filter(), test_zone_crossing_the_timing_line() (+1 more)

### Community 64 - "R1 — MVP"
Cohesion: 0.08
Nodes (23): COMMANDS, KNOWN ISSUES, OWNER WORKING RULES (from the chats, on top of `CLAUDE.md`), SESSION_CONTEXT — handoff for a new agent session, WHAT EACH SPRINT DAY BUILT, WHERE THE PROJECT STANDS, Block 0: Foundation, Block 1: Track (+15 more)

### Community 65 - "pathlib"
Cohesion: 0.07
Nodes (22): main(), pit_stop_stats(), PitStopStats, main(), _f(), main(), main(), _get_json() (+14 more)

### Community 68 - "calibration"
Cohesion: 0.11
Nodes (19): cda_corner, cda_straight, cla_corner, k_load, long_grip_ratio, mu_base_soft, pu_power_scale, calibration (+11 more)

### Community 69 - "reference.py"
Cohesion: 0.12
Nodes (7): RadarState, electric_power_w(), FloatArray, resample(), savgol_coefficients(), wheel_power_w(), _ModeFit

### Community 70 - "rival_strategy"
Cohesion: 0.11
Nodes (18): rival_strategy, attack_margin_mj, battle_gap_s, critical_wear, defend_margin_mj, low_battery_mj, no_stop_last_laps, push_final_laps (+10 more)

### Community 71 - "alpine"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 72 - "aston_martin"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 73 - "audi"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 74 - "aurora"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 75 - "brontes"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 76 - "cadillac"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 77 - "calder"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 78 - "driftwood"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 79 - "equinox"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 80 - "ferrari"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 81 - "fulcrum"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 82 - "greystone"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 83 - "haas"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 84 - "halcyon"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 85 - "ironwood"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 86 - "juniper"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 87 - "kestrel"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 88 - "mclaren"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 89 - "mercedes"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 90 - "rb"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 91 - "red_bull"
Cohesion: 0.11
Nodes (18): aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight, driveline_efficiency (+10 more)

### Community 92 - "williams"
Cohesion: 0.11
Nodes (18): williams, aggression, battery_discharge_efficiency, brake_harvest_share, cda_corner, cda_straight, cla_corner, cla_straight (+10 more)

### Community 93 - "TrackConfig"
Cohesion: 0.18
Nodes (12): TrackConfig, model(), test_acceleration_zones_are_the_three_owner_approved_straights(), test_corners_are_in_driving_order(), test_detection_point_is_turn_17(), test_every_position_is_inside_the_track(), test_model_length_is_the_official_length(), test_overtaking_zone_has_a_difficulty_entry() (+4 more)

### Community 94 - "test_calls.py"
Cohesion: 0.15
Nodes (12): _Pending, AlertEvidence, _alert(), _run(), test_each_option_sends_exactly_its_commands(), test_follow_ups_come_at_the_next_lap(), test_headline_and_radio_say_which_rule_fired(), branch() (+4 more)

### Community 95 - "energy.py"
Cohesion: 0.19
Nodes (8): _cda(), _decode_feed(), _energies(), FloatArray, _in_zones(), IntArray, _process(), _push()

### Community 96 - "models.py"
Cohesion: 0.09
Nodes (13): CalibrationConfig, CarRules, DirtyAirConfig, DriverEntry, EnergyRules, Fraction, HexColor, MaybeDate (+5 more)

### Community 97 - "StrictModel"
Cohesion: 0.10
Nodes (10): CompoundCoefficients, Corner, MultiViewerConfig, OutlineSource, PathsConfig, RaceEngineConfig, RaceRules, SimConfig (+2 more)

### Community 99 - "ai_driver"
Cohesion: 0.12
Nodes (16): ai_driver, balanced_headroom_mj, boost_gap_s, boost_reserve_mj, energy_feedback_gain, grip_margin, harvest_target_mj_per_lap, hold_gap_s (+8 more)

### Community 100 - "alerts"
Cohesion: 0.11
Nodes (19): alerts, attack_gap_s, battery_reserve_mj, clip_min_s, closing_dv_kmh, closing_min_straight_left_m, closing_range_m, defend_gap_s (+11 more)

### Community 101 - "RadarEstimate"
Cohesion: 0.18
Nodes (3): RadarEstimate, reference_estimate_batch(), ReferenceRadarEstimator

### Community 102 - "mistakes"
Cohesion: 0.13
Nodes (15): CRASH, LOCK_UP, OFF_TRACK, SPIN, mistakes, base_p_per_corner, consistency_gain, kind_shares (+7 more)

### Community 103 - "drivers"
Cohesion: 0.13
Nodes (14): code, display_name, driver_id, number, skill_consistency, skill_pace, skill_racecraft, grid_id (+6 more)

### Community 104 - "drivers"
Cohesion: 0.13
Nodes (14): code, display_name, driver_id, number, skill_consistency, skill_pace, skill_racecraft, grid_id (+6 more)

### Community 105 - "suzuka.yaml"
Cohesion: 0.13
Nodes (14): abrasiveness, acceleration_zones_source, air_pressure_hpa, air_temp_c, derived_acceleration_zones, detection_points_m, evolution_per_lap, fastf1_event (+6 more)

### Community 106 - "test_accel_zones.py"
Cohesion: 0.23
Nodes (6): AccelerationZonesConfig, cfg(), _profile(), test_suzuka_derived_zones_cover_the_manual_straights(), test_turning_points_ignore_small_dips(), test_zones_run_from_corner_exit_to_braking_point()

### Community 107 - "Quick start (Windows)"
Cohesion: 0.29
Nodes (6): Command-line checks, Quick start (Windows), Run the app, Tests, We Are Racing, Not Testing, Where things are

### Community 108 - "overtake"
Cohesion: 0.14
Nodes (14): overtake, braking_trigger_min_drop_kmh, braking_zone_difficulty, fail_time_loss_s, follow_gap_m, trigger_gap_m, w_attack, w_defend (+6 more)

### Community 109 - "weather"
Cohesion: 0.14
Nodes (14): DAMP, DRY, HEAVY_WET, WET, weather, car_drying_per_min, drying_per_min, evolution_wash_per_min (+6 more)

### Community 110 - "track_builder"
Cohesion: 0.14
Nodes (14): track_builder, centre_line_fit, length_tolerance, max_closure_gap_m, normalize_length, outline_blend_m, outline_window_max_m, pool_bin_m (+6 more)

### Community 111 - "MVP.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.14
Nodes (13): BUILD ORDER INSIDE THE MVP, CONSTRAINTS, CONTEXT, Excluded from MVP (built in later releases), Included, MVP BOUNDARY STATUS, MVP.md — Pit Wall Race Simulator (2026 Regulations), MVP OBJECTIVE (+5 more)

### Community 113 - "test_live.py"
Cohesion: 0.29
Nodes (9): _sent(), test_call_summary_opens_at_the_flag(), test_f1_answers_the_newest_alert(), test_option_button_sends_the_option_commands(), test_speed_buttons(), test_test_mode_shows_true_battery_only_when_chosen(), test_thirty_seconds_at_16x_without_a_slow_frame(), _until_alert() (+1 more)

### Community 114 - "SETUP.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.15
Nodes (12): 1. CLONE AND ENVIRONMENT, 2. DEPENDENCIES (`pyproject.toml`), 3. IMPORT CONTRACTS (`.importlinter`), 4. REAL DATA (FASTF1), 5. GEMMA MODEL (R3 ONLY), 6. COMMANDS, 7. CONFIG FILES, 8. VERIFY THE SETUP (+4 more)

### Community 115 - "UI_DESIGN.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.09
Nodes (21): COLOURS, Command bar, CONSTRAINTS, CONTEXT, KEYBOARD SHORTCUTS, OPEN ITEMS, Our Car status, PANEL SPECIFICATIONS (+13 more)

### Community 116 - "test_step_kernel.py"
Cohesion: 0.22
Nodes (9): _one_car(), _profile(), test_advance_equals_stepping_one_by_one(), test_full_braking_matches_python(), test_full_throttle_acceleration_matches_python(), test_invariants_hold_for_random_controls(), test_race_order_matches_lexsort(), test_single_car_matches_the_lap_simulation() (+1 more)

### Community 117 - "engineer"
Cohesion: 0.40
Nodes (5): engineer, call_max_laps, defend_clear_gap_s, let_teammate_by_gap_s, push_lap_max_laps

### Community 118 - "openf1"
Cohesion: 0.40
Nodes (5): openf1, base_url, max_requests_per_min, max_requests_per_s, timeout_s

### Community 119 - "Calibration notes"
Cohesion: 0.17
Nodes (11): Bound hits, Calibration notes, Owner round 15 (2026-10-25): fit 2 written as provisional, new acceptance, Placeholders and STRUCTURAL defaults accepted in owner round 13, Pole team, suzuka (2026_pre_miami), PROVISIONAL, suzuka T-02A final fit (2026-10-24): FAIL, provisional values kept, T-02A last fit (owner round 14, 2026-10-25): FAIL, provisional values kept (+3 more)

### Community 121 - "CLAUDE.md — Agent Entry Point for `pitwall_sim`"
Cohesion: 0.20
Nodes (9): CLAUDE.md — Agent Entry Point for `pitwall_sim`, CODE CONVENTIONS, CURRENT STATE, DOCUMENT MAP, KEY COMMANDS, PROJECT IN ONE PARAGRAPH, PURPOSE, UNRESOLVED ITEMS AGENTS MUST NOT DECIDE (+1 more)

### Community 122 - "HARD"
Cohesion: 0.18
Nodes (11): HARD, a_wear, b_wear, c_rr, cliff_w, cool_rate, heat_gain, k_wear (+3 more)

### Community 123 - "INTERMEDIATE"
Cohesion: 0.18
Nodes (11): INTERMEDIATE, a_wear, b_wear, c_rr, cliff_w, cool_rate, heat_gain, k_wear (+3 more)

### Community 124 - "MEDIUM"
Cohesion: 0.18
Nodes (11): MEDIUM, a_wear, b_wear, c_rr, cliff_w, cool_rate, heat_gain, k_wear (+3 more)

### Community 125 - "SOFT"
Cohesion: 0.18
Nodes (11): SOFT, a_wear, b_wear, c_rr, cliff_w, cool_rate, heat_gain, k_wear (+3 more)

### Community 126 - "WET"
Cohesion: 0.18
Nodes (11): WET, a_wear, b_wear, c_rr, cliff_w, cool_rate, heat_gain, k_wear (+3 more)

### Community 127 - "debrief"
Cohesion: 0.50
Nodes (4): debrief, k_alternatives, n_seeds, score_scale_s

### Community 132 - "feed"
Cohesion: 0.25
Nodes (8): feed, drop_p, gear_upshift_kmh, position_noise_m, rate_hz, speed_noise_kmh, throttle_noise_pct, window_s

### Community 133 - "paths"
Cohesion: 0.25
Nodes (8): paths, calibration, fastf1_cache, multiviewer_cache, openf1_cache, real_races, runs, tracks

### Community 134 - "pit"
Cohesion: 0.25
Nodes (8): pit, box_fraction, entry_decel_ms2, slow_stop_extra_s, slow_stop_p, stop_mean_s, stop_min_s, stop_sd_s

### Community 137 - "race_engine"
Cohesion: 0.29
Nodes (7): race_engine, grid_slot_spacing_m, max_race_factor, pole_offset_m, start_battery_fraction, start_compound, timing_loop_spacing_m

### Community 140 - "outline"
Cohesion: 0.33
Nodes (6): outline, corners, file, licence, provider, revision

### Community 141 - "pit"
Cohesion: 0.33
Nodes (6): pit, entry_s_m, exit_s_m, lane_loss_s, lane_speed_kmh, limit_length_m

### Community 142 - "zones"
Cohesion: 0.33
Nodes (6): zones, s_end_m, s_start_m, tags, type, zone_id

### Community 143 - "compounds"
Cohesion: 0.33
Nodes (5): compounds, load_sensitivity, k_load, n_ref_n, wear_norm_j

### Community 144 - "load_factor"
Cohesion: 0.28
Nodes (5): corner_speed_ms(), load_factor(), test_corner_speed_balances_load_sensitive_grip(), test_load_sensitivity_removes_the_aero_singularity(), test_corner_speed_formula()

### Community 145 - "decide"
Cohesion: 0.33
Nodes (3): decide(), Decision, Situation

### Community 146 - "geometry_source"
Cohesion: 0.40
Nodes (5): geometry_source, driver, session, source, year

### Community 149 - "corners"
Cohesion: 0.50
Nodes (4): corners, corner_id, name, s_m

### Community 150 - "SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)"
Cohesion: 0.50
Nodes (3): Part 1 — OWNER DECISION — DEADLINE SPRINT (overrides TASKS.md order), Part 2 — SPRINT CHANGE — ALERTS + "CALL THE DRIVER" (replaces the previous Simply Clipping addendum), SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)

### Community 153 - "events"
Cohesion: 0.67
Nodes (3): events, incident_rate_per_lap, sc_share

### Community 154 - "weather"
Cohesion: 0.67
Nodes (3): weather, rain_p_per_race, transition_matrix

## Knowledge Gaps
- **4 isolated node(s):** `pitwall_sim`, `OPEN owner decision: structural DEFEND (hold until threat passes) / ATTACK (close the gap)`, `Known issue: timing tests (headless runtime, step kernel budget, UI 16x frame) fail under machine load`, `Parked until after the sprint: S-1, S-3, S-4, T-02B/C/D, T-038, T-062, R3-R5`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1938 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **63 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RaceEngine` connect `RaceEngine` to `engine.py`, `calibration/compare.py`, `load_app`, `state.py`, `ReplayWindow`, `call_outcome.py`, `test_snapshot.py`, `test_pit.py`, `rival_strategy.py`, `LiveSession`, `session.py`, `PublicFeedFrame`, `WeatherModel`, `RaceSetup`, `TRD.md — Pit Wall Race Simulator (2026 Regulations)`, `commands.py`, `._events`, `test_commands_effect.py`, `test_mistakes.py`, `dataclasses`, `.timing_state`, `integration/test_rival_strategy.py`, `test_radar.py`, `test_info_barrier.py`, `zone_mask`, `pathlib`, `RadarBank`, `RadarEstimate`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 76 inferred relationships involving `RaceEngine` (e.g. with `THREADING MODEL` and `_ahead()`) actually correct?**
  _`RaceEngine` has 76 INFERRED edges - model-reasoned connections that need verification._
- **What connects `pitwall_sim`, `OPEN owner decision: structural DEFEND (hold until threat passes) / ATTACK (close the gap)`, `Known issue: timing tests (headless runtime, step kernel budget, UI 16x frame) fail under machine load` to the rest of the system?**
  _4 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `RaceEngine` be split into smaller, more focused modules?**
  _Cohesion score 0.044372612400822804 - nodes in this community are weakly interconnected._
- **Why does `Compound` connect `load_app` to `RaceEngine`, `engine.py`, `calibration/compare.py`, `test_config_load.py`, `fit.py`, `state.py`, `ReplayWindow`, `test_snapshot.py`, `test_aero_fuel_tyres.py`, `test_pit.py`, `rival_strategy.py`, `loader.py`, `speed_profile.py`, `test_speed_profile.py`, `test_alerts.py`, `pytest`, `test_ai_driver.py`, `WeatherModel`, `RaceSetup`, `step_kernel.py`, `DriverInstructions`, `commands.py`, `corner_sources.py`, `accel_zones.py`, `test_commands_effect.py`, `integration/test_rival_strategy.py`, `models.py`, `test_step_kernel.py`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 74 inferred relationships involving `TrackConfig` (e.g. with `load_reference_lap()` and `load_team_references()`) actually correct?**
  _`TrackConfig` has 74 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_deploy_policy.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10808080808080808 - nodes in this community are weakly interconnected._