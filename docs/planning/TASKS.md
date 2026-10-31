# TASKS.md — Pit Wall Race Simulator (2026 Regulations)

## PURPOSE

This is the ordered work list for building `pitwall_sim`. Agents pick tasks from here, following the workflow in `CLAUDE.md`.

Feature IDs (`F01`–`F20`) come from `docs/spec/PRD.md`. Releases and MVP acceptance IDs (`MVP-01`…`MVP-10`) come from `docs/spec/MVP.md`. Technical references point to sections of `docs/spec/TRD.md`, `docs/spec/PROCESS_FLOW.md` and `docs/spec/UI_DESIGN.md`.

## RULES

- Status values: `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `PARKED` (deliberately set aside by the owner).
- A task MAY start only when every task in `Depends on` is `DONE`.
- A task is `DONE` only when all its acceptance criteria pass and `ruff check .`, `lint-imports`, `pytest -q` pass.
- R1 tasks are detailed. R2–R5 tasks are coarser and MUST be split into smaller tasks before starting (add them in this file with the same ID prefix).
- Do not renumber tasks. New tasks take the next free number in their block.

## S — Deadline sprint: alerts and calling the driver (owner, 2026-10-26 to 2026-10-31)

Overrides the R1 order until 2026-10-31 (owner sprint decision + "Sprint change:
alerts + call the driver", which replaces the Simply Clipping export addendum).
Simply Clipping does not exist yet: its alert logic is built inside the sim as a
swappable `AlertProvider` plug-in that sees `EngineerView` only, and alerts are
made actionable from the pit wall. Day order: S-2 → A-1 + A-5 → S-5 + A-3 + A-2
→ A-4 + presets + fixes → S-6. S-1 export, S-3 scorer and S-4 batch come after
the deadline (for testing the real Simply Clipping through the same interface).

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| S-2 | Replay viewer (day 1): record a headless race and replay it: `python -m pitwall_sim.viewer --seed 42` (records, then plays) or `--run <dir>`; track map with all cars (team colours, driver codes), timing tower (position, gap, tyre), battery trace for a selected car (true solid, Radar Estimate dashed, truth toggle), play / pause, 1x / 4x / 16x, lap slider | `pitwall_sim/viewer/` (new) | T-041, T-052 | Runs on the owner's laptop; ≥ 10 fps at 16x | Sprint S-2, UI_DESIGN colours | DONE |
| A-1 | Alert provider plug-in (day 2): `observe/alerts.py` `AlertProvider.update(view: EngineerView) -> list[Alert]`; built-in `simply_clipping_lite` (ATTACK, DEFEND, RE-PASS RISK, CLOSING-SPEED RISK from Our Car's view, same pair + type suppressed 1 lap, evidence, confidence, expiry); `app.yaml: alerts.*` incl. `provider` (`external:<module.path>` later) | `pitwall_sim/observe/alerts.py`, `config/app.yaml` | T-052 | A-5 tests | Sprint A-1, Rival Battery Radar spec | DONE (headless check: `python -m pitwall_sim.observe.alerts_check --seed 42`) |
| A-5 | Alert tests (day 2): each type fires in a constructed scenario and not when its condition is false; each call option sends exactly its commands; a forked comparison shows a call changes the outcome (DEFEND option keeps position more often than ignoring over 20 seeds); info barrier (lint-imports + test) | `tests/` | A-1, A-2 | All pass | Sprint A-5 | DONE (day 5: paired forks via `python -m pitwall_sim.engineer.call_outcome`, 20 seeds x 5 forks: ATTACK answered 33 % vs ignored 7 % (+26 points), DEFEND 85 % vs 33 % (+52); from lap 5 on: ATTACK +27, DEFEND +12 (13 alerts); after ATTACK / DEFEND became persistent calls and the alerts got the observed-clip / own-battery branches) |
| S-5 | Live pit wall lite (day 3): `python main.py` → setup (Suzuka, rule set, Our Car, seed, Test mode, Pause on alert) → live race: track map, timing tower, Our Car status, Rival radar panel, battery trace, PAUSE / 1x / 4x / 16x, command buttons; EngineerView only, truth overlays only in Test mode (clearly labelled) | `main.py`, `pitwall_sim/ui/` | T-061, S-2 | Runs on the owner's laptop | Sprint S-5 | DONE (`python main.py`) |
| A-3 | Alert feed panel (day 3): newest on top, colour by type, hidden below `alerts.min_confidence` 0.4 and greyed below `alerts.low_confidence` 0.6 (day 4), expiry countdown, option buttons, F1/F2/F3 on the newest alert, evidence on click, Test mode shows the rival's true battery | `pitwall_sim/ui/` | S-5, A-1 | Usable live | Sprint A-3 | DONE |
| A-2 | Call the driver (day 3): per alert type the listed options, each = validated Engineer Commands (radio latency) + template radio line and template driver ack; rejected commands show the reason | `pitwall_sim/engineer/calls.py` (new) | A-1, T-061 | A-5 tests | Sprint A-2 | DONE (day 5: DEFEND [1] is DEFEND(corner) only; ATTACK / DEFEND last until the situation is over, at most 2 laps; headline and radio say which rule fired) |
| A-4 | End-of-race call summary (day 4): every alert with option chosen / ignored / expired and the outcome in the next 2 laps; totals; Test mode: alert correct per Ground Truth | `pitwall_sim/engineer/`, `pitwall_sim/ui/` | A-2 | Shown after the flag | Sprint A-4 | DONE (`live/session.py` CallSummary, UI Call summary dialog; screenshot docs/screenshots/day4_summary.png) |
| A-6 | Setup presets (day 4): `repass` and `closing_speed` quick starts in the live sim | `pitwall_sim/ui/`, `pitwall_sim/race/` | S-5 | Each preset produces its situation | Sprint day 4 | DONE (`live/presets.py`; setup screen Scenario combo; each fires its alert within 3 laps, tests/integration/test_presets_summary.py) |
| S-6 | README quick start, polish, fixes (day 5); no new features | `README.md` | all above | Commands work as written | Sprint day 5 | DONE (README quick start; timing tests best of 3 on a quiet machine: headless race 8.41 s / 10 s, kernel step 9.1 us / 20 us, 16x UI slowest frame 10 ms / 100 ms) |
| S-1 | Race export for Simply Clipping (owner day 5 follow-up): `python -m pitwall_sim.export --seed N --scenario normal\|battles\|repass\|closing_speed\|taper\|cda_trap\|all --out <dir>`; FastF1-like feed (car_data, pos_data, cars, laps, gaps; dropouts, jitter, noise), 10 Hz Ground Truth (superclip, taper, zone cap, CdA, mass, state_true), events with scenario targets, car_params.json, run.json; built-in alerts for a point-of-view car as baseline | `pitwall_sim/export/` | T-041, T-050 | Every scenario's target event logged and reported | SPRINT Parts 1, 3, 5 | DONE (high_drag_full, partial_deploy, pu_spread not built) |
| S-3 | Scorer (owner day 5 follow-up): `python -m pitwall_sim.evaluate --run <dir> [--estimates] [--alerts] [--cda-fit] --baseline`; energy MAE / p90 / bias by mode, confidence and time since anchor; state confusion, CLIP precision / recall, false CLIP in taper; CdA % error; alert recall / precision / lead time / right-per-truth per type and branch; incident pass/fail; baselines: built-in Radar on the exported feed + built-in alerts + dumb ATTACK rule; contract in docs/spec/SIMPLY_CLIPPING_BRIDGE.md | `pitwall_sim/evaluate/` | S-1 | Scores the baselines on an export | SPRINT Parts 1, 3, 5 | DONE |
| S-4 | Batch runner: seeds x scenarios, resumable, scored per run, docs/results/SC_RESULTS.md rewritten after every run; tune seeds 1-5 / test seeds 6-10 apart; built-in, dumb rule and Simply Clipping columns | `pitwall_sim/export/`, `pitwall_sim/evaluate/batch.py` | S-1, S-3 | Partial results survive a stopped run | SPRINT Parts 3, 4 | DONE (10 seeds x 6 scenarios = 60 full races; docs/results/SC_RESULTS.md; timing tests afterwards, best of 3: headless race 4.87 s / 10 s, kernel step 7.2 us / 20 us, 16x UI slowest frame 4 ms / 100 ms) |
| SC-v0 | Simply Clipping v0 package (the agent's, sprint day 7; was `SC-0` until 2026-10-30) | — | — | — | SPRINT Part 4 | ARCHIVED (owner, day 8: the owner builds Simply Clipping; branch `archive/sc-v0`, tag `sc-v0`) |
| BENCH | Test bench for the owner's package (owner, day 8): `python -m pitwall_sim.bench --sc-module <module> --scenario all --seeds 6-10` (export -> plug-in `run(...)` -> scorer -> report, resumable); hello-world plug-in `docs/examples/hello_clipping.py`; live plug-in through `alerts.provider: external:<module>` | `pitwall_sim/bench/`, `docs/` | S-1, S-3, S-4 | The template runs through the bench and plugs into the pit wall | SPRINT owner day 8 | DONE |

## SC — Simply Clipping (owner's project, branch `simply-clipping`, from 2026-10-30)

The owner's rival battery estimator, built as a plug-in of the simulator in
`simply_clipping/`. Spec, rules (`SC-R01`…`SC-R08`), lessons (`L-a`…`L-f`) and
targets: `docs/spec/SIMPLY_CLIPPING_SPEC.md`. Contract:
`docs/spec/SIMPLY_CLIPPING_BRIDGE.md`. Every SC task: tune on seeds 1-5 only,
report seeds 6-10 (test set) with
`python -m pitwall_sim.bench --sc-module simply_clipping --scenario all --seeds 6-10 --rerun`;
never read `truth/` inside `simply_clipping`; gates `pytest -q`, `ruff check .`,
`ruff format --check .`, `mypy pitwall_sim simply_clipping`, `lint-imports`.
Rows SC-1…SC-6 follow the owner's prompts of 2026-10-30.

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| SC-0 | Scaffold + spec: `docs/spec/SIMPLY_CLIPPING_SPEC.md`; `simply_clipping/` from the hello template (loader, physics, energy, battles, alerts, live, config.yaml, tests); import contracts both ways; bench wiring run | `simply_clipping/`, `docs/spec/SIMPLY_CLIPPING_SPEC.md`, `.importlinter`, `pyproject.toml` | BENCH | `python -m pitwall_sim.bench --sc-module simply_clipping --scenario normal --seeds 6` runs; contracts kept; gates pass | SPEC all | DONE (scaffold = prior 2.0 MJ, no alerts: energy MAE 1.18 MJ on normal_s6) |
| SC-1 | Loader + physics + CdA fit (owner prompt SC-1): feed per car with gaps > 0.5 s splitting segments; 10 Hz resample, Savitzky-Golay (7, 2), acceleration, `P_wheel`, `P_elec` from config; CdA per car per aero mode from full-throttle samples below 290 km/h, robust least squares; `cda_fit.json` | `simply_clipping/loader.py`, `physics.py`, `config.yaml`; bench CdA rows (`pitwall_sim/evaluate`, `pitwall_sim/bench`) | SC-0 | Tests: constant speed = drag + rolling only; zero speed = zero power; known CdA recovered within 5 %. Bench tune seeds 1-5 (normal, cda_trap, taper): CdA error per car | owner SC-1, SPEC P1-P5 | DONE (tune set: mean \|err\| straight 2.6-4.0 %, corner 2.7-4.4 %, trap cars +3.9 %; every car's mean within ±6 %) |
| SC-2 | Energy estimate (owner prompt SC-2): states, taper rule, partial deploy level, integration with harvest cap and clamp, EMPTY anchor only for a "ran out" clip (not super-clip), start prior ~full, confidence calibrated on seeds 1-5 | `simply_clipping/energy.py` | SC-1 | Tests: scripted full-then-clip, super-clip-with-energy and taper-limited laps give the right states, within 0.5 MJ. Bench tune set all scenarios, then test seeds 6-10 once vs the built-in | owner SC-2, SPEC P6-P7, L-a, L-b, L-c, L-e | DONE (test set once, seeds 6-10, built-in → SC: energy MAE 0.84-1.28 → 0.36-0.88 MJ in every scenario; within 0.5 MJ 20-41 % → 38-73 %; confidence ECE 18-34 % → 4-10 % per scenario, 0.9 % pooled; CLIP precision 4-6 % → 53-66 %; CLIP recall 35-41 % → 19-27 % (lower); false CLIP in taper 0-2 %) |
| SC-3 | Battles + alerts + live plug-in (owner prompt SC-3): battles within 1.0 s from positions; ATTACK (a) energy / (b) long CLIP last lap; DEFEND (a) energy / (b) own battery; RE-PASS; CLOSING-SPEED with Our Car, one per episode; 1-lap suppression; evidence, confidence, branch; incremental `live.py` | `simply_clipping/battles.py`, `alerts.py`, `live.py` | SC-2 | Tests: each alert fires in a constructed case and not otherwise; live and offline give the same alerts. Bench recall / precision / lead time, both incident checks; live check seed 42 GAS, screenshot `docs/screenshots/sc3_live.png` | owner SC-3, SPEC P8-P9, L-f | DONE (tests incl. live = offline; test set once, built-in → SC: ATTACK right 14-71 → 19-97 %, DEFEND recall 25-60 → 50-100 %, repass incident 33 → 67 %, closing incident 0 → 0 % (spec O-3), normal ATTACK precision 8 → 4 % (SC-4), alerts / race 44-101; live seed 42 GAS Test mode: 36 alerts, 16 / 24 right per truth, 16x frames p99 25 ms; `docs/screenshots/sc3_live.png`) |
| SC-4 | Tuning + final results (owner prompt SC-4): tune on seeds 1-5 only with a log in `docs/results/SC_TUNING.md`; test set once; Simply Clipping column in `docs/results/SC_RESULTS.md`; tag `sc-v1` | `simply_clipping/config.yaml`, `docs/results/` | SC-3 | Test set run once with the final config; every TARGETS row compared | owner SC-4, SPEC TARGETS | DONE (tag `sc-v1`; test set once: energy MAE 0.36-0.88 vs 0.84-1.28 MJ, confidence ECE 4-10 vs 18-34 %, CLIP precision 53-66 vs 4-6 %, repass incident 67 vs 33 %, alerts / race 30-77: beaten; normal ATTACK precision 0 vs 8 % and closing incident 0 vs 0 %: not beaten (spec O-3); `docs/results/SC_RESULTS.md`, `docs/results/SC_TUNING.md`) |
| SC-5 | Real 2026 Japanese GP check (owner prompt SC-5): `simply_clipping/real_data.py` fetches OpenF1 (cache `data/openf1_cache/`), converts to the bridge input; NOR/HAM re-pass and BEA/COL closing-speed incidents | `simply_clipping/real_data.py`, `docs/results/SC_RESULTS.md` | SC-4 | Alert time, lead time, evidence per incident, or an honest "the data does not show it" | owner SC-5 | DONE (OpenF1 session 11253, cached; a) NOR/HAM: RE-PASS RISK at both passes (laps 47, 50), 15.1 s and 20.0 s before HAM re-passed; b) BEA/COL lap 22: not caught: BEA's speed channel is frozen at 262 km/h before the crash, the closing (35-42 km/h) shows only in positions; `docs/results/SC_RESULTS.md` REAL RACE) |
| SC-6 | Radio line + demo (owner prompt SC-6): one-line template radio call per alert (≤ 12 words, evidence facts only); `docs/guides/DEMO_SC.md`; README section | `simply_clipping/alerts.py`, `docs/guides/DEMO_SC.md`, `README.md` | SC-5 | Full gates; after this bug fixes only | owner SC-6 | DONE (template radio line ≤ 12 words from the evidence, shown as the pit-wall headline (no Gemma set up); `docs/guides/DEMO_SC.md` rehearsed (seed 5, 3 laps); README section; post-v1 fix: pit-lane cars no longer raise CLOSING-SPEED alerts. Bug fixes only from here) |

## R1 — MVP

### Block 0: Foundation

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-001 | Repository scaffold: package layout, `pyproject.toml` with dependencies, ruff, pytest, import-linter contracts `sim-headless` (HR-01) and `ui-info-barrier` (HR-02) | `pyproject.toml`, `.importlinter`, package `__init__.py` files per TRD REPOSITORY STRUCTURE, `docs/` | — | `pytest -q` runs (0 tests OK); `lint-imports` passes; `ruff check .` passes | TRD REPOSITORY STRUCTURE, SETUP.md | DONE |
| T-002 | Config models and loader with validation; detects `UNRESOLVED`/`UNKNOWN` values used at runtime | `pitwall_sim/config/models.py`, `pitwall_sim/config/loader.py` | T-001 | Loading a YAML with a wrong type fails with a clear error; loader returns list of unresolved keys | TRD CONFIG SCHEMAS | DONE |
| T-003 | Rule Set files `2026_pre_miami.yaml`, `2026_post_miami.yaml` with every value from TRD RULE SET VALUES; unknowns as `UNRESOLVED` | `config/rules/*.yaml` | T-002 | `test_rules_load` passes; report lists unresolved keys | TRD RULE SET VALUES | DONE |
| T-004 | Grid, team performance and tyre config: `real_2026.yaml` (from FastF1 results of latest cached 2026 race), `fictional.yaml`, `teams/performance.yaml`, `tyres.yaml` with `# PLACEHOLDER: calibrate` values | `config/grid/*.yaml`, `config/teams/performance.yaml`, `config/tyres.yaml` | T-002 | Both grids load; 22 drivers each; every `team_id` in grid exists in `performance.yaml` | TRD CONFIG SCHEMAS, PRD F19 | DONE |
| T-005 | `app.yaml` with sim, feed, ui, radar, debrief, predictor, radio defaults from TRD | `config/app.yaml` | T-002 | Loads; values equal TRD defaults | TRD TIME STEPPING, PUBLIC FEED | DONE |

### Block 1: Track

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-010 | Track builder: FastF1 fastest lap → 1 m resampled centre line, curvature, auto straight tagging, CLI | `pitwall_sim/track/builder.py` | T-002 | `python -m pitwall_sim.track.builder --track suzuka` writes `data/tracks/suzuka.parquet`; closed loop; length within ±1% of official | TRD F01, PF-01 | DONE |
| T-011 | Suzuka track config: zones, corners, detection points, pit entry/exit; manual values documented with source | `config/tracks/suzuka.yaml` | T-010 | Auto-tagged straights and `track_builder` STRUCTURAL settings re-checked against the real layout (owner round 6); all zone ids unique; every zone inside track length; overtaking zone source noted (or `UNRESOLVED`) | TRD CONFIG SCHEMAS, MVP-01 | DONE |

### Block 2: Single-car physics

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-020 | `CarState`, `RaceState` dataclasses + parallel array mirror for Numba | `pitwall_sim/race/state.py` | T-002 | Round-trip dataclass ↔ arrays lossless (test) | TRD DATA CONTRACTS | DONE |
| T-021 | Powertrain: ICE, MGU-K, tapers, zone caps, boost net cap, Overtake mode energy | `pitwall_sim/car/powertrain.py` | T-003, T-020 | `test_taper` passes for both Rule Sets; zone caps applied per zone tag; `acceleration_zone` cap only under `2026_post_miami` | TRD Powertrain | DONE |
| T-022 | Battery: integration, clamp, harvest sources, super-clip, per-lap counters | `pitwall_sim/car/battery.py` | T-021 | `test_battery_bounds`, `test_lap_limits` pass | TRD Battery | DONE |
| T-023 | Aero (Straight Mode / Corner Mode), fuel, tyres (MVP: constant optimal temperature) | `pitwall_sim/car/aero.py`, `fuel.py`, `tyres.py` | T-020 | Unit tests: CdA switches by zone tag; fuel mass decreases monotonic; wear increases monotonic | TRD Active aero, Tyres, Fuel | DONE |
| T-024 | Reference speed profile: QSS forward/backward pass | `pitwall_sim/car/` (new `speed_profile.py`) | T-010, T-023 | `test_constant_speed_power` passes; profile never exceeds `v_corner`; check corner speeds for the known builder curvature overshoot at straight/corner joins (TRD OPEN ITEMS) | TRD Longitudinal dynamics | DONE |
| T-025 | Single-car lap simulation + calibration compare CLI | `pitwall_sim/calibration/compare.py` | T-022, T-024 | `python -m pitwall_sim.calibration.compare --track suzuka` prints lap time delta and speed RMSE | TRD CALIBRATION, PF-02 | DONE |
| T-026 | Calibrate team coefficients for Suzuka | `config/teams/performance.yaml`, `config/tyres.yaml` | T-025 | **MVP-02**: lap time within 2% of reference | TRD CALIBRATION | DONE (provisional, owner round 11: lap time within 2 % of each team's target, order within ±2, speed RMSE ≤ 20 km/h; values marked CALIBRATED-PROVISIONAL, bound hits in docs/results/CALIBRATION_NOTES.md; final calibration is T-02A) |
| T-027 | Derive acceleration zones from the speed profile: for every track without FIA-published zones, tag `acceleration_zone` from corner exit (minimum-speed point) to the next braking point where the accelerating stretch is ≥ 200 m (structural default in `app.yaml`); set `acceleration_zones_source: derived`; FIA-published zones always win | `pitwall_sim/track/` (new), `config/tracks/*.yaml`, `config/app.yaml` | T-024 | Suzuka: derived zones compared with the manual tags and the difference reported; tracks with `acceleration_zones_source: fia` untouched | TRD OPEN ITEMS (acceleration zones), Powertrain | DONE (derived zones stored in suzuka.yaml, not applied; owner round 16) |
| T-028 | Calibration lap energy policy (owner decision (c), replaces the zones-only T-026 rule): deploy anywhere at full throttle within the Rule Set caps; if the lap is energy-limited, super-clip at the end of every acceleration zone (real 2026 qualifying behaviour), at most the deployment shortfall and the harvest allowance left after braking, sized for the fastest lap and shared by zone length | `pitwall_sim/calibration/deploy_policy.py` (reused by T-031), `car/lap_sim.py` (unmet deploy) | T-026 | Clip only at acceleration-zone ends and never above the shortfall; policy lap no slower than greedy; pole lap harvest and top speed reported vs real; unit tests | TRD CALIBRATION, Battery (super-clipping) | DONE |
| T-029 | Track geometry from multiple pooled laps: average the fastest N clean qualifying laps (structural default N = 5, from different drivers) before fitting the centre line | `pitwall_sim/track/builder.py`, `config/app.yaml` | T-010, T-026 | T-010 checks re-run (closed loop, ±1 % raw length, normalized); Suzuka rebuilt; T-011 zones and corners re-checked | TRD F01, PF-01 | DONE |
| T-02A | Re-run the T-026 calibration on the T-028 / T-029 model (owner rounds 12-15) | `config/teams/performance.yaml`, `config/tyres.yaml`, `docs/results/CALIBRATION_NOTES.md` | T-028, T-029 | Closed by owner round 15: fit 2 (load sensitivity, energy-spreading policy, penalized centre line) written as CALIBRATED-PROVISIONAL (T-02A fit 2); every team within 2 %, order within ±2, RMSE 21-25 km/h and plausibility not met, so the final calibration moves to T-02D | TRD CALIBRATION | DONE (provisional) |
| T-02B | Race fuel calibration (owner round 13): set the track `fuel_start_kg` so the race distance ends with 0.5–2 kg left at the real race pace; burn from `P_ice` / fuel energy (3000 MJ/h rule limit) | `config/tracks/suzuka.yaml`, `docs/results/CALIBRATION_NOTES.md` | T-033, T-02C | Suzuka race at the T-02C pace finishes with 0.5–2 kg for every finisher; `# PLACEHOLDER` mark on `fuel_start_kg` replaced by a calibration note | TRD Fuel, CALIBRATION | PARKED (sprint, until 2026-10-31) |
| T-02C | Race calibration (F20, owner round 13): tune the race energy balance, part-throttle harvest, tyre wear and overtake weights against the real Suzuka race | `config/teams/performance.yaml`, `config/tyres.yaml`, `config/app.yaml` (`overtake`, `dirty_air`, `slipstream`), `docs/results/CALIBRATION_NOTES.md` | T-02A, T-041 | Simulated median race lap within 2 % of the real 95.8 s (OpenF1 session 11253); on-track overtakes per race near the real count (source to be reported) | TRD CALIBRATION, OVERTAKE MODEL | PARKED (sprint, until 2026-10-31) |
| T-02D | Geometry + constrained fit (owner round 15): (a) a high-resolution public circuit outline (e.g. GitHub bacinger/f1-circuits GeoJSON; licence and Suzuka checked) projected to metres, resampled at 1 m, scaled to official_length_m and aligned with the OpenF1 lap; per corner use the source whose radius is closer to the one implied by real minimum speeds, source recorded in suzuka.yaml (no usable source: report, keep the current shape); (b) plausibility as a constraint inside the fit (lateral ≤ 5.5 g, braking ≤ 6.0 g, Esses ≤ +15 km/h); (c) one fit | `pitwall_sim/track/`, `pitwall_sim/calibration/fit.py`, `config/tracks/suzuka.yaml`, `config/teams/performance.yaml`, `config/tyres.yaml`, `docs/results/CALIBRATION_NOTES.md` | T-041 | MUST: every team within 2 % of its target, order within ±2, plausibility limits met, no bound hits on shared tyre coefficients; SHOULD: RMSE ≤ 15 km/h (15-20 km/h accepted with all MUSTs, per-corner residuals in CALIBRATION_NOTES.md) | TRD CALIBRATION | PARKED (sprint, until 2026-10-31) |

### Block 3: Race

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-030 | Numba step kernel for all cars | `pitwall_sim/race/step_kernel.py` | T-024, T-028, T-029 | Matches single-car Python result within 0.1% lap time; ≤ 20 µs per 22-car step | TRD PERFORMANCE BUDGETS | DONE |
| T-031 | AI Driver: speed tracking, Energy Modes, lines, attack/defend (no mistakes) | `pitwall_sim/driver/ai_driver.py` | T-030 | PUSH lap faster than BALANCED faster than HARVEST; HARVEST gains battery over a lap | TRD AI DRIVER | DONE |
| T-032 | Dirty air + slipstream | `pitwall_sim/car/dirty_air.py` | T-030 | Following car corner speed lower, straight speed higher vs alone (test) | TRD Dirty air | DONE |
| T-033 | Race engine loop, timing, standing start, finish | `pitwall_sim/race/engine.py` | T-031 | 22-car race completes; laps/sectors/gaps consistent; PF-04 order followed | TRD Per-step order, PF-04 | DONE |
| T-034 | Overtake model | `pitwall_sim/race/overtake.py` | T-033, T-032 | Overtakes occur; p_pass rises with Δv (test); placeholder weights flagged | TRD OVERTAKE MODEL, PF-11 | DONE |
| T-035 | Pit lane state machine | `pitwall_sim/race/pit.py` | T-033 | PF-12 transitions tested; tyre reset on exit | TRD PIT LANE, PF-12 | DONE |
| T-036 | Headless CLI + runtime test | `pitwall_sim/race/engine.py` (`__main__`) | T-034, T-035 | **MVP-05**: `test_headless_runtime` ≤ 10 s; report the measured time on the 8 GB CPU-only target machine | TRD PERFORMANCE BUDGETS | DONE |
| T-037 | AI Driver mistakes (moved into R1 by owner decision 2026-10-19; was `T-101`) | `pitwall_sim/driver/ai_driver.py` | T-033 | Mistake rate scales with tyre wear, wetness and `skill_consistency`; uses only the `mistakes` RNG stream (HR-04) | TRD AI DRIVER | DONE |
| T-038 | Race events, MVP subset: incidents, Virtual Safety Car, Safety Car (split out of R2 `T-102` by owner decision 2026-10-19; red flag, track limits, penalties and reliability DNFs stay in `T-102`) | `pitwall_sim/race/events.py` | T-037, T-034 | **MVP-11**: a mistake or overtake contact raises an incident; severity raises VSC or SC; SC bunches the field; PF-13 VSC/SC flows tested | TRD RACE EVENTS, PF-13 | IN_PROGRESS (hackathon H4, branch `hack/demo`: a crash stopped on the line raises SC, off the line VSC (`race_events.crash_on_line_p`); VSC = race pace / 1.35, SC = queue at race pace / 1.40 with 55 m gaps, no overtakes, restart after `sc_laps`, SC_IN_THIS_LAP; `demo.scripted_sc_lap`; tests/integration/test_safety_car.py. Not yet: overtake contact as a trigger, lapped-car rule) |
| T-039 | Weather model, track wetness, grip change, track evolution, noisy public forecast (moved into R1 by owner decision 2026-10-19; was `T-103`) | `pitwall_sim/race/weather.py`, `pitwall_sim/car/tyres.py` | T-033, T-023 | **MVP-12**: rain changes grip and makes INTERMEDIATE or WET faster; the crossover emerges from the `tyres.yaml` grip curves, never hard-coded; PF-14 tested; uses only the `weather` RNG stream | TRD WEATHER, PF-14 | DONE |

### Block 4: Determinism and rivals

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-040 | RNG streams, Snapshot save/restore/fork, state hash | `pitwall_sim/race/snapshot.py` | T-036 | **MVP-06**: `test_determinism`, `test_snapshot_roundtrip` pass | TRD SNAPSHOT AND DETERMINISM | DONE |
| T-041 | Rival Strategy AI (basic): stop plans, energy schedule, battle rules using Radar Estimate | `pitwall_sim/race/rival_strategy.py` | T-040, T-051 | **MVP-10**: a Rival pits and changes Energy Mode unaided; never reads other cars' Ground Truth battery (test) | TRD RIVAL STRATEGY AI, PF-10 | DONE |

### Block 5: Observation

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-050 | Public Feed: 4 Hz, noise, dropout, public timing | `pitwall_sim/observe/public_feed.py` | T-040 | Frame rate, noise σ and drop rate within 10% of config over a race (test) | TRD PUBLIC FEED | DONE |
| T-051 | Rival Battery Radar port (from existing Radar code if available, else from TRD algorithm) with incremental mode; finalise `radar.*` constants starting from the Radar spec values already in `app.yaml`, and set `radar.confidence_half_life_s` | `pitwall_sim/observe/radar/*.py`, `config/app.yaml` | T-050 | `test_radar_on_sim` reports error vs Ground Truth; uses only `radar.*` config constants; no `radar.*` key left `UNKNOWN` | TRD RIVAL BATTERY RADAR | DONE |
| T-052 | `EngineerView` builder + info barrier test | `pitwall_sim/observe/engineer_view.py` | T-051 | **MVP-08**: `test_info_barrier` passes; `lint-imports` passes | TRD DATA CONTRACTS, PF-06 | DONE |

### Block 6: Commands

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-060 | Engineer Commands schema, validator, queue with `effective_at_s` | `pitwall_sim/engineer/commands.py` | T-033 | Invalid params rejected with reason (test per type) | TRD ENGINEER COMMANDS, PF-07 | DONE |
| T-061 | Wire commands into AI Driver and pit lane | `driver/ai_driver.py`, `race/pit.py`, `race/engine.py` | T-060, T-035, T-040 | **MVP-09**: `test_each_command_effect` passes for all R1 command types | TRD ENGINEER COMMANDS | DONE |
| T-062 | SC/VSC/weather command reactions + Rival AI reactions (moved into R1 by owner decision 2026-10-19; was `T-104`) | `engineer/commands.py`, `race/rival_strategy.py`, `race/pit.py` | T-061, T-038, T-039, T-041 | **MVP-13**: `BOX` under SC costs measurably less than under green (test); Rivals react to SC/VSC and to the wet crossover; `FR-CTRL-06` satisfied | PRD FR-CTRL-06, TRD RIVAL STRATEGY AI | IN_PROGRESS (hackathon H4: MVP-13 tested (stop 1520 m lost under green, 1060 m under SC); Rivals' SC / VSC pit branch (box if the planned stop is within `rival_box_window_laps`); wet crossover not done) |

### Block 7: UI

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-070 | Main window, dock layout, sim worker thread, clock (`PAUSE`/`1x`/`4x`/`16x`), sim-behind indicator | `ui/window.py`, `ui/clock.py`, `main.py` | T-052, T-061 | App starts; clock works; UI thread never runs physics | UI_DESIGN S2, PF-05 | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-071 | Race Setup screen S1, including the "Harvest limit (MJ/lap)" field | `ui/window.py` (setup widget) | T-070 | Validation per PF-03; START disabled on invalid; harvest field pre-filled via `resolve_harvest_limit_mj` (track override → Rule Set default) and the chosen value reaches the race config | UI_DESIGN S1 | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-072 | Timing tower | `ui/timing_tower.py` | T-070 | Columns per UI_DESIGN; Our Car tinted; radar dot | UI_DESIGN Timing tower | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-073 | Track map | `ui/track_map.py` | T-070 | Static track drawn once; cars update by `setData` | UI_DESIGN Track map | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-074 | Our Car status + Rival radar panel | `ui/window.py`, `ui/radar_panel.py` | T-070 | Estimate visually distinct (hatched band, `~`); low confidence greyed | UI_DESIGN Our Car status, Rival radar | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-075 | Telemetry traces | `ui/telemetry_plot.py` | T-070 | 4 linked plots; rival battery as band; previous-lap ghost | UI_DESIGN Telemetry traces | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-076 | Command bar + keyboard shortcuts + radio log with template acks | `ui/command_bar.py`, `ui/radio_panel.py` | T-070 | Every R1 command issuable; rejection shown | UI_DESIGN Command bar, Radio | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-077 | UI performance test | `tests/ui/test_ui_fps.py` | T-072…T-076 | **MVP-07**: no frame > 100 ms over 60 s at `16x` | TRD TESTING | PARKED (sprint: S-5 replaces it until 2026-10-31) |
| T-078 | UI: flag banners (VSC, SC) and weather display (moved into R1 by owner decision 2026-10-19; split out of R2 `T-106`) | `ui/window.py`, `ui/timing_tower.py` | T-070, T-038, T-039 | Banner per UI_DESIGN UI STATES for VSC and SC; timing tower shows SC deltas; weather state and forecast shown; team colour always accompanied by driver code and team label | UI_DESIGN UI STATES | PARKED (sprint, until 2026-10-31) |

### Block 8: MVP acceptance

| ID | Task | Files | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T-080 | MVP acceptance run and report | `docs/MVP_REPORT.md` (new) | T-026, T-02B, T-02C, T-02D, T-036, T-038, T-039, T-040, T-041, T-052, T-061, T-062, T-077, T-078 | All MVP-01…MVP-13 pass; MVP-02 on the T-02D calibration (owner round 15 acceptance); report lists placeholders, unresolved values and the measured headless race time | MVP.md | PARKED (sprint, until 2026-10-31) |

## R2 — Events, weather, predictor

| ID | Task | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- |
| T-100 | Tyre temperature model (replace MVP constant) | T-080 | Temperature affects grip; calibration still passes | TRD Tyres | TODO |
| T-101 | AI Driver mistakes | — | — | TRD AI DRIVER | MOVED to R1 as `T-037` (owner decision 2026-10-19) |
| T-102 | Race events, remainder: red flag, track-limits warnings, time penalties, reliability DNFs (incidents, VSC and SC moved to R1 `T-038`) | T-080 | PF-13 red-flag flow tested; `race.track_limits_warnings_before_penalty` (3) honoured: B/W flag on the 3rd offence, 5 s penalty on the 4th and every later one, races and sprints only, qualifying deletes the lap; `reliability_dnf_p_per_race` applied per team | TRD RACE EVENTS, PF-13 | TODO |
| T-103 | Weather model + public forecast | — | — | TRD WEATHER, PF-14 | MOVED to R1 as `T-039` (owner decision 2026-10-19) |
| T-104 | SC/VSC/weather command reactions + Rival AI reactions | — | — | PRD FR-CTRL-06 | MOVED to R1 as `T-062` (owner decision 2026-10-19) |
| T-105 | Strategy Predictor + strategy panel | T-080 | Uses Radar Estimates for Rivals (barrier test); panel per UI_DESIGN | TRD STRATEGY PREDICTOR, PF-15 | TODO |
| T-106 | UI: red-flag banner, damage and penalty display (VSC/SC banners and weather display moved to R1 `T-078`) | T-102 | UI states per UI_DESIGN | UI_DESIGN UI STATES | TODO |

## R3 — Radio and debrief

| ID | Task | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- |
| T-200 | LLM worker: load the fine-tuned Gemma 3 270M GGUF, warm-up, FIFO queue | T-080, T-208 | Model loads on CPU only; UI never blocks (NFR-04) | TRD TWO-WAY RADIO | PARKED (sprint, until 2026-10-31) |
| T-201 | Radio parser: keyword pre-parser (`RAD-03`) + GBNF grammar-forced command JSON (`RAD-02`) + clarify fallback | T-200 | `test_radio_parse` accuracy reported; unambiguous phrases never reach the LLM; the model cannot emit invalid JSON; invalid → clarify | PF-08, TRD TWO-WAY RADIO | PARKED (sprint, until 2026-10-31) |
| T-202 | Template driver replies + unprompted triggers + grounding check; the model MAY only rephrase a template, never originate facts | T-200 | `test_radio_grounding` passes; every reply traceable to a template and to the passed facts | PF-09, TRD TWO-WAY RADIO | PARKED (sprint, until 2026-10-31) |
| T-203 | Radio panel text input | T-201, T-202 | UI per UI_DESIGN Radio | UI_DESIGN Radio | PARKED (sprint, until 2026-10-31) |
| T-204 | Debrief scorer | T-080 | Decision Points + best call + score per TRD | TRD DEBRIEF AND SCORING, PF-16 | PARKED (sprint, until 2026-10-31) |
| T-205 | Debrief screen S3 | T-204 | Ground Truth shown only here | UI_DESIGN S3 | PARKED (sprint, until 2026-10-31) |
| T-206 | Radio training-data generator: engineer phrase → `EngineerCommand` JSON pairs covering every `CommandType`, with paraphrases, noise, and out-of-scope phrases that must map to `clarify` | T-060 | Dataset written under `data/radio_training/`; every `CommandType` covered; held-out split exists; generation is seeded and reproducible | TRD TWO-WAY RADIO `RAD-01` | PARKED (sprint, until 2026-10-31) |
| T-207 | Fine-tune Gemma 3 270M on the generated dataset | T-206 | Held-out command-match accuracy reported; beats the keyword pre-parser alone on ambiguous phrases | TRD TWO-WAY RADIO `RAD-01` | PARKED (sprint, until 2026-10-31) |
| T-208 | Convert the fine-tuned model to GGUF (Q8_0 preferred) and verify it under `llama-cpp-python` | T-207 | `models/gemma-3-270m-it-pitwall.gguf` loads on CPU; parse latency ≤ 2 s on the target machine (NFR-05); accuracy within 2 points of the unquantised model | TRD TWO-WAY RADIO, SETUP.md section 5 | PARKED (sprint, until 2026-10-31) |

## R4 — Compare modes

| ID | Task | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- |
| T-300 | Real Race loader + cache | T-080 | Laps, telemetry, race control, weather cached to parquet | TRD REAL RACE REPLAY | PARKED (sprint, until 2026-10-31) |
| T-301 | Decision Points mode + overlay S5 | T-300, T-205 | PF-17 flow works on one 2026 race | PF-17, UI_DESIGN S4/S5 | PARKED (sprint, until 2026-10-31) |
| T-302 | Alternate Race initialiser | T-300 | Sim lap times L−5..L−1 within 2% of real | PF-18 | PARKED (sprint, until 2026-10-31) |
| T-303 | Link Decision Point → Alternate Race | T-301, T-302 | `PLAY MY VERSION` launches fork | UI_DESIGN S5 | PARKED (sprint, until 2026-10-31) |

## R5 — Full calendar

| ID | Task | Depends on | Acceptance | Refs | Status |
| --- | --- | --- | --- | --- | --- |
| T-400 | Track list from `fastf1.get_event_schedule(2026)`; build all available tracks | T-080 | Each track built or marked `UNAVAILABLE` | PF-01 | PARKED (sprint, until 2026-10-31) |
| T-401 | Zones/corners/pit config per track | T-400 | Same checks as T-011 per track | TRD CONFIG SCHEMAS | PARKED (sprint, until 2026-10-31) |
| T-402 | Calibrate every track | T-401 | NFR-06 per track; report table | TRD CALIBRATION | PARKED (sprint, until 2026-10-31) |
