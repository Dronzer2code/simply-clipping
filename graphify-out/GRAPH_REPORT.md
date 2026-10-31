# Graph Report - simply-clipping  (2026-10-31)

## Corpus Check
- 234 files · ~248,086 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 2, .geojson 1, .parquet 1)

## Summary
- 5334 nodes · 13291 edges · 265 communities (191 shown, 74 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 1530 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4bc6de7e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- scenarios.py
- test_deploy_policy.py
- test_overtake.py
- simply_clipping/energy.py
- load_app
- config/loader.py
- fit.py
- load_rule_set
- engine.py
- ReplayWindow
- EngineerView
- ai_driver.py
- snapshot.py
- builder.py
- test_radio_llm.py
- pytest
- Compound
- test_pit.py
- const
- rival_strategy.py
- LiveSession
- costs.py
- time
- CarTracker
- test_track_builder.py
- speed_profile.py
- unit/test_alerts.py
- app.yaml
- test_step_kernel.py
- 2026_post_miami.yaml
- 2026_pre_miami.yaml
- baseline.py
- test_ai_driver.py
- WeatherModel
- real_data.py
- pathlib
- test_race_engine.py
- TeamPerformance
- math
- test_openf1.py
- pandas
- _Estimate
- PushToTalk
- step_kernel.py
- DriverInstructions
- PitWallWindow
- llm_commands.py
- test_info_barrier.py
- speed_profile.py
- pitwall_lite.py
- commands.py
- test_public_feed.py
- accel_zones.py
- RaceEngine
- test_mistakes.py
- reveal.py
- radar
- PROCESS_FLOW.md — Pit Wall Race Simulator (2026 Regulations)
- llm_replies.py
- voice.py
- RadarEstimate
- test_radar.py
- deploy_allocation.py
- make_command
- SESSION_CONTEXT — handoff for a new agent session
- TrackModel
- alerts
- EngineerView
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
- models.py
- test_calls.py
- radar/energy.py
- StrictModel
- KernelState
- test_headless_runtime.py
- ai_driver
- alerts
- R1 — MVP PROMPTS
- mistakes
- drivers
- drivers
- suzuka.yaml
- test_accel_zones.py
- We Are Racing, Not Testing
- overtake
- weather
- track_builder
- SetupScreen
- PRD.md — Pit Wall Race Simulator (2026 Regulations)
- test_live.py
- UI_DESIGN.md — Pit Wall Race Simulator (2026 Regulations)
- Path
- numpy
- Pit Wall: Hackathon Scope
- openf1
- LapBuffer
- TEST SET (seeds 6-10)
- CLAUDE.md — Agent Entry Point for `pitwall_sim`
- HARD
- INTERMEDIATE
- MEDIUM
- SOFT
- WET
- TRD.md — Pit Wall Race Simulator (2026 Regulations)
- dirty_air.py
- EngineerCommand
- ReferenceRadarEstimator
- feed
- paths
- pit
- cda_fit
- main
- race_engine
- test_safety_car.py
- outline
- pit
- zones
- compounds
- convert
- decide
- geometry_source
- We Are Racing, Not Testing
- resample
- corners
- RadioAI
- config.yaml
- events
- weather
- MVP.md — Pit Wall Race Simulator (2026 Regulations)
- teams
- zone_difficulty
- .__init__
- DriverRadio
- SETUP.md — Pit Wall Race Simulator (2026 Regulations)
- DriverVoice
- car
- docs/ — index: which document holds what
- Calibration notes
- PROJECT_STATUS.md — what is built, what is on its way, what needs changes
- FloatArray
- race_events
- test_overtake_contact.py
- deploy
- test_outline.py
- test_radio_voice.py
- export
- Provider
- DEMO_SC.md — 3-minute Simply Clipping demo (screen recording)
- SC_TUNING.md — Simply Clipping tuning log
- test_scorer.py
- real_race
- test_radio_llm_session.py
- real_race.py
- to_result
- _FakeRecorder
- test_lap_sim.py
- pitwall_sim
- streams
- DEMO.md — 3-minute demo script (screen recording)
- RadarBank
- TASKS.md — Pit Wall Race Simulator (2026 Regulations)
- SoundDeviceRecorder
- anchor
- confidence
- energy
- states
- DEMO_HACKATHON.md — 4-minute hackathon demo (docs/HACKATHON_SCOPE.md section 8)
- SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)
- SIMPLY_CLIPPING_BRIDGE.md — Test bench for your Simply Clipping
- math
- _Recorder
- TrackValidationError
- integration/test_rival_strategy.py
- radio_llm
- ui
- voice_input
- .for_track
- signal
- sim
- PitConfig
- _FakeWorker
- HACKATHON_SCOPE.md
- lap_distance
- engineer
- valid_car_samples
- RaceEventsConfig
- provider
- RadarState
- CarRules
- Corner
- DebriefConfig
- DirtyAirConfig
- DriverEntry
- EnergyRules
- GeometrySource
- LoadSensitivity
- MultiViewerConfig
- OutlineSource
- PhysicsConfig
- RaceEngineConfig
- RadioConfig
- TeamEntry
- TrackWeatherConfig
- UiConfig
- SlipstreamConfig
- VoiceInputConfig
- StrategyPanelConfig
- RealRaceConfig

## God Nodes (most connected - your core abstractions)
1. `RaceEngine` - 237 edges
2. `Compound` - 136 edges
3. `load_app()` - 119 edges
4. `load_track()` - 107 edges
5. `LiveSession` - 103 edges
6. `TrackConfig` - 102 edges
7. `EngineerView` - 82 edges
8. `RaceSetup` - 77 edges
9. `ConfigError` - 72 edges
10. `CommandType` - 65 edges

## Surprising Connections (you probably didn't know these)
- `CURRENT STATE` --references--> `bench()`  [INFERRED]
  CLAUDE.md → pitwall_sim/bench/__init__.py
- `T-02A round 13 diagnosis (2026-10-24), before the last fit` --references--> `load_team_references()`  [INFERRED]
  docs/results/CALIBRATION_NOTES.md → pitwall_sim/calibration/compare.py
- `DOCUMENT MAP` --references--> `fit()`  [INFERRED]
  CLAUDE.md → pitwall_sim/calibration/fit.py
- `Powertrain (`car/powertrain.py`)` --references--> `PowertrainParams`  [INFERRED]
  docs/spec/TRD.md → pitwall_sim/car/powertrain.py
- `RULE SET VALUES` --references--> `boost_cap_w()`  [INFERRED]
  docs/spec/TRD.md → pitwall_sim/car/powertrain.py

## Import Cycles
- None detected.

## Communities (265 total, 74 thin omitted)

### Community 0 - "scenarios.py"
Cohesion: 0.07
Nodes (11): apply(), _hold(), on_tick(), plan(), ScenarioSetup, apply(), _battery(), grid_order() (+3 more)

### Community 1 - "test_deploy_policy.py"
Cohesion: 0.08
Nodes (44): acceleration_zone_index(), BoolArray, DeployPlan, feasible_budgets(), FloatArray, _fund(), _harvest_per_point(), _in_zone() (+36 more)

### Community 2 - "test_overtake.py"
Cohesion: 0.08
Nodes (15): OvertakeConfig, crossed(), OvertakeModel, p_pass(), trigger_points(), TriggerPoint, make_rngs(), app() (+7 more)

### Community 3 - "simply_clipping/energy.py"
Cohesion: 0.04
Nodes (30): 1. EXPORT (`python -m pitwall_sim.export`), CONFIG (`simply_clipping/config.yaml`), CarInput, aero_modes(), CdaFit, _dot(), electric_power_kw(), fit_cda() (+22 more)

### Community 4 - "load_app"
Cohesion: 0.05
Nodes (54): BoolArray, DeployMode, FloatArray, lap_of(), load_reference_lap(), load_team_references(), main(), positions() (+46 more)

### Community 5 - "config/loader.py"
Cohesion: 0.03
Nodes (50): Block 0: Foundation, quali_fuel_kg(), choose_sources(), CornerSource, implied_radius_m(), main(), write_corners(), reference_params() (+42 more)

### Community 6 - "fit.py"
Cohesion: 0.04
Nodes (71): NEEDS CHANGES (FOUND BY RUNNING), compare_teams(), log_results(), order_ok(), ReferenceLap, speed_rmse_kmh(), TeamResult, TrackArrays (+63 more)

### Community 7 - "load_rule_set"
Cohesion: 0.07
Nodes (32): TESTING, boost_cap_w(), ice_power_w(), linear_taper(), mgu_k_allowed_w(), mgu_k_deploy_w(), overtake_available(), overtake_extra_energy_j() (+24 more)

### Community 8 - "engine.py"
Cohesion: 0.07
Nodes (22): PredictorOutput, BoolArray, AeroMode, CarArrays, CarState, CarStatus, _check_mirror_covers_car_state(), EnergyModeName (+14 more)

### Community 10 - "EngineerView"
Cohesion: 0.05
Nodes (27): Block 5: Observation, S — Deadline sprint: alerts and calling the driver (owner, 2026-10-26 to 2026-10-31), PF-06 INFORMATION FLOW AND BARRIER, THREADING MODEL, PowerRules, _ahead(), first_alert(), main() (+19 more)

### Community 11 - "ai_driver.py"
Cohesion: 0.08
Nodes (21): AI DRIVER (`driver/ai_driver.py`), Per-step order (`race/engine.py`), AiDriverConfig, BoolArray, CarPlan, decide_all(), deploy_fractions(), EnergyBalance (+13 more)

### Community 12 - "snapshot.py"
Cohesion: 0.08
Nodes (20): Block 4: Determinism and rivals, WHERE TO FIND IT (TOPIC LOOKUP), ARCHITECTURE PRINCIPLES, SNAPSHOT AND DETERMINISM (`race/snapshot.py`) — F09, fork(), restore(), rng_states(), save() (+12 more)

### Community 13 - "builder.py"
Cohesion: 0.10
Nodes (15): build_from_laps(), _Curve, _drop_repeated_points(), FloatArray, IntArray, load_laps_xy_fastf1(), main(), _penalized_curve() (+7 more)

### Community 14 - "test_radio_llm.py"
Cohesion: 0.09
Nodes (15): RadioLlmConfig, AnthropicMessagesProvider, _arguments(), HttpTransport, LLMError, make_provider(), OpenAIChatProvider, Transport (+7 more)

### Community 15 - "pytest"
Cohesion: 0.07
Nodes (38): Block 1: Track, Block 2: Single-car physics, Block 6: Commands, Block 7: UI, Block 8: MVP acceptance, R1 — MVP, Battery (`car/battery.py`), available_deploy_w() (+30 more)

### Community 16 - "Compound"
Cohesion: 0.07
Nodes (29): f_temp(), f_wear(), mu_tyre(), step_wear(), tyre_params(), tyre_temp_c(), TyreParams, wear_rate_per_s() (+21 more)

### Community 17 - "test_pit.py"
Cohesion: 0.07
Nodes (24): PIT LANE (`race/pit.py`), RaceSetup, FloatArray, PitEvent, PitLane, PitPhase, rain(), _rain_race() (+16 more)

### Community 18 - "const"
Cohesion: 0.04
Nodes (38): AlertRow, Engine, row(), offline_alerts(), our_state(), OwnTrack, radio_line(), ticks() (+30 more)

### Community 19 - "rival_strategy.py"
Cohesion: 0.08
Nodes (19): RIVAL STRATEGY AI (`race/rival_strategy.py`), battle_inputs(), BoolArray, _box(), crosses_over(), decide(), decide_book(), _decide_rows() (+11 more)

### Community 20 - "LiveSession"
Cohesion: 0.06
Nodes (26): CommandType, RadioSource, CallSpec, _Ack, LiveSession, job(), job(), LiveSetup (+18 more)

### Community 21 - "costs.py"
Cohesion: 0.09
Nodes (14): CallOption, CallRunner, CallStep, _coming_straight(), _ignore(), _Pending, CallRecord, alternatives() (+6 more)

### Community 22 - "time"
Cohesion: 0.13
Nodes (7): main(), record(), Replay, app(), replay(), test_recording_round_trips(), test_22_car_step_is_within_budget()

### Community 23 - "CarTracker"
Cohesion: 0.06
Nodes (25): calibrated(), CarTracker, classify_states(), confidence_table(), Estimates, flows_kw(), _integrate(), steady_full() (+17 more)

### Community 24 - "test_track_builder.py"
Cohesion: 0.11
Nodes (19): TrackBuilderConfig, build_centre_line(), stadium(), test_alignment_recovers_a_moved_mirrored_outline(), _distance_to_true_stadium(), _stadium_xy(), test_both_fits_recover_the_stadium(), test_circle_has_no_straights() (+11 more)

### Community 25 - "speed_profile.py"
Cohesion: 0.06
Nodes (38): run(), AeroParams, cda(), cla(), air_density(), car_mass_kg(), downforce_n(), drag_n() (+30 more)

### Community 26 - "unit/test_alerts.py"
Cohesion: 0.13
Nodes (21): AlertsConfig, PublicWeather, _car(), _clip_case(), _own_battery(), _pass(), _repass(), test_alert_clears_expires_and_is_suppressed_for_a_lap() (+13 more)

### Community 27 - "app.yaml"
Cohesion: 0.06
Nodes (34): acceleration_zones, min_length_m, min_speed_change_kmh, reference_rule_set, aero, straight_mode_throttle_min, debrief, k_alternatives (+26 more)

### Community 28 - "test_step_kernel.py"
Cohesion: 0.21
Nodes (10): brake_decel_ms2(), _one_car(), _profile(), test_advance_equals_stepping_one_by_one(), test_full_braking_matches_python(), test_full_throttle_acceleration_matches_python(), test_invariants_hold_for_random_controls(), test_race_order_matches_lexsort() (+2 more)

### Community 29 - "2026_post_miami.yaml"
Cohesion: 0.06
Nodes (30): car, min_mass_kg, effective_from, energy, deploy_max_mj_per_lap, e_usable_max_mj, energy_counter_reset, harvest_max_mj_per_lap_quali (+22 more)

### Community 30 - "2026_pre_miami.yaml"
Cohesion: 0.06
Nodes (30): car, min_mass_kg, effective_from, energy, deploy_max_mj_per_lap, e_usable_max_mj, energy_counter_reset, harvest_max_mj_per_lap_quali (+22 more)

### Community 31 - "baseline.py"
Cohesion: 0.14
Nodes (4): PublicFeedFrame, FloatArray, PublicFeed, _Tick

### Community 32 - "test_ai_driver.py"
Cohesion: 0.18
Nodes (10): _lap(), _plan(), _shape(), test_attack_uses_all_the_grip_and_defend_keeps_deploy_for_the_straights(), test_energy_balance_corrects_a_steady_loss(), test_energy_modes_meet_their_battery_targets(), test_energy_modes_order_lap_times_and_harvest_gains_battery(), test_grip_margin_orders_reference_lap_times() (+2 more)

### Community 34 - "real_data.py"
Cohesion: 0.05
Nodes (31): ALERT RULES, FLOWS (P7, per steady 10 Hz point), LESSONS FROM THE SIMULATOR (designed in from the start), OPEN ITEMS (owner decides), PACKAGE LAYOUT, PIPELINE (offline `run`), PURPOSE, RADIO LINE (SC-6) (+23 more)

### Community 35 - "pathlib"
Cohesion: 0.03
Nodes (37): run(), bench(), BenchSetup, cda_table(), layout_file(), plugin_run(), scenarios_arg(), seeds_arg() (+29 more)

### Community 36 - "test_race_engine.py"
Cohesion: 0.17
Nodes (14): full_race(), _short(), test_a_car_out_of_fuel_retires(), test_classification_and_gaps_at_the_flag(), test_commands_apply_at_their_effective_time(), test_gaps_mid_race_are_consistent(), test_lap_times_add_up_to_the_finish_time(), test_no_ice_power_without_fuel() (+6 more)

### Community 37 - "TeamPerformance"
Cohesion: 0.10
Nodes (18): aero_mode(), aero_params(), _value(), burn(), fuel_flow_w(), fuel_params(), FuelParams, max_ice_power_w() (+10 more)

### Community 38 - "math"
Cohesion: 0.14
Nodes (10): align_to_model(), apply_outline(), blend_corners(), blend_weight(), corner_windows(), densify(), FloatArray, outline_curvature() (+2 more)

### Community 39 - "test_openf1.py"
Cohesion: 0.06
Nodes (34): OpenF1Config, TrackConfig, Fetch, RateLimiter, track(), cfg(), _client(), _FakeApi (+26 more)

### Community 40 - "pandas"
Cohesion: 0.05
Nodes (34): evaluate(), _events_for(), _honesty(), _right(), Run, score_alerts(), score_cda(), score_energy() (+26 more)

### Community 42 - "PushToTalk"
Cohesion: 0.09
Nodes (6): PushToTalk, Recorder, Samples, Transcriber, test_fake_transcriber_feeds_the_radio_pipeline(), test_push_to_talk_transcribes_on_a_worker()

### Community 43 - "step_kernel.py"
Cohesion: 0.10
Nodes (20): Step kernel (`race/step_kernel.py`, `T-030`), advance(), _car_forces(), _corner_speed(), _f_wear(), _float(), _index(), jit() (+12 more)

### Community 44 - "DriverInstructions"
Cohesion: 0.23
Nodes (12): RivalStrategyConfig, DriverInstructions, cfg(), _plan(), test_battle_flags_use_the_radar_estimate(), test_battle_inputs_read_only_positions_gaps_and_radar(), test_compiled_decisions_match_the_scalar_rules(), test_harvest_hysteresis_reads_the_battery_at_the_line() (+4 more)

### Community 45 - "PitWallWindow"
Cohesion: 0.05
Nodes (6): key(), Frame, AlertCard, _label(), _panel(), PitWallWindow

### Community 46 - "llm_commands.py"
Cohesion: 0.11
Nodes (15): _box_lap(), _clauses(), _corner(), corner_names(), _has(), _norm(), parse(), ParsedCommand (+7 more)

### Community 47 - "test_info_barrier.py"
Cohesion: 0.05
Nodes (20): _follow(), PitPlan, RadioEvent, StrategyResult, evaluate(), _low_priority(), plans_for(), public_snapshot() (+12 more)

### Community 48 - "speed_profile.py"
Cohesion: 0.17
Nodes (18): _accel_jit(), _backward_jit(), backward_pass(), _bool(), BoolArray, corner_limits(), _corner_limits_jit(), _decel_jit() (+10 more)

### Community 49 - "pitwall_lite.py"
Cohesion: 0.10
Nodes (6): LapTelemetry, TelemetryPlot, _drive(), test_lap_change_makes_the_ghost(), test_repeated_frames_and_full_buffers_are_ignored(), test_widget_draws_current_and_ghost()

### Community 50 - "commands.py"
Cohesion: 0.29
Nodes (17): EngineerConfig, _bool(), _box(), _cancel_box(), _choice(), CommandContext, _defend(), _energy() (+9 more)

### Community 51 - "test_public_feed.py"
Cohesion: 0.08
Nodes (10): PUBLIC FEED (`observe/public_feed.py`) — F10, FloatArray, start_positions(), _published(), test_frame_rate_and_drop_rate_match_config(), test_frames_follow_the_contract_with_every_car(), test_gear_rises_with_speed(), test_noise_sigmas_match_config() (+2 more)

### Community 52 - "accel_zones.py"
Cohesion: 0.10
Nodes (14): derive_zones(), DerivedZone, FloatArray, main(), reference_speed_kmh(), turning_points(), _in_zone(), zone_ids_mask() (+6 more)

### Community 53 - "RaceEngine"
Cohesion: 0.04
Nodes (32): EnergyMode, RaceEngine, engine(), _engine(), _fork(), _issue(), _put_behind(), _run_laps() (+24 more)

### Community 54 - "test_mistakes.py"
Cohesion: 0.13
Nodes (10): MistakesConfig, draw_mistake(), mistake_probability(), cfg(), _engine(), test_mistakes_are_deterministic_and_change_the_race(), test_mistakes_in_a_race_use_only_their_stream(), test_outcomes_follow_the_shares() (+2 more)

### Community 55 - "reveal.py"
Cohesion: 0.09
Nodes (5): CallContext, _place(), RevealData, RevealRecorder, RivalSeries

### Community 56 - "radar"
Cohesion: 0.09
Nodes (23): radar, anchor_min_s, c_rr, confidence_half_life_s, e_max_mj, eta, fit_max_speed_kmh, fit_min_samples (+15 more)

### Community 57 - "PROCESS_FLOW.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.05
Nodes (29): Built flows this document does not describe yet (sprint, 2026-10-26 to 2026-10-31), CONTEXT, FLOW INDEX, IMPLEMENTATION STATUS, OPEN ITEMS, PF-01 OFFLINE: TRACK BUILD, PF-02 OFFLINE: CALIBRATION, PF-03 APP START AND RACE SETUP (+21 more)

### Community 58 - "llm_replies.py"
Cohesion: 0.12
Nodes (12): call_with_timeout(), LLMProvider, interpret(), _clean(), fact_check(), _numbers(), reply_facts(), _value() (+4 more)

### Community 59 - "voice.py"
Cohesion: 0.24
Nodes (4): _read(), _synthesise(), team_radio_filter(), _write()

### Community 60 - "RadarEstimate"
Cohesion: 0.22
Nodes (3): RIVAL BATTERY RADAR (`observe/radar/`) — F11, estimate_batch(), RadarEstimate

### Community 61 - "test_radar.py"
Cohesion: 0.11
Nodes (10): builtin_radar(), RadarEstimator, radar_race(), test_compiled_radar_matches_the_python_reference(), test_engine_radar_equals_a_standalone_estimator(), test_incremental_equals_batch(), test_radar_on_sim(), test_radar_uses_its_own_constants() (+2 more)

### Community 62 - "deploy_allocation.py"
Cohesion: 0.16
Nodes (10): allocate(), BoolArray, deploy_demand_j(), DeployAllocation, FloatArray, full_throttle_runs(), IntArray, profile_full_throttle() (+2 more)

### Community 63 - "make_command"
Cohesion: 0.15
Nodes (12): _issuer(), issue(), make_command(), validate(), Validation, issue(), cfg(), test_every_type_has_a_rejection_test() (+4 more)

### Community 64 - "SESSION_CONTEXT — handoff for a new agent session"
Cohesion: 0.14
Nodes (13): COMMANDS, DAY 5 DETAILS, DAY 6 (2026-10-27) — owner plan in docs/planning/SPRINT.md Parts 3-5, DAY 7 (2026-10-27), DAY 8 (2026-10-27) — CHANGE OF PLAN (owner), DAY 9 (2026-10-27) — demo package, HACKATHON (2026-10-30/31, branch `hack/demo`, docs/HACKATHON_SCOPE.md), OWNER WORKING RULES (from the chats, on top of `CLAUDE.md`) (+5 more)

### Community 65 - "TrackModel"
Cohesion: 0.05
Nodes (36): reference_from_lap(), _timestamp(), main(), pit_stop_stats(), PitStopStats, project_path_to_s(), TrackModel, _get_json() (+28 more)

### Community 66 - "alerts"
Cohesion: 0.07
Nodes (29): alerts, attack_gap_s, attack_margin_mj, closing_counts_no_deploy, closing_dv_kmh, closing_episode_gap_s, closing_fast_states, closing_min_speed_kmh (+21 more)

### Community 67 - "EngineerView"
Cohesion: 0.13
Nodes (6): SimplyClippingLite, test_attack_evidence_names_the_energy_branch_and_the_prior(), test_attack_stays_silent_otherwise(), test_closing_speed_stays_silent_otherwise(), test_defend_stays_silent_otherwise(), test_no_alert_below_min_confidence()

### Community 68 - "calibration"
Cohesion: 0.11
Nodes (19): cda_corner, cda_straight, cla_corner, k_load, long_grip_ratio, mu_base_soft, pu_power_scale, calibration (+11 more)

### Community 69 - "reference.py"
Cohesion: 0.15
Nodes (6): electric_power_w(), FloatArray, resample(), savgol_coefficients(), wheel_power_w(), _ModeFit

### Community 70 - "rival_strategy"
Cohesion: 0.11
Nodes (19): rival_strategy, attack_margin_mj, battle_gap_s, critical_wear, defend_margin_mj, low_battery_mj, no_stop_last_laps, push_final_laps (+11 more)

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

### Community 93 - "models.py"
Cohesion: 0.11
Nodes (11): _contact_shares(), DemoConfig, Fraction, FuelRules, HexColor, MaybeDate, MaybeFloat, MaybeInt (+3 more)

### Community 94 - "test_calls.py"
Cohesion: 0.24
Nodes (8): AlertEvidence, _alert(), _run(), test_each_option_sends_exactly_its_commands(), test_follow_ups_come_at_the_next_lap(), test_option_sets_match_the_spec(), test_rejections_are_reported(), test_repass_hold_ends_when_the_battery_is_back()

### Community 95 - "radar/energy.py"
Cohesion: 0.15
Nodes (8): _cda(), _decode_feed(), _energies(), FloatArray, _in_zones(), IntArray, _process(), _push()

### Community 96 - "StrictModel"
Cohesion: 0.10
Nodes (10): CalibrationConfig, CompoundCoefficients, FeedConfig, OvertakeRules, PathsConfig, PredictorConfig, RaceRules, SimConfig (+2 more)

### Community 97 - "KernelState"
Cohesion: 0.15
Nodes (6): _close_hits(), FloatArray, default_controls(), grip_mu(), KernelControls, KernelState

### Community 98 - "test_headless_runtime.py"
Cohesion: 0.24
Nodes (4): Block 3: Race, KNOWN ISSUES, _run(), test_headless_runtime()

### Community 99 - "ai_driver"
Cohesion: 0.12
Nodes (16): ai_driver, balanced_headroom_mj, boost_gap_s, boost_reserve_mj, energy_feedback_gain, grip_margin, harvest_target_mj_per_lap, hold_gap_s (+8 more)

### Community 100 - "alerts"
Cohesion: 0.11
Nodes (19): alerts, attack_gap_s, battery_reserve_mj, clip_min_s, closing_dv_kmh, closing_min_straight_left_m, closing_range_m, defend_gap_s (+11 more)

### Community 101 - "R1 — MVP PROMPTS"
Cohesion: 0.08
Nodes (25): BUILD_PROMPTS.md — Pit Wall Race Simulator (2026 Regulations), OPERATOR RULES, P-00 SESSION START (prepend to every prompt), P-01 Foundation (T-001 → T-005), P-02 Track (T-010 → T-011), P-03 Single-car physics (T-020 → T-025), P-04 Calibration (T-026), P-05 Race (T-030 → T-036) (+17 more)

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

### Community 107 - "We Are Racing, Not Testing"
Cohesion: 0.22
Nodes (8): Command-line checks, Quick start (Windows), Results (built-in baseline), Run the app, Simply Clipping, Tests, We Are Racing, Not Testing, Where things are

### Community 108 - "overtake"
Cohesion: 0.14
Nodes (14): overtake, braking_trigger_min_drop_kmh, braking_zone_difficulty, fail_time_loss_s, follow_gap_m, trigger_gap_m, w_attack, w_defend (+6 more)

### Community 109 - "weather"
Cohesion: 0.12
Nodes (16): DAMP, DRY, HEAVY_WET, WET, weather, car_drying_per_min, drying_per_min, evolution_wash_per_min (+8 more)

### Community 110 - "track_builder"
Cohesion: 0.14
Nodes (14): track_builder, centre_line_fit, length_tolerance, max_closure_gap_m, normalize_length, outline_blend_m, outline_window_max_m, pool_bin_m (+6 more)

### Community 111 - "SetupScreen"
Cohesion: 0.14
Nodes (3): main(), SetupScreen, test_setup_screen_real_race_moment()

### Community 112 - "PRD.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.08
Nodes (24): CONSTRAINTS, CONTEXT, DECISIONS LOG, Engineer controls (`F12`), Extras (`F14`, `F16`, `F17`, `F18`), FEATURES, FUNCTIONAL REQUIREMENTS, GLOSSARY (CANONICAL TERMS) (+16 more)

### Community 113 - "test_live.py"
Cohesion: 0.14
Nodes (15): RevealTab, _sent(), test_16x_is_16x(), test_call_summary_opens_at_the_flag(), test_f1_answers_the_newest_alert(), test_option_button_sends_the_option_commands(), test_radio_box_sends_a_message(), test_reveal_engineer_score_fills_after_the_costs() (+7 more)

### Community 114 - "UI_DESIGN.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.09
Nodes (21): COLOURS, Command bar, CONSTRAINTS, CONTEXT, KEYBOARD SHORTCUTS, OPEN ITEMS, Our Car status, PANEL SPECIFICATIONS (+13 more)

### Community 115 - "Path"
Cohesion: 0.20
Nodes (17): cfg(), _must_not_run(), _no_data(), _openf1_no_data(), _provider(), load(), _run(), stadium_config() (+9 more)

### Community 116 - "numpy"
Cohesion: 0.14
Nodes (10): car_params(), _closing(), events(), ground_truth(), _lap_at(), laps_and_gaps(), _repasses(), _runs() (+2 more)

### Community 117 - "Pit Wall: Hackathon Scope"
Cohesion: 0.10
Nodes (20): 10. Done checklist, 11. Notes for the team, 1. The idea in short, 2. Already built (we demo this as is), 3. Core hackathon features, 4. Left out on purpose, 5. Extras if the core is done, 6. Suggested split (team of 3, each with Claude Code sessions) (+12 more)

### Community 118 - "openf1"
Cohesion: 0.40
Nodes (5): openf1, base_url, max_requests_per_min, max_requests_per_s, timeout_s

### Community 120 - "TEST SET (seeds 6-10)"
Cohesion: 0.10
Nodes (19): a) Norris passes Hamilton, clips, Hamilton re-passes → RE-PASS RISK (Our Car = NOR), b) Lap 22: Bearman closing on Colapinto before Spoon → CLOSING-SPEED RISK (Our Car = BEA), battles (seeds 1, 2, 3, 4, 5; target produced in 5/5), battles (seeds 6, 7, 8, 9, 10; target produced in 5/5), cda_trap (seeds 1, 2, 3, 4, 5; target produced in 5/5), cda_trap (seeds 6, 7, 8, 9, 10; target produced in 5/5), closing_speed (seeds 1, 2, 3, 4, 5; target produced in 5/5), closing_speed (seeds 6, 7, 8, 9, 10; target produced in 5/5) (+11 more)

### Community 121 - "CLAUDE.md — Agent Entry Point for `pitwall_sim`"
Cohesion: 0.18
Nodes (10): CLAUDE.md — Agent Entry Point for `pitwall_sim`, CODE CONVENTIONS, CURRENT STATE, DOCUMENT MAP, HARD RULES, KEY COMMANDS, PROJECT IN ONE PARAGRAPH, PURPOSE (+2 more)

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

### Community 127 - "TRD.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.08
Nodes (24): Alternate Race mode (F18), `config/app.yaml`, `config/grid/<grid>.yaml`, `config/rules/<rule_set>.yaml`, CONFIG SCHEMAS, CONTEXT, DATA CONTRACTS, Data loaded from FastF1 (`real_race.py`) (+16 more)

### Community 128 - "dirty_air.py"
Cohesion: 0.12
Nodes (16): Dirty air and slipstream (`car/dirty_air.py`), BoolArray, dirty_air_params(), DirtyAirParams, downforce_scale(), drag_scale(), FloatArray, gaps_ahead_m() (+8 more)

### Community 130 - "EngineerCommand"
Cohesion: 0.17
Nodes (6): ENGINEER COMMANDS (`engineer/commands.py`) — F12, PURPOSE, CommandQueue, EngineerCommand, test_queue_releases_commands_in_effective_order(), cmd()

### Community 132 - "feed"
Cohesion: 0.25
Nodes (8): feed, drop_p, gear_upshift_kmh, position_noise_m, rate_hz, speed_noise_kmh, throttle_noise_pct, window_s

### Community 133 - "paths"
Cohesion: 0.22
Nodes (9): paths, calibration, cost_cache, fastf1_cache, multiviewer_cache, openf1_cache, real_races, runs (+1 more)

### Community 134 - "pit"
Cohesion: 0.25
Nodes (8): pit, box_fraction, entry_decel_ms2, slow_stop_extra_s, slow_stop_p, stop_mean_s, stop_min_s, stop_sd_s

### Community 135 - "cda_fit"
Cohesion: 0.11
Nodes (18): max, min, cda_fit, aero_modes, cda_bounds_m2, min_dv_kmh, min_points, min_runs (+10 more)

### Community 136 - "main"
Cohesion: 0.15
Nodes (6): format_result(), main(), RaceResult, run_headless(), RunTiming, test_cli_needs_headless_and_reports_bad_config()

### Community 137 - "race_engine"
Cohesion: 0.29
Nodes (7): race_engine, grid_slot_spacing_m, max_race_factor, pole_offset_m, start_battery_fraction, start_compound, timing_loop_spacing_m

### Community 139 - "test_safety_car.py"
Cohesion: 0.29
Nodes (11): _engine(), _pit_loss_m(), _progress(), _run_until(), _spread(), test_crash_on_line_is_sc_off_line_is_vsc(), test_pit_stop_cheaper_under_sc(), test_rivals_split_under_sc() (+3 more)

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

### Community 144 - "convert"
Cohesion: 0.18
Nodes (6): cache_path(), convert(), fetch(), _seconds(), _put(), test_openf1_race_converts_to_the_bridge_input()

### Community 145 - "decide"
Cohesion: 0.29
Nodes (4): PF-04 SIMULATION TICK, decide(), Decision, Situation

### Community 146 - "geometry_source"
Cohesion: 0.40
Nodes (5): geometry_source, driver, session, source, year

### Community 147 - "We Are Racing, Not Testing"
Cohesion: 0.13
Nodes (14): 1. The 30-second version (no F1 knowledge needed), 2. The key idea: "clipping", 3. What we built: two parts, 4. How it feels to play, 5. All features, 6. Does it work?, 7. Why it matters, 8. Mini glossary (+6 more)

### Community 148 - "resample"
Cohesion: 0.14
Nodes (3): resample(), WhisperTranscriber, test_resample_to_16k()

### Community 149 - "corners"
Cohesion: 0.40
Nodes (5): corners, aliases, corner_id, name, s_m

### Community 152 - "config.yaml"
Cohesion: 0.13
Nodes (14): battles, min_speed_kmh, stale_s, within_s, fuel, burn_kg_per_lap, start_kg, output (+6 more)

### Community 153 - "events"
Cohesion: 0.67
Nodes (3): events, incident_rate_per_lap, sc_share

### Community 154 - "weather"
Cohesion: 0.67
Nodes (3): weather, rain_p_per_race, transition_matrix

### Community 155 - "MVP.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.14
Nodes (13): BUILD ORDER INSIDE THE MVP, CONSTRAINTS, CONTEXT, Excluded from MVP (built in later releases), Included, MVP BOUNDARY STATUS, MVP.md — Pit Wall Race Simulator (2026 Regulations), MVP OBJECTIVE (+5 more)

### Community 160 - ".__init__"
Cohesion: 0.06
Nodes (5): RACE EVENTS (`race/events.py`) — R2, ContactEvent, MistakeEvent, _Timing, TrackStatus

### Community 161 - "DriverRadio"
Cohesion: 0.17
Nodes (5): DriverRadio, test_low_battery_only_before_a_long_straight(), test_rain_line_names_the_corner_ahead_and_is_not_rate_limited(), test_triggers_and_rate_limit(), _view()

### Community 162 - "SETUP.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.15
Nodes (12): 1. CLONE AND ENVIRONMENT, 2. DEPENDENCIES (`pyproject.toml`), 3. IMPORT CONTRACTS (`.importlinter`), 4. REAL DATA (FASTF1), 5. GEMMA MODEL (R3 ONLY), 6. COMMANDS, 7. CONFIG FILES, 8. VERIFY THE SETUP (+4 more)

### Community 163 - "DriverVoice"
Cohesion: 0.18
Nodes (6): available(), DriverVoice, _level(), test_band_pass_keeps_the_voice_band(), test_muted_by_default(), _tone()

### Community 164 - "car"
Cohesion: 0.15
Nodes (13): car, crr, eta, g_ms2, mass_kg, p_elec_max_kw, p_ice_from_runs, p_ice_kw (+5 more)

### Community 165 - "docs/ — index: which document holds what"
Cohesion: 0.17
Nodes (11): docs/ — index: which document holds what, DOCUMENT CATALOGUE, FOLDER LAYOUT, GENERATED FILES, guides/ — how to run, planning/ — work to do, READING ORDER, results/ — measured numbers (+3 more)

### Community 166 - "Calibration notes"
Cohesion: 0.17
Nodes (11): Bound hits, Calibration notes, Owner round 15 (2026-10-25): fit 2 written as provisional, new acceptance, Placeholders and STRUCTURAL defaults accepted in owner round 13, Pole team, suzuka (2026_pre_miami), PROVISIONAL, suzuka T-02A final fit (2026-10-24): FAIL, provisional values kept, T-02A last fit (owner round 14, 2026-10-25): FAIL, provisional values kept (+3 more)

### Community 167 - "PROJECT_STATUS.md — what is built, what is on its way, what needs changes"
Cohesion: 0.17
Nodes (11): Deadline sprint (until 2026-10-31), HOW IT WAS RUN, Later releases (all stubs or not started), MVP acceptance today, ON ITS WAY (NOT DONE), PROJECT_STATUS.md — what is built, what is on its way, what needs changes, PURPOSE, R1 core (MVP) (+3 more)

### Community 168 - "FloatArray"
Cohesion: 0.20
Nodes (7): BoolArray, flat_plans(), FloatArray, initial_state(), IntArray, race_order(), reached()

### Community 169 - "race_events"
Cohesion: 0.11
Nodes (18): LIGHT, SC, VSC, race_events, car_length_m, contact_min_p_pass, contact_p, contact_shares (+10 more)

### Community 170 - "test_overtake_contact.py"
Cohesion: 0.24
Nodes (8): OvertakeEvent, _attempt(), _engine(), test_contact_happens_in_a_race_and_is_deterministic(), run(), test_contact_stops_the_attacker_and_raises_sc_or_vsc(), test_light_contact_slows_both_cars_only(), test_no_contact_on_hopeless_attempts_or_blue_flags()

### Community 171 - "deploy"
Cohesion: 0.18
Nodes (11): deploy, corner_cap_kw, corner_min_kmh, corner_seen_kw, corner_tau_s, cruise_scale, level_tau_s, observed_kmh (+3 more)

### Community 172 - "test_outline.py"
Cohesion: 0.15
Nodes (5): cfg(), _limacon(), test_blend_weight_and_corner_blend(), test_corner_windows_stop_half_way_to_the_neighbours(), test_geojson_projects_to_metres()

### Community 173 - "test_radio_voice.py"
Cohesion: 0.23
Nodes (5): _Recorder, test_hold_the_key_to_talk(), test_talk_button_off_without_voice_packages(), _Transcriber, _window()

### Community 174 - "export"
Cohesion: 0.22
Nodes (9): export, drop_p, gap_rate_per_min, gap_s, jitter_s, position_noise_m, speed_noise_kmh, stream_rate_hz (+1 more)

### Community 176 - "DEMO_SC.md — 3-minute Simply Clipping demo (screen recording)"
Cohesion: 0.22
Nodes (8): 1. The problem (15 s), 2. Live pit wall with Simply Clipping (40 s), 3. Answer an ATTACK and a DEFEND (50 s), 4. Call summary (20 s), 5. Results against the built-in (30 s), 6. Real-race check (25 s), Before recording (2 min, off camera), DEMO_SC.md — 3-minute Simply Clipping demo (screen recording)

### Community 177 - "SC_TUNING.md — Simply Clipping tuning log"
Cohesion: 0.22
Nodes (8): SC-1 — CdA fit (2026-10-30), SC-2 — energy estimate (2026-10-30), SC-2 result, SC-3 — battles, alerts, live plug-in (2026-10-30), SC-3 result (test set, run once; built-in → Simply Clipping), SC-4 — threshold tuning, final config (2026-10-30), SC-6 — radio line, demo; post-v1 fix (2026-10-30), SC_TUNING.md — Simply Clipping tuning log

### Community 179 - "test_scorer.py"
Cohesion: 0.10
Nodes (16): engineer_score(), EngineerScore, score_from_loss(), CallCost, RadioSender, describe(), test_describe(), _cost() (+8 more)

### Community 181 - "real_race"
Cohesion: 0.15
Nodes (13): real_race, battery_fraction, default_lap, fuel_margin_kg, fuel_per_lap_kg, min_spacing_m, session_key, wear_per_lap (+5 more)

### Community 187 - "test_radio_llm_session.py"
Cohesion: 0.18
Nodes (14): LLMReply, Tool, ToolCall, _driver(), _FakeProvider, _session(), test_driver_lines_llm_written_when_true_else_template(), test_invalid_llm_command_is_rejected_by_validation() (+6 more)

### Community 190 - "real_race.py"
Cohesion: 0.05
Nodes (28): `config/tracks/<track_id>.yaml`, GridConfig, StartCar, driver_ids(), format_moment(), format_result(), load_data(), main() (+20 more)

### Community 191 - "to_result"
Cohesion: 0.15
Nodes (7): ack_for(), _obj(), to_result(), tools(), test_invalid_llm_output_is_rejected_by_validate(), test_tool_calls_become_validated_commands(), test_tools_cover_every_command_type_with_its_parameters()

### Community 204 - "test_lap_sim.py"
Cohesion: 0.33
Nodes (8): reference_profile(), _run(), test_braking_recharges_the_battery(), test_lap_time_is_the_integral_of_ds_over_v(), test_no_mgu_k_is_slower_and_draws_nothing(), test_real_battery_limits_deployment(), test_unlimited_energy_reproduces_the_speed_profile(), test_unmet_deploy_counts_what_the_battery_could_not_supply()

### Community 212 - "streams"
Cohesion: 0.20
Nodes (4): ExportConfig, merge(), streams(), _times()

### Community 213 - "DEMO.md — 3-minute demo script (screen recording)"
Cohesion: 0.25
Nodes (7): 1. One line (5 s), 2. Race setup (15 s), 3. Answer a DEFEND and an ATTACK with F1 (60 s), 4. The two scenario presets (40 s), 5. Call summary at the flag (20 s), 6. The test bench (30 s), DEMO.md — 3-minute demo script (screen recording)

### Community 215 - "TASKS.md — Pit Wall Race Simulator (2026 Regulations)"
Cohesion: 0.22
Nodes (8): PURPOSE, R2 — Events, weather, predictor, R3 — Radio and debrief, R4 — Compare modes, R5 — Full calendar, RULES, SC — Simply Clipping (owner's project, branch `simply-clipping`, from 2026-10-30), TASKS.md — Pit Wall Race Simulator (2026 Regulations)

### Community 217 - "anchor"
Cohesion: 0.25
Nodes (8): anchor, empty_mj, max_start_frac, min_clip_s, min_straight_m, no_deploy_kw, start_mj, superclip_kw

### Community 218 - "confidence"
Cohesion: 0.25
Nodes (8): confidence, missing_scale_s, missing_tau_s, right_tol_mj, table, energy_edges_mj, hit_rate, since_anchor_edges_s

### Community 219 - "energy"
Cohesion: 0.25
Nodes (8): energy, brake_share, e_max_mj, e_min_mj, harvest_cap_kw, harvest_max_mj_per_lap, lift_harvest_kw, superclip_min_kmh

### Community 220 - "states"
Cohesion: 0.25
Nodes (8): states, clip_max_accel_ms2, clip_max_kw, deploy_min_kw, full_throttle_pct, lift_throttle_pct, partial_deploy_kw, taper_margin_kw

### Community 221 - "DEMO_HACKATHON.md — 4-minute hackathon demo (docs/HACKATHON_SCOPE.md section 8)"
Cohesion: 0.29
Nodes (6): Before going on stage (off camera, 3 min), DEMO_HACKATHON.md — 4-minute hackathon demo (docs/HACKATHON_SCOPE.md section 8), Fallbacks, Flow (4 minutes), Reveal (60 s), Setup (20 s)

### Community 222 - "SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)"
Cohesion: 0.29
Nodes (6): Part 1 — OWNER DECISION — DEADLINE SPRINT (overrides TASKS.md order), Part 2 — SPRINT CHANGE — ALERTS + "CALL THE DRIVER" (replaces the previous Simply Clipping addendum), Part 3 — OWNER ANSWERS — DAY 5 FOLLOW-UP (2026-10-26), Part 4 — DEADLINE PLAN — DAYS 6–9 (owner, 2026-10-27; extends Part 3), Part 5 — SPRINT ADDENDUM — SIMPLY CLIPPING TEST BENCH (verbatim; the spec Part 3 item 3 refers to), SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)

### Community 223 - "SIMPLY_CLIPPING_BRIDGE.md — Test bench for your Simply Clipping"
Cohesion: 0.11
Nodes (15): 0. QUICK START, 2. YOUR PACKAGE: TWO FUNCTIONS, 3. SCORER (`python -m pitwall_sim.evaluate`), 4. BATCH AND BASELINE TABLE, `create(cfg, track) -> provider` (live, the pit wall), `run(feed_dir, out_dir, our, own_file, layout_file) -> None` (offline, the bench), SIMPLY_CLIPPING_BRIDGE.md — Test bench for your Simply Clipping, CONTRACT (+7 more)

### Community 224 - "math"
Cohesion: 0.15
Nodes (12): Active aero (`car/aero.py`), Fuel (`car/fuel.py`), Longitudinal dynamics (`step_kernel.py`), Powertrain (`car/powertrain.py`), SIMULATION CORE, Time stepping, Tyres (`car/tyres.py`), corner_speed_ms() (+4 more)

### Community 226 - "TrackValidationError"
Cohesion: 0.25
Nodes (4): TrackUnavailableError, TrackValidationError, validate_length(), test_length_check_uses_the_raw_length()

### Community 227 - "integration/test_rival_strategy.py"
Cohesion: 0.28
Nodes (3): race(), _Recorder, test_mvp10_rivals_pit_and_change_energy_mode_unaided()

### Community 228 - "radio_llm"
Cohesion: 0.25
Nodes (8): radio_llm, api_key_env, base_url, driver_replies, max_reply_words, model, provider, timeout_s

### Community 229 - "ui"
Cohesion: 0.40
Nodes (5): ui, default_race_laps, fallback_palette, refresh_hz, window_title

### Community 230 - "voice_input"
Cohesion: 0.29
Nodes (7): voice_input, compute_type, enabled, key, max_record_s, model, model_dir

### Community 232 - "signal"
Cohesion: 0.40
Nodes (5): signal, max_gap_s, resample_hz, savgol_order, savgol_window

### Community 233 - "sim"
Cohesion: 0.50
Nodes (4): sim, decision_tick_s, default_seed, dt_s

### Community 239 - "engineer"
Cohesion: 0.40
Nodes (5): engineer, call_max_laps, defend_clear_gap_s, let_teammate_by_gap_s, push_lap_max_laps

### Community 240 - "valid_car_samples"
Cohesion: 0.40
Nodes (3): CALIBRATION (`calibration/compare.py`) — F20, valid_car_samples(), test_invalid_and_frozen_car_samples_are_dropped()

### Community 243 - "provider"
Cohesion: 0.50
Nodes (3): cfg(), provider(), fresh()

## Knowledge Gaps
- **1 isolated node(s):** `pitwall_sim`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 2803 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **74 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RaceEngine` connect `RaceEngine` to `scenarios.py`, `EngineerCommand`, `test_overtake.py`, `load_app`, `config/loader.py`, `engine.py`, `main`, `EngineerView`, `test_safety_car.py`, `snapshot.py`, `Compound`, `test_pit.py`, `LiveSession`, `costs.py`, `time`, `baseline.py`, `.__init__`, `WeatherModel`, `pathlib`, `test_race_engine.py`, `test_overtake_contact.py`, `test_info_barrier.py`, `commands.py`, `test_public_feed.py`, `test_mistakes.py`, `RadarEstimate`, `test_radar.py`, `real_race.py`, `make_command`, `RadarBank`, `_Recorder`, `integration/test_rival_strategy.py`, `numpy`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 100 inferred relationships involving `RaceEngine` (e.g. with `THREADING MODEL` and `_ahead()`) actually correct?**
  _`RaceEngine` has 100 INFERRED edges - model-reasoned connections that need verification._
- **What connects `pitwall_sim` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `scenarios.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06968641114982578 - nodes in this community are weakly interconnected._
- **Why does `EngineerView` connect `EngineerView` to `EngineerCommand`, `load_rule_set`, `engine.py`, `snapshot.py`, `LiveSession`, `costs.py`, `unit/test_alerts.py`, `baseline.py`, `.__init__`, `DriverRadio`, `PROJECT_STATUS.md — what is built, what is on its way, what needs changes`, `PitWallWindow`, `llm_commands.py`, `test_info_barrier.py`, `pitwall_lite.py`, `reveal.py`, `PROCESS_FLOW.md — Pit Wall Race Simulator (2026 Regulations)`, `llm_replies.py`, `RadarEstimate`, `EngineerView`, `SIMPLY_CLIPPING_BRIDGE.md — Test bench for your Simply Clipping`, `UI_DESIGN.md — Pit Wall Race Simulator (2026 Regulations)`, `CLAUDE.md — Agent Entry Point for `pitwall_sim``?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Are the 81 inferred relationships involving `Compound` (e.g. with `1. EXPORT (`python -m pitwall_sim.export`)` and `simulate_quali_lap()`) actually correct?**
  _`Compound` has 81 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_deploy_policy.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07971014492753623 - nodes in this community are weakly interconnected._