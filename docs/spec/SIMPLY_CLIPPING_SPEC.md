# SIMPLY_CLIPPING_SPEC.md — Simply Clipping: rival battery estimator and pit-wall alerts

## PURPOSE

Simply Clipping estimates every rival's hidden 2026 battery energy from public
telemetry and raises pit-wall alerts (ATTACK, DEFEND, RE-PASS RISK,
CLOSING-SPEED RISK). It is the owner's own project, built as a plug-in of the
simulator: the simulator is its test bench and its live pit wall, never a
dependency.

| Item | Value |
| --- | --- |
| Package | `simply_clipping/` (repository root), branch `simply-clipping` |
| Owner | the project owner; agents build it only through the owner's `SC-n` prompts |
| Algorithm source | owner's Rival Battery Radar spec (`docs/planning/SPRINT.md` Part 5, alert rules Part 2) |
| Contract | `docs/spec/SIMPLY_CLIPPING_BRIDGE.md`, exactly |
| Tasks | `docs/planning/TASKS.md` block SC (`SC-0` … `SC-6`, the owner's prompts) |
| Baseline to beat | `docs/results/SC_RESULTS.md` TEST SET, column built-in |

## RULES

Violating any of these is a defect, regardless of scores.

| ID | Rule |
| --- | --- |
| SC-R01 | `simply_clipping` MUST NOT import `pitwall_sim`; `pitwall_sim` MUST NOT import `simply_clipping`. Enforced by import-linter contracts `simply-clipping-independent` and `sim-independent-of-simply-clipping`. |
| SC-R02 | Never read the answer sheet: an export's `truth/`, `baseline/` and `run.json`. The only Ground Truth file allowed is `own_file`, and only the rows of `our` (`loader.load_own` filters while reading). Enforced by `simply_clipping/tests/test_scaffold.py::test_package_never_names_the_answer_sheet`. |
| SC-R03 | Tune only on seeds 1–5 (tune set). Seeds 6–10 (test set) are run and reported, never used to choose a value. Every report gives test-set numbers. |
| SC-R04 | Every constant lives in `simply_clipping/config.yaml` with its source (`RADAR`, `RULES`, `BRIDGE`, `TUNE (SC-n)`). No number is hard-coded in a module, apart from unit conversions (3.6, 1e3, 1e6). |
| SC-R05 | Inputs and outputs follow the bridge contract exactly: `run(feed_dir, out_dir, our, own_file, layout_file)` offline, `create(cfg, track)` live; output files and columns as in BRIDGE section 2. |
| SC-R06 | Confidence MUST be honest (lesson L-e): a value is only published once its reliability check on the tune set passes, otherwise the output keeps the scaffold confidence and says so in the report. |
| SC-R07 | Gates for every SC task: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy pitwall_sim simply_clipping` (strict), `lint-imports`. |
| SC-R08 | Lessons L-a … L-f below are designed in from the step that first touches them; a task that ignores one is not DONE. |

## PACKAGE LAYOUT

| Module | Responsibility | Filled by |
| --- | --- | --- |
| `__init__.py` | `run(...)` (offline pipeline) and `create` (re-exported from `live`) — the two bridge functions | SC-0, each task extends the pipeline |
| `config.yaml` | Every constant, with source | SC-0; values `TUNE (SC-n)` set in that task |
| `loader.py` | `load_config`, `const` (dotted key lookup, KeyError names the key), `load_feed` (cars, laps, gaps), `load_layout`, `load_own` (our rows only); `CarInput` per car with race progress pinned to the public lap starts; `segment_ids` (gaps > 0.5 s); `Track` (zones, corners) | SC-0, SC-1 |
| `physics.py` | `Stream`: streaming, chunk-invariant 10 Hz resample + Savitzky-Golay (7, 2) + acceleration (live and offline give identical points); `P_wheel`, `P_elec`; mass with fuel; ICE power per maker; `CdaFit` / `RunBuilder`: CdA per car per aero mode | SC-1 |
| `energy.py` | States DEPLOY / CLIP / HARVEST / LIFT / CRUISE; energy integration and clamp; anchors; confidence | SC-2 |
| `battles.py` | Pairs within 1.0 s, order and gaps from the public feed | SC-3 |
| `alerts.py` | The four alert rules, 1-lap suppression, closing-speed episodes; `alerts.parquet` rows; radio line (SC-6) | SC-3, SC-6 |
| `live.py` | `Provider` / `create(cfg, track)` for the pit wall: same rules on the rolling live view | SC-3 |
| `real_data.py` | A real race from OpenF1 (cached in `data/openf1_cache/`) converted to the bridge input and run with Our Car's battery estimated (no team data) | SC-5 |
| `tests/` | Unit and contract tests; must not import `pitwall_sim` (SC-R01 covers `simply_clipping.tests`) | every task |

## PIPELINE (offline `run`)

| Step | Input → output | Module | Config keys |
| --- | --- | --- | --- |
| P1 load | `feed/cars.parquet`, `laps.parquet`, `gaps.parquet`, layout JSON, `own_file` rows of `our` → frames | `loader` | — |
| P2 resample | per car, uniform 10 Hz; no interpolation across gaps > 0.5 s | `physics` | `signal.resample_hz`, `signal.max_gap_s` |
| P3 smooth | Savitzky-Golay window 7, order 2 on speed; acceleration from its derivative | `physics` | `signal.savgol_window`, `signal.savgol_order` |
| P4 power | `P_wheel = m·a·v + ½·ρ·CdA·v³ + Crr·m·g·v`; `P_elec = P_wheel / η − P_ICE` | `physics` | `car.*`, `fuel.*` |
| P5 CdA | fit per car per aero mode (straight = a Straight Mode zone / corner) from full-throttle runs below the taper start (290 km/h, owner SC-1); each run has its own unknown power level (partial deploy allowed, L-c), slope fitted on the run's deviations with outliers trimmed; the car's CdA = weighted median of its runs (weights floored, slopes bounded); `cda_fit.json` | `physics` | `cda_fit.*` |
| P6 states | DEPLOY / CLIP / HARVEST / LIFT / CRUISE per point (table STATES). "Full throttle" means steady: full throttle and no brake over the whole filter window (else the smoothed acceleration mixes in the braking that follows and reads as a false CLIP / super-clip). Taper-aware (L-b) | `energy` | `states.*`, `taper.*` |
| P7 energy | `E += (harvest − deploy)·dt` within the lap's harvest limit, clamped `[e_min_mj, e_max_mj]`; deploy and harvest per table FLOWS; EMPTY anchor (L-a); start prior `anchor.start_mj`; confidence (L-e). CdA and ICE power refitted when the car crosses the line (causal) | `energy` | `energy.*`, `deploy.*`, `anchor.*`, `confidence.*` |
| P8 battles | per-car history; who is ahead / behind and the gap (distance ÷ follower's speed) from race progress, not from timing; a rival's last complete pass of a straight with its longest CLIP and detection share | `battles` | `battles.*` |
| P9 alerts | rules in table ALERT RULES, evaluated every `alerts.tick_s` (bench: every tick of the race; pit wall: every tick up to `alerts.latency_s` before now, so both give the same alerts), from Our Car's exact own data and the rivals' estimates | `alerts` | `alerts.*` |
| P10 write | `estimates.parquet` (every car, `output.estimates_hz`), `alerts.parquet` (when `our`), `cda_fit.json` | `__init__` | `output.*` |

Live (`create`): each rival's tracker gets only the frames it has not seen (incremental); laps counted from the lap distance wrapping; the same engine and tick grid as offline. Test: `test_live_and_offline_give_the_same_alerts` (identical alerts on the same race).
(last 120 s per car) and `view.our_car`, called a few times a second; must keep
the pit wall's 16x frame budget (100 ms per frame).

## FLOWS (P7, per steady 10 Hz point)

| Flow | When | Power (kW) | Config |
| --- | --- | --- | --- |
| deploy | steady full throttle on a straight, speed in the observed band | `clip(P_elec, 0, taper limit)`; updates the car's straight-line level | `deploy.observed_kmh`, `deploy.level_tau_s` |
| deploy | steady full throttle on a straight below the band (slow exit) | the car's straight-line level | `deploy.start_level_kw` |
| deploy | steady full throttle in a fast corner | `P_elec` if above `corner_seen_kw` (capped at `corner_cap_kw`), else 0 | `deploy.corner_*` |
| deploy | steady full throttle in a slow corner | `corner_cap_kw` × share of fast-corner points that showed deploy | `deploy.corner_*` |
| deploy | part throttle | `clip(P_elec, 0, limit) × cruise_scale` | `deploy.cruise_scale` |
| harvest | braking | `min(brake_share × braking power, harvest_cap_kw)` | `energy.brake_share`, `energy.harvest_cap_kw` |
| harvest | lifting (throttle < 20 %, no brake) | `lift_harvest_kw` | `energy.lift_harvest_kw` |
| harvest | super-clip: steady full throttle on a straight, ≥ `superclip_min_kmh`, `P_elec` < `anchor.superclip_kw` | `min(−P_elec, harvest_cap_kw)` | `energy.superclip_min_kmh` |
| none | negative `P_elec` anywhere else (full-throttle corners read negative: cornering losses the model leaves out) | 0 | — |

Per lap at most `energy.harvest_max_mj_per_lap` (RULES 8.5 MJ) is harvested; a full battery takes nothing.

## STATES

Same definitions as the scorer's `state_true` (BRIDGE section 1), applied to the
ESTIMATED electric power.

| State | Condition |
| --- | --- |
| HARVEST | brake on |
| LIFT | throttle < `states.lift_throttle_pct` (20 %), no brake |
| DEPLOY | throttle ≥ `states.full_throttle_pct` (95 %) and `P_elec` > `states.deploy_min_kw` (150 kW) |
| CLIP | steady full throttle, `P_elec` < `states.clip_max_kw` (50 kW) and acceleration ≤ `states.clip_max_accel_ms2` (0.3 m/s², speed flat or falling); in the taper band `P_elec` must also be `states.taper_margin_kw` below what the taper allows (L-b) |
| CRUISE | everything else |

## ALERT RULES

From `our`'s point of view (`car_a = our`, `car_b = rival`). Same pair + type is
suppressed for `alerts.suppress_laps` (1) lap.

| Type | Fires when | Config keys |
| --- | --- | --- |
| ATTACK | car ahead within `attack_gap_s` (1.0 s) AND (a) `energy`: its estimate ≥ `attack_margin_mj` (0.8 MJ) below our exact battery with confidence ≥ `min_confidence` (0.4), OR (b) `observed clip`: on its last pass of the straight we are on / coming to it showed a CLIP ≥ `long_clip_s`; confidence = detection share (≥ `detection_min_share`) | `alerts.attack_*`, `min_confidence`, `long_clip_s`, `detection_min_share` |
| DEFEND | car behind within `defend_gap_s` (0.6 s) AND (a) `energy`: its estimate ≥ `defend_margin_mj` (0.8 MJ) above ours, confidence ≥ 0.4, OR (b) `own battery`: our battery < `need_share` × what full deploy on the coming straight needs, AND the car behind was not seen clipping there last lap (detection share ≥ `detection_min_share`) | `alerts.defend_*`, `need_share` |
| REPASS_RISK | we passed a car in the last `repass_window_s` (15 s) AND our battery < `repass_our_max_mj` (1.0 MJ) AND the coming straight is longer than `repass_straight_m` (600 m); confidence 1.0 (our own data) | `alerts.repass_*` |
| CLOSING_SPEED_RISK | Our Car involved: a rival within `closing_range_m` (200 m), closing speed > `closing_dv_kmh` (40 km/h), the slower car CLIP / LIFT and the faster DEPLOY (ours from our exact battery's rate); ONE alert per episode, for the biggest-closing rival; an episode ends after `closing_episode_gap_s` without a closing pair (L-f) | `alerts.closing_*` |

## RADIO LINE (SC-6)

Every alert carries `radio`: one line of at most `alerts.radio_max_words` (12)
words, made from a template and only the alert's own evidence (no Gemma: not
set up). The pit wall shows it as the alert's headline (the sim's `alert_line`
uses a provider's `radio` when present).

| Alert / branch | Template |
| --- | --- |
| ATTACK energy | `{rival} has {rival_mj} MJ, we have {our_mj}. Attack into {corner}.` |
| ATTACK observed clip | `{rival} clipped here last lap. Attack into {corner}.` |
| DEFEND energy | `{rival} behind has {rival_mj} MJ, we have {our_mj}. Defend {corner}.` |
| DEFEND own battery | `We have {our_mj} MJ, straight needs {need_mj}. Defend {corner}.` |
| REPASS_RISK | `Only {our_mj} MJ, long straight ahead. {rival} can re-pass.` |
| CLOSING_SPEED_RISK | `Closing {dv_kmh} km/h on {rival}. Careful into {corner}.` |

## LESSONS FROM THE SIMULATOR (designed in from the start)

| ID | Lesson | Design response | Step | Measured by (scorer) |
| --- | --- | --- | --- | --- |
| L-a | Super-clip ≠ empty battery: 2026 cars super-clip on purpose with energy left. | EMPTY anchor only on the "ran out" pattern: at steady full throttle early on a long straight the car neither deploys (`P_elec` < `anchor.no_deploy_kw`) nor harvests (`P_elec` > `anchor.superclip_kw`) for `anchor.min_clip_s`; then `E = anchor.empty_mj`. A super-clip (P_elec ≈ −350 kW at speed on a straight) is integrated as harvest. | P7, SC-2 | energy bias by time since anchor; cda_trap MAE |
| L-b | The 290–355 km/h regulated speed taper (Overtake 337–355) is not CLIP. | In the taper band, expected MGU-K power falls with speed (`taper.*`); a power drop the taper explains is DEPLOY / CRUISE, never CLIP, and never an anchor. | P6, SC-3 | false CLIP while `taper_active` (target ≤ 1 %) |
| L-c | Cars often deploy partially (150–250 kW), not always 350 kW. | CdA fit with one unknown power level per run (SC-1). Deploy = estimated `P_elec` where the speed trace shows it; where it cannot (slow exits, corners: grip, not power, limits the car) the car's own recent straight-line level, and in slow corners the corner cap times the share of fast corners that showed deploy (PUSH deploys there, BALANCED does not). | P5, P7, SC-1, SC-2 | CdA % error; energy MAE by Energy Mode |
| L-d | ICE power differs per maker; fuel mass falls over the race. | `P_ICE` per team (`car.p_ice_kw_by_team`, fitted on the tune set from public data, default `car.p_ice_kw`); mass = `car.mass_kg` + fuel left (`fuel.*`, falling per lap). | P4, SC-1 | CdA % error (pu_spread-like spread), energy bias per team |
| L-e | Confidence must be honest: 0.8 confidence ≈ right 80 % of the time. | Confidence from time since anchor, missing samples and fit quality, then mapped through a reliability table fitted on seeds 1–5 (`confidence.calibration`). | P7, SC-4, SC-7 | MAE conf ≥ 0.5 vs < 0.5; reliability table (share right per confidence bin) |
| L-f | Closing-speed alerts: one per episode, the single biggest-closing rival. | Episodes grouped in time (`alerts.closing_episode_gap_s`); per episode one alert, for the rival with the largest Δv. | P9, SC-6 | closing-speed precision, alerts per race, closing incident pass |

## CONTRACT

Exactly `docs/spec/SIMPLY_CLIPPING_BRIDGE.md`. Summary for agents:

| Function | Reads | Writes / returns |
| --- | --- | --- |
| `run(feed_dir, out_dir, our, own_file, layout_file)` | `feed_dir`: `cars.parquet`, `laps.parquet`, `gaps.parquet` (raw `car_data` / `pos_data` allowed); `layout_file`; `own_file` rows of `our` only | `out_dir/estimates.parquet` (`driver`, `time_s`, `energy_mj`, `state`, `confidence`, optional `since_anchor_s`); `out_dir/alerts.parquet` when `our` (`time_s`, `lap`, `type`, `car_a`, `car_b`, `confidence`, optional `branch`); optional `cda_fit.json` |
| `create(cfg, track)` → provider; `provider.update(view)` | `view.t_s`, `view.our_car`, `view.timing`, `view.rival_feed`, `track` zones / corners. NOT `view.radar` (the sim's own estimates). | list of objects with the fields of the sim's `Alert` (`alert_id`, `type`, `rival`, `lap`, `corner_id`, `evidence`, `confidence`, `created_t`, `expires_t`), built without importing the sim (SC-R01) |

Never read: `truth/`, `baseline/`, `run.json` (SC-R02).

## TARGETS

Built-in baseline, TEST SET seeds 6–10, from `docs/results/SC_RESULTS.md` (mean
over seeds). "Beat" = better mean on the test set in every scenario listed.

| Metric | Built-in (test set) | Target | Direction |
| --- | --- | --- | --- |
| Energy MAE MJ | normal 0.92, battles 0.84, cda_trap 0.85, closing_speed 0.95, repass 0.97, taper 1.28 (≈ 0.9) | below the built-in in every scenario | lower |
| CLIP precision | 4–6 % (battles 6 %, others 4 %) | above the built-in in every scenario | higher |
| CLIP recall (guard, agent proposal) | 35–41 % | not below the built-in (stops "never say CLIP" from winning precision) | higher |
| False CLIP while taper active (guard, L-b) | 0–1 % | ≤ 1 % | lower |
| ATTACK precision | normal 8 % (battles 36 %, cda_trap 11 %, closing_speed 10 %, repass 26 %, taper 10 %) | above the built-in, normal first | higher |
| Repass incident pass | 33 % | above 33 % | higher |
| Closing-speed incident pass | 0 % | above 0 % | higher |
| Alerts per race (guard) | 30–64 | ≤ 100 (scorer flag) | lower |

## CONFIG (`simply_clipping/config.yaml`)

| Section | Keys | Source |
| --- | --- | --- |
| `signal` | `resample_hz` 10, `savgol_window` 7, `savgol_order` 2, `max_gap_s` 0.5 | RADAR |
| `car` | `mass_kg` 768 (RULES minimum mass; fuel added below), `rho_kg_m3` 1.18, `crr` 0.012, `g_ms2` 9.81, `eta` 0.92, `p_ice_kw` 400, `p_ice_kw_by_team` {}, `p_elec_max_kw` 350 | RADAR / RULES; per-team ICE TUNE (SC-2) |
| `fuel` | `start_kg` 90, `burn_kg_per_lap` 1.7 | TUNE (SC-1, `docs/results/SC_TUNING.md`) |
| `taper` | `start_kmh` 290, `end_kmh` 355, `overtake_start_kmh` 337, `overtake_end_kmh` 355 | RULES |
| `states` | `full_throttle_pct` 95, `lift_throttle_pct` 20, `deploy_min_kw` 150, `clip_max_kw` 50, `clip_max_accel_ms2` 0.3, `partial_deploy_kw` [150, 250] | RADAR / BRIDGE |
| `deploy` | `observed_kmh`, `level_tau_s`, `start_level_kw`, `corner_min_kmh`, `corner_seen_kw`, `corner_tau_s`, `corner_cap_kw` 250 (RULES), `cruise_scale` | TUNE (SC-2), L-c |
| `cda_fit` | `aero_modes`, `v_min_kmh` (straight 230, corner 150), `v_max_kmh` 290, `min_points` 15, `min_dv_kmh` 20, `trim_mad` 3, `trim_rounds` 2, `min_runs` 3, `cda_bounds_m2` 0.2–3.0, `resid_floor_kw` 20, `prior_m2` (straight 0.77, corner 1.62) | owner SC-1; TUNE (SC-1) |
| `energy` | `e_min_mj` 0, `e_max_mj` 4, `harvest_cap_kw` 350, `harvest_max_mj_per_lap` 8.5, `brake_share`, `lift_harvest_kw`, `superclip_min_kmh` | RADAR / RULES / owner SC-2; TUNE (SC-2) |
| `anchor` | `start_mj` 4.0, `min_straight_m` 600, `max_start_frac`, `min_clip_s`, `no_deploy_kw`, `superclip_kw`, `empty_mj` | owner SC-2 / RADAR; TUNE (SC-2), L-a |
| `confidence` | `half_life_s`, `missing_tau_s`, `missing_scale_s`, `right_tol_mj` 0.5, `calibration` (raw → hit-rate table from `python -m pitwall_sim.evaluate.reliability`, tune seeds) | TUNE (SC-2); `right_tol_mj` OPEN (O-1) |
| `battles` | `within_s` 1.0, `stale_s`, `min_speed_kmh` | RADAR; STRUCTURAL |
| `alerts` | thresholds in ALERT RULES (SC-4: `attack_margin_mj` / `defend_margin_mj` 1.2, `need_share` 0.4), `suppress_laps` 1, `expires_s` 8, `tick_s`, `latency_s`, `feed_batch_s`, `own_rate_s`, `history_s`, `closing_*` states, `closing_min_speed_kmh` (pit lane), `radio_max_words` 12 | RADAR / owner SC-3; STRUCTURAL; TUNE (SC-3, SC-4) |
| `output` | `estimates_hz` 1.0 | BRIDGE ("once a second per car is plenty") |

## TEST PLAN

| Level | What | Where |
| --- | --- | --- |
| Unit | each module on small synthetic frames (no export needed) | `simply_clipping/tests/` |
| Contract | `run` writes the bridge columns and value ranges; `load_own` returns only `our`; package never names the answer sheet; live `create` / `update` | `simply_clipping/tests/test_scaffold.py` |
| Bench, tune set | `python -m pitwall_sim.bench --sc-module simply_clipping --scenario all --seeds 1-5 --rerun` | tuning only |
| Bench, test set | `python -m pitwall_sim.bench --sc-module simply_clipping --scenario all --seeds 6-10 --rerun` | the numbers every report quotes |

## OPEN ITEMS (owner decides)

| ID | Item |
| --- | --- |
| O-1 | What "right" means for honest confidence (L-e): proposed \|estimate − true\| ≤ `confidence.right_tol_mj` = 0.5 MJ. The scorer has no reliability table yet; SC-7 adds it to the bench report (sim side) or Simply Clipping computes it on the tune set only. |
| O-2 | Closed 2026-10-30: the owner's prompts SC-1 … SC-6 arrived; TASKS rows match them. |
| O-3 | CLOSING-SPEED rule vs the closing-speed incident target. The rule (owner SC-3) needs the faster car in DEPLOY and the slower in CLIP / LIFT; the sim's closing events (and the incident check) need only Δv > 40 km/h within 200 m with either car CLIP or LIFT, and most start when the car ahead brakes (e.g. closing_speed seed 1, lap 1: Our Car CLIP at 238 km/h, the rival braking). On the tune set no variant passes the incident (0 %), even with the states relaxed (fast: DEPLOY / CLIP / CRUISE, slow: CLIP / LIFT / HARVEST, anywhere on track: closing recall 26-73 % but 125-210 alerts per race): an alert cannot come before a braking-triggered event on lap 1. Owner: keep the rule as specified (current), or change the rule or the target. |
