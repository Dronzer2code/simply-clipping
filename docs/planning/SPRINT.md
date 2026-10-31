# SPRINT.md — Deadline sprint (owner, 2026-10-26 to 2026-10-31)

The owner's sprint texts, verbatim. Part 2 replaces the "Simply Clipping test
bench" addendum and sets the day order; where the two parts differ, part 2 wins.
Task IDs and status: `docs/planning/TASKS.md` block S.

Docs were sorted into sub-folders on 2026-10-28 (`docs/README.md` is the index).
The verbatim texts below keep their original paths: read `docs/TASKS.md` as
`docs/planning/TASKS.md`, `docs/SIMPLY_CLIPPING_BRIDGE.md` as
`docs/spec/SIMPLY_CLIPPING_BRIDGE.md`, `docs/SC_RESULTS.md` as
`docs/results/SC_RESULTS.md` and `docs/DEMO.md` as `docs/guides/DEMO.md`.

## Part 1 — OWNER DECISION — DEADLINE SPRINT (overrides TASKS.md order)

CONTEXT
I have 5 days (deadline: 2026-10-31). Goal: use this simulator as a TEST BENCH for my separate project "Simply Clipping" (my rival battery / clipping estimator, based on the Rival Battery Radar spec), and be able to SEE races running. Simply Clipping location: <SIMPLY_CLIPPING_REPO>. Its input: the Parquet contract from the Radar spec: cars.parquet (per car: time, distance, speed, throttle, brake, gear, x, y), laps.parquet, gaps.parquet. Read its loader and match its exact column names and units. If it differs from this description, follow the code and tell me.

PARKED until after 2026-10-31 (mark PARKED in TASKS.md, do not work on them):
T-02C, T-02B, T-02D follow-ups, T-038 SC/VSC (keep only what's already built), T-062, the Gemma radio (R3), debrief, compare modes, other tracks. Keep current PROVISIONAL calibration as is.
Answer Round 16 items only where it's quick (revert centre line if not done, T-027 store derived zones, wet key null, runtime test tolerance). Skip the rest.

SPRINT TASKS (new block "S" in TASKS.md, do in order, commit + push after each, all gates must pass)

S-1 Race export (Day 1)
  CLI: python -m pitwall_sim.export --track suzuka --rules 2026_pre_miami --seed 42 --scenario normal --out data/exports/<run_id>
  Writes:
  - feed/ : what a real team sees, in Simply Clipping's input format (cars.parquet, laps.parquet, gaps.parquet), from the Public Feed: 4 Hz, noise, ~5% dropped frames. Our Car excluded is NOT wanted here: export ALL 22 cars (it's a test dataset).
  - truth/ground_truth.parquet: per car, every 0.1 s: driver, time_s, distance_m, battery_mj, p_k_deploy_kw, p_harvest_kw, energy_mode, overtake_active, state_true ∈ {DEPLOY, CLIP, HARVEST, LIFT, CRUISE} (CLIP = super-clipping or battery empty at full throttle).
  - truth/events.parquet: overtakes (time, lap, attacker, defender, s_m), clip events (start/end time, car, s_m), closing-speed events (Δv > 40 km/h within 200 m, either car CLIP or LIFT).
  - run.json: seed, rule set, track, scenario, software commit hash.
  Scenarios (--scenario): normal | battles (cars start in close packs) | clip_heavy (more HARVEST/super-clip rivals) | closing_speed (forces CLIP-vs-DEPLOY pairs on straights). Implement via starting conditions and Rival Strategy settings only, no physics hacks.
  Test: the export loads with Simply Clipping's own loader without errors.

S-2 Replay viewer (Day 1, same day as S-1)
  CLI: python -m pitwall_sim.viewer --run data/exports/<run_id>
  PySide6 + pyqtgraph, reads only exported files (no sim running):
  - track map with all cars moving (team colours + driver codes)
  - timing tower (position, gap, tyre)
  - battery trace for a selected car: TRUE battery (solid) vs Radar Estimate (dashed); toggle "truth on/off"
  - play/pause, 1x/4x/16x, lap slider
  Keep it simple, reuse the UI_DESIGN colours, ≥ 10 fps at 16x.
  I must be able to run it on my laptop at the end of Day 1. Put the exact two commands in the report.

S-3 Scorer (Day 2–3)
  CLI: python -m pitwall_sim.evaluate --run data/exports/<run_id> --estimates <file>
  Estimate file contract (document in docs/SIMPLY_CLIPPING_BRIDGE.md):
    estimates.parquet: driver, time_s, energy_mj, state, confidence
    alerts.parquet (optional): time_s, type (ATTACK|DEFEND|REPASS_RISK|CLOSING_SPEED_RISK), car_a, car_b
  Metrics (printed table + evaluate_report.json):
  - energy error: MAE and 90th percentile (MJ), per car and overall, and by energy_mode
  - state accuracy: confusion matrix vs state_true; CLIP recall and precision
  - alerts: for each true overtake / closing-speed event, was there a matching alert before it, and the lead time (s); alert precision (alerts followed by a real event within 2 laps); alerts per race
  - baseline: score the built-in Radar (observe/radar) on the same run, so Simply Clipping is compared to a reference
  Also: a small adapter script example in docs/SIMPLY_CLIPPING_BRIDGE.md showing how Simply Clipping writes estimates.parquet.

S-4 Batch runner (Day 3)
  CLI: python -m pitwall_sim.export --batch 10 --scenario all --out data/exports/batch_<date>
  → 10 seeds × 4 scenarios, and evaluate over the batch with mean ± spread. Must run on my 8 GB laptop (sequential is fine; report the total time).

S-5 Live pit wall lite (Day 4)
  python main.py → setup (track Suzuka, rule set, Our Car team + driver, seed) → live race:
  track map, timing tower, Our Car status (exact battery), Rival radar panel (Radar Estimate + confidence), battery trace, clock PAUSE/1x/4x/16x, command buttons (Energy Mode, Overtake allow, Lift&Coast, BOX + compound, DEFEND, ATTACK, HOLD).
  EngineerView only (info barrier stays). A "Test mode" checkbox on the setup screen shows truth overlays (allowed only in test mode; label it clearly).
  This replaces T-070…T-077 for the sprint; full UI_DESIGN later.

S-6 Demo + hardening (Day 5)
  - A README "Quick start" section: install, export, view, evaluate, live, with exact commands.
  - Fix bugs found in Days 1–4. No new features.
  - Record nothing yourself; I will record the demo.

RULES FOR THE SPRINT
- Don't ask me about placeholders or calibration; use what exists and list it in the report.
- Ask me only if Simply Clipping's input format can't be matched, or a task can't be done in its day.
- At the end of each day, report: what I can run now (exact commands), what's next, any risk to the deadline.

## Part 2 — SPRINT CHANGE — ALERTS + "CALL THE DRIVER" (replaces the previous Simply Clipping addendum)

Simply Clipping does not exist yet. Build its alert logic INSIDE the sim as a swappable plug-in, and make alerts actionable from the pit wall.

A-1 Alert provider (plug-in)
- pitwall_sim/observe/alerts.py: protocol AlertProvider.update(view: EngineerView) -> list[Alert]. Input is EngineerView ONLY (info barrier: Our Car exact battery + Rival Radar Estimates + public timing/feed).
- Built-in provider "simply_clipping_lite" implementing the Rival Battery Radar spec rules, from Our Car's point of view:
  ATTACK: car ahead within 1.0 s AND (its Radar Estimate ≥ 0.8 MJ below our exact battery, OR it was CLIP on the same straight last lap)
  DEFEND: car behind within 0.6 s AND its Radar Estimate ≥ 0.8 MJ above our battery
  RE-PASS RISK: we passed a car in the last 15 s AND our battery < 1.0 MJ AND a straight > 600 m is ahead
  CLOSING-SPEED RISK: Δv > 40 km/h to a car within 200 m, one CLIP/LIFT and the other DEPLOY
  Same pair + type suppressed for 1 lap. Alert fields: type, rival driver_id, lap, next corner_id, evidence (our MJ, rival est. MJ, Δv, gap, last clip location), confidence (from Radar), created_t, expires_t (default 8 s or when the condition clears).
- Config: alerts.provider: simply_clipping_lite (later: external:<module.path> for the real Simply Clipping). Thresholds in app.yaml under alerts.*.

A-2 "Call the driver" options per alert
Each option sends normal Engineer Commands (validated, radio latency 1 s) plus a template radio line. No Gemma.
- ATTACK  "NOR low on charge — attack into T1"
  [1] Attack now        → ATTACK + SET_OVERTAKE_PERMISSION(allowed)
  [2] Charge, go next lap → SET_ENERGY_MODE(HARVEST) for 1 lap, then ATTACK + PUSH next lap
  [3] Ignore
- DEFEND  "HAM has the battery — defend into the chicane"
  [1] Defend into <next corner> → DEFEND(corner) + SET_ENERGY_MODE(PUSH) for 1 lap
  [2] Deploy on the straight    → SET_ENERGY_MODE(PUSH)
  [3] Let him go, save energy   → HOLD_POSITION + BALANCED
- RE-PASS RISK  "Don't pass yet — you'll be empty on the back straight"
  [1] Hold behind, harvest → HOLD_POSITION + HARVEST until battery ≥ 2.0 MJ
  [2] Go anyway            → ATTACK
- CLOSING-SPEED RISK  "Big closing speed on COL — careful into Spoon"
  [1] Warn driver (radio only)  [2] Lift → SET_LIFT_COAST(enabled, next zone)
Driver replies with a template ack ("Copy, defending T1.") in the radio panel. If a command is rejected, the reason is shown.

A-3 Pit wall UI (part of S-5 live pit wall lite)
- Alert feed panel: newest on top, colour by type (ATTACK green, DEFEND amber, RISK red), greyed when confidence < 0.5, countdown bar until expiry.
- Each alert shows its option buttons; keyboard F1/F2/F3 = option 1/2/3 on the newest alert.
- Click an alert → evidence: our battery vs rival estimate, Δv, gap, confidence, last clip location.
- Setup option "Pause on alert" (on/off), useful for testing.
- Test mode (setup checkbox, clearly labelled): also show the rival's TRUE battery next to the estimate, so I can see if the warning was right.

A-4 End-of-race call summary (small, not the full debrief)
Table of every alert: time, type, rival, option chosen (or ignored/expired), and what happened in the next 2 laps (pass made / position kept / position lost / re-passed). Totals: alerts, calls made, successful attacks, successful defends. In test mode, also: was the alert correct per Ground Truth (rival's true battery difference).

A-5 Tests
- Each alert type fires in a constructed scenario and NOT when the condition is false.
- Each option sends exactly the listed commands; a test fork shows the call changes the outcome (e.g. DEFEND option keeps position more often than ignore over 20 seeds).
- Info barrier: AlertProvider gets EngineerView only (lint-imports + test).

NEW SPRINT ORDER (deadline 2026-10-31)
Day 1: S-2 replay viewer (simple, from a headless run) so I can see a race today.
Day 2: A-1 alert provider + A-5 alert tests.
Day 3: S-5 live pit wall lite + A-3 alert panel + A-2 call options.
Day 4: A-4 call summary, the repass + closing_speed scenarios (as quick setup presets in the live sim), bug fixes.
Day 5: README quick start, polish, no new features.
S-1 export / S-3 scorer / S-4 batch: AFTER the deadline (they're for testing the real Simply Clipping later). Keep the AlertProvider interface so it plugs in.
Commit + push after each item; report each day what I can run (exact commands).

## Part 3 — OWNER ANSWERS — DAY 5 FOLLOW-UP (2026-10-26)

1. HOLD_POSITION bug: fix it (it must stop overtake attempts, per TRD). Re-run overtakes per race (3 seeds) and the ATTACK/DEFEND call_outcome numbers, and report before vs after. Accept if overtakes stay within 20–80 and both calls stay ≥ +10.
2. GAS at 34 alerts: accepted. No new threshold.
3. Step 6: yes, start now, in this order, commit + push after each:
   - S-1 export (with the Simply Clipping addendum: FastF1-like feed files incl. separate car/pos streams, dropouts, ground truth at 10 Hz incl. superclip/taper flags, car_params.json, events.parquet). Scenarios for now: normal, battles, repass, closing_speed, taper, cda_trap. The rest (high_drag_full, partial_deploy, pu_spread) only if time remains.
   - S-3 scorer: energy error, state confusion (incl. false CLIP during taper), alert recall/precision/lead time, and the built-in Radar + simply_clipping_lite alerts as the baseline (the 30–55% / 67–75% "alert right" numbers should come out of this scorer too).
   - S-4 batch (10 seeds × the scenarios above) if time remains.
   Deadline 2026-10-31; stop new work on 2026-10-30 evening and use the 31st for bug fixes only.
4. Delete the three stray empty folders (#, if, skip) in the repo root. Add a note to the README: run commands one line at a time; don't paste comment lines starting with # into the terminal.

## Part 4 — DEADLINE PLAN — DAYS 6–9 (owner, 2026-10-27; extends Part 3)

DAY 6 (2026-10-27): as already agreed: HOLD_POSITION fix → S-1 export → S-3 scorer. Commit + push after each.

DAY 7 (2026-10-28): SIMPLY CLIPPING v0 as its own package
- New top-level package `simply_clipping/` in this repo (own pyproject section or subfolder package; can move to its own repo later). It is MY project, so it must stand alone:
  - MUST NOT import pitwall_sim (new import-linter contract "simply-clipping-independent"). It only reads files.
  - Input: the Radar-spec contract (cars.parquet, laps.parquet, gaps.parquet), exactly what S-1 exports.
  - Modules per the Radar spec: loader.py (reads the contract), physics.py, energy.py, battles.py, alerts.py. Start by MOVING the logic from pitwall_sim/observe/radar and the simply_clipping_lite rules (keep behaviour identical for v0; the sim's copy can then import nothing from it, or keep its own copy, your call, but the sim must not depend on simply_clipping).
  - Output: estimates.parquet + alerts.parquet in the S-3 scorer contract.
  - CLI: python -m simply_clipping.run --input data/exports/<run_id>/feed --out data/sc_out/<run_id> [--our <driver>]
- Live pit wall plug-in: alerts.provider: external:simply_clipping.live adapter that feeds it the live Public Feed (EngineerView only) so the pit wall can run real Simply Clipping instead of the built-in rules. Setup screen dropdown: "Alert engine: built-in / Simply Clipping".
- S-4 batch: 10 seeds × scenarios (normal, battles, repass, closing_speed, taper, cda_trap). Score Simply Clipping v0 and the dumb baseline ("car ahead slower on this straight → ATTACK"). Write docs/SC_RESULTS.md with the table (mean ± spread per metric per scenario).
- Split seeds: seeds 1–5 = tune set, 6–10 = test set. Report both separately from now on.

DAY 8 (2026-10-29): SIMPLY CLIPPING v1, improved by the scores, then real data
- Improve using ONLY the tune-set scores (never Ground Truth inside Simply Clipping itself), and report test-set results. Candidate improvements, in priority order; do the ones the scores show matter most:
  1. Super-clip ≠ empty: 2026 cars super-clip on purpose with energy left. Don't re-anchor to 0 on every CLIP; anchor to 0 only if the speed loss pattern says "battery empty" (e.g. clip starts early on the straight / lasts long), otherwise treat as harvest.
  2. Regulated taper: don't classify CLIP when speed is in the 290–355 km/h taper band and the speed curve matches the taper.
  3. Partial deploy: allow DEPLOY levels between 0 and 350 kW instead of assuming full deploy for the CdA fit and integration.
  4. Confidence calibration: make "confidence" honest (alerts at 0.8 confidence should be right ~80% of the time on the tune set).
  5. ICE power per PU maker + fuel mass decreasing over the race.
- Keep v0 frozen for comparison (simply_clipping version flag or tag), and add a v0-vs-v1 column to docs/SC_RESULTS.md (test set).
- Real data check: fetch the real 2026 Japanese GP race from OpenF1 (car_data + location + laps; reuse pitwall_sim's OpenF1 client code by copying the minimal fetch logic into simply_clipping/real_data.py: independence rule still applies), convert to the input contract, run v1, and check:
  a) Norris clips after passing Hamilton → RE-PASS RISK fires before Hamilton re-passes (find the real lap/time from the data first);
  b) Lap 22: Bearman closing on Colapinto before Spoon → CLOSING-SPEED RISK fires before the crash;
  Report alert time, lead time in seconds, and the evidence. If the real data doesn't show the incident clearly, say so; don't force it.

DAY 9 (2026-10-30): DEMO PACKAGE (last day of new work)
- docs/DEMO.md: a 3-minute demo script I can follow while screen recording:
  (1) problem in one line, (2) live pit wall with Simply Clipping as alert engine, Test mode on, an ATTACK and a DEFEND alert answered with F1/F2/F3, (3) call summary, (4) results table v0 vs v1 vs baseline, (5) real Japanese GP incident check.
  Include exact setup choices (scenario, Our Car, seed) that reliably produce each moment within the first few laps.
- README: "Results" section with the test-set table and the real-race findings.
- Full gate run, timing tests best of 3, fix bugs.
2026-10-31: bug fixes only, no new features.

RULES
- Commit + push after each item; daily report: what I can run (exact commands), numbers, risks.
- Ask me only if blocked or if something can't fit its day; then propose what to cut.
- Priority if time runs short: cut Day 8 improvements 3–5 first, then the real-data check, never the demo package.

## Part 5 — SPRINT ADDENDUM — SIMPLY CLIPPING TEST BENCH (verbatim; the spec Part 3 item 3 refers to)

Sent before Part 2, which set it aside until after the deadline; Part 3 (2026-10-26) brought S-1 / S-3 / S-4 back with it.

SPRINT ADDENDUM — "SIMPLY CLIPPING" TEST BENCH REQUIREMENTS (refines S-1, S-3, S-4)

WHAT SIMPLY CLIPPING IS (restated, self-contained)
"Simply Clipping" = my Rival Battery Radar project (working name WeAreChecking). It replays a 2026 race from FastF1 data and estimates every car's hidden battery energy:
- data/loader.py → cars.parquet (per car: time, distance, speed, throttle, brake, gear, x, y), laps.parquet, gaps.parquet
- engine/physics.py: resample to 10 Hz, Savitzky-Golay (7, 2), accel; P_wheel = m·a·v + ½ρCdA·v³ + Crr·m·g·v; P_elec = P_wheel/η − P_ICE
- CdA fitted per car per aero mode from full-throttle samples in the first 2 s of each straight (assumes full 350 kW deploy there)
- engine/energy.py: states DEPLOY (thr ≥ 95%, P_elec > 150 kW), CLIP (thr ≥ 95%, P_elec < 50 kW, speed flat/falling), HARVEST (brake), LIFT (thr < 20%, no brake), CRUISE; energy integrated and clamped 0–4 MJ; re-anchored to ~0 at each CLIP on a long straight; confidence drops with time since anchor and missing samples
- constants: m 800 kg (fuel ignored), P_ICE 400 kW, P_elec max 350 kW, E_max 4 MJ, η 0.92, ρ 1.18, Crr 0.012
- engine/battles.py: battle = within 1.0 s
- engine/alerts.py: ATTACK (rival ≥ 0.8 MJ below us, or clipped on same straight last lap) | DEFEND (car behind ≥ 0.8 MJ above us, gap < 0.6 s) | RE-PASS RISK (just passed, our energy < 1.0 MJ, straight > 600 m ahead) | CLOSING-SPEED RISK (Δv > 40 km/h within 200 m, one car CLIP/LIFT, other DEPLOY); repeats suppressed 1 lap
- demo incidents: Japan 2026: Norris clips after passing Hamilton → RE-PASS RISK before Hamilton re-passes; lap 22: Bearman closing ~45–50 km/h on Colapinto before Spoon → CLOSING-SPEED RISK
If the Simply Clipping code is available (<SIMPLY_CLIPPING_REPO>), its loader/column names override this description. If not, export exactly this contract.

S-1 EXPORT MUST LOOK LIKE REAL FASTF1 DATA
- Two separate raw streams per car, like FastF1: car_data (Speed km/h, RPM, nGear, Throttle 0–100, Brake bool) and pos_data (X, Y, Z in FastF1 units = decimetres), each ~3.7–4 Hz with independent timestamps and ±30 ms jitter, then cars.parquet built the same way Simply Clipping's loader builds it (time, distance, speed, throttle, brake, gear, x, y).
- Dropouts: random single missing frames (~5%) AND occasional gaps of 0.5–2 s (configurable), because Simply Clipping drops samples with gaps > 0.5 s.
- Throttle quantised to integers; brake boolean; speed noise σ 0.5 km/h; position noise σ 1 m.
- laps.parquet with FastF1-style columns: Driver, DriverNumber, Team, LapNumber, LapTime, Sector1Time/2/3, LapStartTime, Position, Compound, TyreLife, PitInTime, PitOutTime.
- gaps.parquet: per car per lap at the timing line: GapToLeader, IntervalToPositionAhead.
- Driver codes/numbers from config/grid/real_2026.yaml, so names look like the real race (NOR, HAM, BEA, COL…).
- No DRS column (doesn't exist in 2026).

S-1 GROUND TRUTH MUST LET ME CHECK EVERY ASSUMPTION
truth/ground_truth.parquet at 10 Hz per car: time_s, distance_m, battery_mj, p_ice_kw, p_k_deploy_kw, p_harvest_kw, superclip (bool), taper_active (bool, MGU-K limited by speed taper), zone_cap_kw, overtake_active, energy_mode, aero_mode, cda_true, mass_kg (incl. fuel), state_true (DEPLOY|CLIP|HARVEST|LIFT|CRUISE using Simply Clipping's definitions applied to TRUE power).
truth/car_params.json: per car the true CdA per aero mode, ICE power (with pu_power_scale), η, mass at start, so CdA-fit and P_ICE errors can be measured directly.

S-1 SCENARIOS AIMED AT SIMPLY CLIPPING'S WEAK SPOTS (--scenario)
- normal: plain race.
- repass: rebuild the Norris/Hamilton case: car A passes car B on a straight with low battery (< 1.0 MJ) and a > 600 m straight ahead; B (higher battery) re-passes within 1 lap. Log the true pass, the true re-pass and the moment RE-PASS RISK should have been possible.
- closing_speed: rebuild the Bearman/Colapinto case: car ahead super-clips/LIFTs approaching Spoon while the car behind deploys, true Δv 45–50 km/h within 200 m. Log the event.
- cda_trap: some cars start straights already empty (CdA-fit assumption broken). Expect biased CdA; measure it.
- high_drag_full: a car with high CdA and a full battery: must NOT be classified CLIP.
- taper: long straights where MGU-K is limited by the 290–355 km/h taper (and Overtake 337–355): regulated taper must not be read as CLIP.
- partial_deploy: BALANCED drivers deploying 150–250 kW (not full 350) on straights.
- pu_spread: real per-maker ICE differences (pu_power_scale) + fuel burn from full tank, while Simply Clipping assumes 400 kW / 800 kg.
- battles: packs within 1 s for alert volume and precision.
- all: run every scenario.
Use starting conditions, Rival Strategy settings and Energy Modes only, no physics hacks. Each scenario writes the target events it was designed to produce to truth/events.parquet with a `scenario_target` flag, and the report says whether the sim actually produced them.

S-3 SCORER MUST MATCH SIMPLY CLIPPING'S OUTPUTS
estimates.parquet: driver, time_s, energy_mj, state, confidence (+ optional cda_fit per car in cda_fit.json)
alerts.parquet: time_s, lap, type (ATTACK|DEFEND|REPASS_RISK|CLOSING_SPEED_RISK), car_a, car_b, confidence
Metrics:
- energy: MAE, p90, error vs time-since-last-anchor (shows drift), split by scenario and energy_mode; separately for samples with confidence ≥ 0.5 vs < 0.5 (is confidence honest?)
- state: confusion matrix vs state_true; CLIP precision/recall; false CLIPs during taper_active and on high_drag_full cars (should be 0)
- CdA fit: fitted vs cda_true per car (% error), and the cda_trap bias
- alerts, per type: recall on true events, lead time in seconds (median, and share with ≥ 5 s lead; under 1 s counts as useless), precision (alert followed by a real matching event within 2 laps), alerts per race (flag if > 100)
- repass + closing_speed scenarios: pass/fail exactly like Simply Clipping's tests/test_incidents.py ("alert fires before the event, for the right pair")
- baseline comparison: (1) the sim's built-in Radar, (2) a dumb rule "car ahead slower on this straight → ATTACK". Simply Clipping should beat the dumb rule; print both.
- held-out check: --tune-seeds and --test-seeds options, so thresholds tuned on some seeds are reported on unseen seeds.

S-4 BATCH
10 seeds × every scenario on my 8 GB laptop, sequential, total time reported; evaluate prints mean ± spread per metric per scenario, and writes evaluate_batch_report.json + a short markdown summary I can paste into Simply Clipping's README.

S-2 VIEWER ADDITION
For a selected car: true battery (solid), Simply Clipping estimate (dashed, if an estimates file is given with --estimates) and built-in Radar (dotted); state strip coloured by state_true vs estimated state; alert markers on the timeline with the matching true event. This is how I'll visually check failures.
