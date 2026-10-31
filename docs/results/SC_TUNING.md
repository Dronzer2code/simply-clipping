# SC_TUNING.md — Simply Clipping tuning log

Every change to `simply_clipping/config.yaml` that was chosen by measuring, with
the reason. Tuned on the TUNE SET only (seeds 1-5, `data/exports/batch`); the
test set (seeds 6-10) is never used to choose a value (spec SC-R03). Numbers
come from `python -m pitwall_sim.bench --sc-module simply_clipping ... --seeds 1-5`.

## SC-1 — CdA fit (2026-10-30)

Objective: CdA error vs `car_params.json` per car (scorer `cda`), tune runs.

| Change | Before → after | Why (tune-set evidence) |
| --- | --- | --- |
| `car.mass_kg` 800 → 768 + fuel | — | Lesson L-d: the RADAR 800 kg averaged fuel in. 768 kg = RULES minimum mass; fuel is added per lap. |
| `fuel.start_kg` null → 90, `burn_kg_per_lap` null → 1.7 | straight bias −10 % → −3 % | Mass scales the fitted slope (CdA ∝ assumed mass). Tried 90 / 110 / 130 kg on normal_s1, normal_s3, cda_trap_s2, taper_s4: mean \|err\| straight 6.6 / 6.8 / 7.2 %, corner 3.7 / 4.2 / 4.8 %. Burn = start over 53 laps. |
| `cda_fit.v_min_kmh` 150 → straight 230, corner 150 | straight \|err\| 12.6 % → 6.8 % | Straight-mode runs that start slower than ~230 km/h are not power-limited (zone entry, traction) and read as too little drag (bias −10 % at 200 km/h). Corner mode got worse when raised (fewer runs): kept 150. 250 km/h: too few runs (\|err\| 13.6 %). |
| `cda_fit.resid_floor_kw` 20, `cda_bounds_m2` 0.2–3.0 (new) | worst runs: straight \|err\| 3.4 % (was up to −174 % on single cars) | One near-perfect run got most of a car's weight (weight = information / residual variance) and its negative slope won the median (LEC normal_s3: 64 % of the weight on one run). A 20 kW noise floor caps a run's weight; slopes outside 0.2–3.0 m² are not drag. 10 / 20 / 40 kW: same result. |
| `cda_fit.prior_m2` 0.7 / 1.6 → 0.77 / 1.62 | — | Median of the 330 fits per mode on the tune set (used before a car has 3 runs). |

Result, tune set (15 runs): mean \|err\| straight 4.0 % (cda_trap), 3.5 % (normal), 2.6 % (taper); corner 3.9 / 4.4 / 2.7 %; trap cars' straight bias +3.9 %. Remaining bias +1-3 %: the RADAR rolling resistance (Crr 0.012, no downforce term) and slipstream in battles.

## SC-2 — energy estimate (2026-10-30)

Objective: energy MAE / bias (overall and by Energy Mode), CLIP precision and
false CLIP in the taper, on tune runs (seed 1 diagnostics; grids on seeds 2-3 x
all six scenarios). Diagnostics compared estimated and true deploy / harvest per
true state on tune runs only.

| Change | Tune-set evidence | Why |
| --- | --- | --- |
| Harvest only from braking, lifting and super-clips (not any negative `P_elec`) | seed 1, 6 scenarios: MAE 0.79 → 0.52 MJ | Estimated harvest was 3.5x the true one: full-throttle corners read −390 kW (cornering losses the model leaves out) and were booked as super-clip harvest; part throttle booked 205 MJ/race against 20 true. |
| `energy.brake_share` 0.5 → 0.55 | grid (seeds 2-3): 0.4 / 0.5 / 0.55 / 0.6 / 0.7 → MAE 0.89 / 0.63 / 0.54 / 0.56 / 0.58 | True braking harvest is ~0.4-0.5 of the braking power below 200 km/h and at the 350 kW cap above. |
| `energy.lift_harvest_kw` 80 → 140 | 40 / 80 / 120 / 140 / 160 → MAE 0.70 / 0.63 / 0.57 / 0.54 / 0.55 | True lift harvest averages ~90 kW with the battery not full; higher values also offset HARVEST-mode underestimates. |
| `deploy.*` (observed band 200-290 km/h, corner rule) | seed 1: MAE 0.52 → 0.24 (normal) | PUSH cars deploy the 250 kW corner cap in slow corners, invisible in the speed trace (grip-limited). A fast full-throttle corner separates deployers (P_elec median +226 kW) from not (+7 ± 40): `corner_seen_kw` 120. Booking the cap on every corner for a "PUSH" car first gave MAE 2.2 (even PUSH cars deploy on only some corner points): expected value instead. |
| `deploy.cruise_scale` 0.6 → 0.3 | 0.0 / 0.3 / 0.5 / 0.6 / 1.0 → MAE 0.57 / 0.54 / 0.55 / 0.63 / 0.67 | Part-throttle deploy read from P_elec runs high. |
| Steady full throttle (whole filter window, no brake in it) for states and flows | false CLIP in taper 5.0 % → 0.6 %; CLIP precision 58 %, recall 50 % → 20 % | The smoothed acceleration at the last points before braking mixes in the braking: false CLIPs and false super-clip harvest at every straight's end. The lost recall is the true CLIP just before braking; relaxing the rule (full throttle at the point, no brake in the window) gave recall 22 %, precision 51 %, taper false CLIP 1.4-2.7 %: worse on all three, reverted. |
| `states.taper_margin_kw` 60 → 120 | taper false CLIP 0.82 → 0.60 %, MAE equal | Near 350 km/h the taper allows ~30 kW: speed noise put P_elec below the CLIP line. |
| Confidence: table of hit rate per estimate band x time since anchor | ECE (raw half-life score) 0.57 | The half-life score ran backwards: estimates are worst in the first 2 min (hit 33 %) and best later (66-72 %); at a clamp (empty / full) or right after an EMPTY anchor 83-87 %, mid-range early ~20 %. A monotone calibration of the half-life score collapses to a constant 0.63. The table (`confidence.table`) is the measured hit rate per cell (cells with < 200 points use the band's rate). |

Not changed (no gain on the grid): `states.taper_margin_kw` above 120, `energy.superclip_min_kmh` 200 vs 250.

### SC-2 result

Tune set (seeds 1-5, 30 races): confidence honest, ECE 0.010 pooled (stated 0.84 → hit 0.84, 0.65 → 0.66, 0.19 → 0.19).

Test set, run once (seeds 6-10, 30 races), built-in → Simply Clipping:

| Scenario | Energy MAE MJ | p90 MJ | Within 0.5 MJ | Confidence ECE | CLIP precision | CLIP recall | False CLIP in taper |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal | 0.92 → 0.36 | 1.87 → 1.02 | 34 → 73 % | 28 → 7 % | 4 → 65 % | 36 → 20 % | 0 → 0 % |
| battles | 0.84 → 0.52 | 1.75 → 1.32 | 37 → 60 % | 30 → 8 % | 6 → 66 % | 41 → 27 % | 1 → 1 % |
| cda_trap | 0.85 → 0.60 | 1.90 → 1.65 | 41 → 61 % | 34 → 4 % | 4 → 53 % | 36 → 21 % | 1 → 2 % |
| closing_speed | 0.95 → 0.41 | 1.96 → 1.13 | 34 → 71 % | 28 → 6 % | 4 → 65 % | 35 → 20 % | 0 → 0 % |
| repass | 0.97 → 0.39 | 1.98 → 1.08 | 33 → 72 % | 27 → 6 % | 4 → 65 % | 35 → 19 % | 0 → 0 % |
| taper | 1.28 → 0.88 | 2.47 → 1.85 | 20 → 38 % | 18 → 10 % | 4 → 53 % | 37 → 19 % | 0 → 0 % |

Pooled test-set confidence: ECE 0.009 (stated 0.84 → hit 0.84). Missed: CLIP recall (the true CLIPs just before braking, see above) and false CLIP in taper 2 % in cda_trap (target ≤ 1 %).

## SC-3 — battles, alerts, live plug-in (2026-10-30)

Objective: alert recall / precision / right per truth, alerts per race, the two
incident checks; tune set only (an alert grid re-running the rules on cached
estimates of the 30 tune races). Rule thresholds of the owner's SC-3 spec kept
as given (0.8 MJ, 1.0 s / 0.6 s, 0.4 confidence, 15 s, 1.0 MJ, 600 m, 40 km/h,
200 m, 1 lap); threshold tuning is SC-4.

| Change | Tune-set evidence | Why |
| --- | --- | --- |
| DEFEND own battery: need = straight length at `straight_speed_kmh` 270 (not our current speed) | own-battery DEFENDs 32.6 / race, right 36 %: median need 6.5 MJ (more than a full battery) | Divided by our speed in the corner before the straight, every battery looked short. |
| `need_share` 1.0 → 0.5 | alerts per race (battles) 143 → 114; DEFEND right normal 70 → 84 %, cda_trap 45 → 70 %; DEFEND recall equal or slightly lower | "Too low for the straight" = below half of full deploy over it. 0.3: right 87 %, recall normal 83 → 67 %. |
| CLOSING-SPEED only with Our Car on a straight (`closing_on_straight`) | CLOSING 30 / race → ~6; recall equal | Corner entries: the car ahead lifts while we are still on power. |
| RE-PASS only for the passed car still within the battle range (1.0 s) | REPASS 14.3 / race → ~3 | A car passed 15 s ago and far behind cannot re-pass. |
| Not changed: `closing_counts_no_deploy` (slow car empty but accelerating) | +10-20 alerts / race, incident still 0 % | — |
| Not adopted (owner rule): relaxed CLOSING states | recall 26-73 %, 125-210 alerts / race, incident still 0 % | Spec O-3. |

Live: rival frames reach the trackers once per `feed_batch_s` (1 s of race), ticks
are evaluated `latency_s` (2 s) behind: 300 s of race in 10 s wall (30x; the pit
wall needs 16x). Unbatched: 14x.

### SC-3 result (test set, run once; built-in → Simply Clipping)

| Scenario | ATTACK precision | ATTACK right | DEFEND recall | DEFEND right | REPASS recall | Alerts / race | Incident |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal | 8 → 4 % | 46 → 67 % | 39 → 100 % | 84 → 86 % | - | 38 → 44 | - |
| battles | 36 → 15 % | 46 → 72 % | 37 → 66 % | 43 → 65 % | 25 → 8 % | 64 → 101 | - |
| cda_trap | 11 → 8 % | 71 → 97 % | 27 → 70 % | 20 → 66 % | - | 30 → 64 | - |
| closing_speed | 10 → 12 % | 14 → 19 % | 42 → 91 % | 87 → 94 % | 50 → 50 % | 37 → 54 | closing 0 → 0 % |
| repass | 26 → 33 % | 29 → 55 % | 60 → 74 % | 65 → 72 % | 36 → 43 % | 55 → 56 | repass 33 → 67 % |
| taper | 10 → 10 % | 38 → 50 % | 25 → 50 % | 47 → 60 % | - | 31 → 57 | - |

ATTACK fires less often than the built-in (normal recall 75 → 12 %) but is right
per Ground Truth more often in every scenario; its precision in a normal race is
below the built-in (target for SC-4). Closing incident: spec O-3.

## SC-4 — threshold tuning, final config (2026-10-30)

Alert grid on the 30 tune races (estimates cached, rules re-run per variant).
The owner allowed tuning thresholds in SC-4 (SC-3 kept the owner's values).

| Variant (tune set) | Normal: ATTACK precision / right | Battles: alerts per race | DEFEND precision (normal / battles / repass) | Repass incident |
| --- | --- | --- | --- | --- |
| SC-3 config | 4 % / 65 % | 114 | 5 / 17 / 13 % | 50 % |
| attack margin 1.2 MJ | 13 % / 40 % | 112 | 5 / 17 / 13 % | 50 % |
| attack margin 1.6 MJ | 10 % / 0 % | 111 | 5 / 17 / 13 % | 50 % |
| attack 1.2 + attack gap 0.8 s | 13 % / 45 % | 111 | 5 / 17 / 13 % | 50 % (repass ATTACK recall 33 → 3 %) |
| attack 1.2 + defend margin 1.2 MJ | 13 % / 40 % | 100 | 6 / 19 / 15 % | 50 % |
| attack 1.2 + need share 0.4 | 13 % / 40 % | 105 | 7 / 18 / 14 % | 50 % |
| **attack 1.2 + defend 1.2 + need share 0.4 (final)** | **13 % / 40 %** | **85** | **9 / 24 / 18 %** | **50 %** |

Final: `alerts.attack_margin_mj` 0.8 → 1.2, `alerts.defend_margin_mj` 0.8 → 1.2,
`alerts.need_share` 0.5 → 0.4. Energy, CLIP and confidence: no change from SC-2
(a further energy grid showed a flat optimum). The test set was then run once
with this config (`docs/results/SC_RESULTS.md`).

## SC-6 — radio line, demo; post-v1 fix (2026-10-30)

- Radio line per alert (template, ≤ 12 words, evidence only); no tuning.
- Fix found while rehearsing the demo: CLOSING-SPEED alerts with 133-154 km/h
  closing speeds were cars in the pit lane (80 km/h, beside the main straight).
  `alerts.closing_min_speed_kmh` 120: a slower car below it is not on track.
  Made after the one-off test run: the v1 numbers in SC_RESULTS.md are without
  this fix (it can only remove false CLOSING-SPEED alerts).
