# PROJECT_STATUS.md — what is built, what is on its way, what needs changes

## PURPOSE

A status report written after setting up and running the project from a clean
environment on 2026-10-28 (after sprint day 9). It records which work is done,
which work is still to come, and which tasks need changes because of what the run
showed. Task IDs refer to `docs/planning/TASKS.md`, MVP IDs to `docs/spec/MVP.md`. It does not
change any task status or owner decision; those stay in `docs/planning/TASKS.md` and
`docs/status/SESSION_CONTEXT.md`.

## HOW IT WAS RUN

| Item | Value |
| --- | --- |
| Machine | Windows 11, CPU only |
| Python | 3.13.12, installed with `uv python install 3.13` (the machine had only 3.12 and 3.14; `pyproject.toml` needs `>=3.13,<3.14`) |
| Environment | `uv venv --python 3.13 .venv`, then `pip install -e ".[dev]"` (75 packages, pinned versions installed cleanly) |
| Code changes needed to run | None |

## RUN RESULTS

| Check | Command | Result |
| --- | --- | --- |
| Lint | `ruff check .` | Pass |
| Format | `ruff format --check .` | Pass (153 files) |
| Types | `mypy pitwall_sim` | Pass (98 files, strict) |
| Architecture contracts | `lint-imports` | 4 kept, 0 broken (headless core, UI info barrier, alert providers, Radar sees only the Public Feed) |
| Tests | `pytest -q` | 458 passed, 1 skipped (`test_calibrated_lap_is_plausible`, skipped while the calibration is PROVISIONAL), 3 min 50 s |
| Headless race | `python -m pitwall_sim.race.engine --headless --track suzuka --rules 2026_post_miami --seed 42` | 7.05 s with a warm Numba cache (budget 10 s, MVP-05). First run 38.9 s (JIT compile, with pytest running at the same time). **All 22 cars DNF "out of fuel" at laps 41-46** (see NEEDS CHANGES 1) |
| Alerts | `python -m pitwall_sim.observe.alerts_check --seed 42 --our GAS` | 42 alerts (ATTACK 31, DEFEND 8, RE-PASS RISK 3, CLOSING 0) |
| Test bench | `python -m pitwall_sim.bench --sc-module docs.examples.hello_clipping --scenario normal --seeds 6` | Export, plug-in, scorer and report ran; `data/sc_out/hello_clipping/BENCH_REPORT.md` |
| Desktop app | `python main.py` path (setup → live session → pit wall), 2 laps, 16x, Test mode, driven by a script | Reached the flag, call summary opened, 0 exceptions, slowest frame 32 ms (MVP-07 limit 100 ms); all panels render on the native Windows platform |

## WORK DONE

### R1 core (MVP)

| Block | Tasks | What works |
| --- | --- | --- |
| 0 Foundation | T-001 – T-005 | Package layout, pinned dependencies, config models + loader (flags `UNRESOLVED` / `UNKNOWN`), both Rule Sets, real and fictional grids, team performance, tyres, `app.yaml` |
| 1 Track | T-010, T-011, T-027, T-029 | Suzuka built from OpenF1 (5 pooled laps), zones, corners, pit, derived acceleration zones (stored, not applied) |
| 2 Single-car physics | T-020 – T-026, T-028, T-02A | State + Numba mirror, powertrain (tapers, zone caps, boost, Overtake mode), battery (super-clip, lap limits), aero, fuel, tyres, speed profile, lap sim, calibration CLI, deploy policy; calibration DONE **provisional** |
| 3 Race | T-030 – T-037, T-039 | Numba step kernel, AI Driver with Energy Modes, attack/defend and mistakes, dirty air + slipstream, race engine, overtakes, pit lane, headless CLI, weather with wet tyres |
| 4 Determinism, rivals | T-040, T-041 | Named RNG streams, snapshot / fork / state hash, Rival Strategy AI |
| 5 Observation | T-050 – T-052 | 4 Hz Public Feed, Rival Battery Radar, `EngineerView` + info barrier |
| 6 Commands | T-060, T-061 | Command schema, validator, queue; every R1 command changes Our Car |

### Deadline sprint (until 2026-10-31)

| Task | What works |
| --- | --- |
| S-2 | Replay viewer: `python -m pitwall_sim.viewer --seed 42` |
| A-1, A-5 | Alert provider plug-in (`simply_clipping_lite`), alert tests, paired-fork call outcome check |
| S-5, A-3, A-2 | Live pit wall lite (`python main.py`), alert feed panel, call the driver (F1/F2/F3) |
| A-4, A-6 | End-of-race call summary; Re-pass and Closing-speed presets |
| S-6 | README quick start |
| S-1, S-3, S-4 | Race export, scorer, batch runner, `docs/results/SC_RESULTS.md` baseline table |
| BENCH | Test bench for the owner's estimator + `docs/examples/hello_clipping.py` |
| SC-0 | Archived (branch `archive/sc-v0`); the owner builds Simply Clipping |

## ON ITS WAY (NOT DONE)

Per runtime flow (PF-01…PF-18), with the step that is missing in each:
`docs/spec/PROCESS_FLOW.md` IMPLEMENTATION STATUS.

### R1 work still needed for MVP sign-off

| Priority | Task | State | What is missing |
| --- | --- | --- | --- |
| 1 | T-02B race fuel calibration | PARKED | `fuel_start_kg` 70 kg placeholder: a full race cannot be finished at the track default (NEEDS CHANGES 1) |
| 2 | T-038 incidents, VSC, Safety Car | PARKED | `race/events.py` is a one-line stub; `events.incident_rate_per_lap` and `events.sc_share` are `UNKNOWN`. Blocks MVP-11 |
| 3 | T-062 SC / VSC / weather reactions | PARKED | Depends on T-038. Blocks MVP-13 |
| 4 | T-02C race calibration | PARKED | Race pace, part-throttle harvest, tyre wear, overtake weights against the real Suzuka race (weights are `GAMEPLAY-TUNED (sprint)`) |
| 5 | T-02D geometry + constrained fit | PARKED | Final MVP-02 calibration: plausibility limits not met, speed RMSE 21-25 km/h (target ≤ 15) |
| 6 | T-070 – T-077 full pit wall UI | PARKED (S-5 replaces it) | `ui/window.py`, `clock.py`, `timing_tower.py`, `track_map.py`, `radar_panel.py`, `telemetry_plot.py`, `command_bar.py`, `radio_panel.py` are one-line stubs; the working UI is `ui/pitwall_lite.py` |
| 7 | T-078 flag banners + weather display | PARKED | Needs T-038; no VSC / SC banner, no weather or forecast shown in the live UI |
| 8 | T-080 MVP acceptance report | PARKED | Needs all of the above; `docs/MVP_REPORT.md` does not exist yet |

### MVP acceptance today

| ID | State |
| --- | --- |
| MVP-01 track model | Pass |
| MVP-02 calibration | Provisional (T-02A fit 2); final on T-02D |
| MVP-03 battery window, MVP-04 Rule Set limits | Pass (tests) |
| MVP-05 headless ≤ 10 s | Pass (7.05 s warm) |
| MVP-06 determinism | Pass (tests) |
| MVP-07 UI ≥ 10 fps at 16x | Pass on the lite UI (slowest frame 32 ms) |
| MVP-08 info barrier | Pass (lint-imports + test) |
| MVP-09 command effects, MVP-10 rival pits + mode change | Pass (tests) |
| MVP-11 incidents, VSC, SC | **Fail** (T-038 not built) |
| MVP-12 rain + wet crossover | Pass (T-039) |
| MVP-13 BOX under SC cheaper | **Fail** (T-062 not built) |

### Later releases (all stubs or not started)

| Release | Tasks | Code today |
| --- | --- | --- |
| R2 | T-100 tyre temperature, T-102 red flag / track limits / penalties / reliability DNFs, T-105 Strategy Predictor, T-106 UI states | `engineer/predictor.py` and `ui/strategy_panel.py` are stubs |
| R3 | T-200 – T-208 Gemma radio (training data, fine-tune, GGUF, parser, replies), T-204 / T-205 debrief | `radio/*.py`, `debrief/*.py`, `ui/debrief_view.py` are one-line stubs; no model file |
| R4 | T-300 – T-303 real race loader, Decision Points, Alternate Race | `replay/*.py` are one-line stubs |
| R5 | T-400 – T-402 the rest of the 2026 calendar | Only Suzuka exists |

## NEEDS CHANGES (FOUND BY RUNNING)

Items marked *owner* touch calibration, placeholders or Rule Set decisions, which
`CLAUDE.md` reserves for the owner; they are reported, not changed.

| # | Task | Seen when running | Suggested change | Decides |
| --- | --- | --- | --- | --- |
| 1 | T-02B | The headless CLI, the replay viewer, `alerts_check` and `call_outcome` use the track default `fuel_start_kg` 70 kg: every car runs out of fuel at laps 41-46 of 53. The live app (`live/session.py:48`) and the export / bench (`export/__init__.py:116`) override it with a hard-coded 110 kg, so two fuel loads are in use and the 110 kg cars race heavier than real ones (the live run used ~1.7 kg/lap) | Calibrate `fuel_start_kg` per T-02B (finish with 0.5-2 kg), then remove the two 110 kg overrides so every entry point uses the track value | owner |
| 2 | T-038 | `config/tracks/suzuka.yaml` keeps `events.incident_rate_per_lap` and `events.sc_share` `UNKNOWN`; `race/events.py` is empty, so mistakes never cause a SC / VSC | Build T-038; the two values need an owner source or a `# PLACEHOLDER: calibrate` value | owner (values), agent (code) |
| 3 | T-02C / T-011 | Every run logs "5 config keys are still UNRESOLVED or UNKNOWN": `pit.lane_loss_s`, `abrasiveness` (the kernel uses a neutral 1.0), `zone_difficulty.OT1` (the default 2.0 is used), and the two event keys above | Resolve in T-02C (abrasiveness, zone difficulty) and T-02B / T-011 (lane loss) | owner |
| 4 | A-1 (alert volume) | Seed 42, Our Car GAS: 42 alerts per race, 31 ATTACK (27 on the observed-clip branch). Day 5 recorded 34 against a target ≤ 30; the day 7 change (rivals see Our Car) and later work raised it | Re-check the target with the owner; if it still stands, tighten the observed-clip ATTACK branch (the scorer shows ATTACK precision 12 %) | owner |
| 5 | T-02D | `test_calibrated_lap_is_plausible` is skipped while `performance.yaml` is CALIBRATED-PROVISIONAL, so plausibility (lateral ≤ 5.5 g, braking ≤ 6.0 g) is not checked by any test today | Nothing until T-02D; then the test runs by itself | — |
| 6 | T-036 (MVP-05) | First headless run after install: 38.9 s (setup 16.8 s, Numba compile); warm: 7.05 s | Measure MVP-05 on a warm cache and say so in the T-080 report; optionally pre-compile at install (`python -m pitwall_sim.race.engine --headless ... --laps 1`) | agent |
| 7 | Docs (SETUP.md) | Python 3.13 was not on the machine and `py -3.13` from the README fails; `uv python install 3.13` + `uv venv --python 3.13 .venv` worked. SETUP.md section 8 says `lint-imports # 2 contracts kept` (now 4) and section 6 says `mypy pitwall_sim --exclude pitwall_sim/ui` (the whole package passes; README says `mypy pitwall_sim`) | Add the `uv` route to SETUP.md / README; update the contract count and the mypy command | agent |
| 8 | Tooling | Under `QT_QPA_PLATFORM=offscreen` (SETUP.md troubleshooting) every label renders as empty boxes (no font database); the native platform renders correctly | Note it in SETUP.md troubleshooting; take screenshots on the native platform | agent |
| 9 | graphify-out | Built from commit `50af763`, 23 commits behind `HEAD` (`e426bb3`) | `graphify update .` | agent |
| 10 | Radar (T-051) | Known: after the first anchor MAE ≈ 1.44 MJ, bias −1.41 MJ; bench seed 6 built-in CLIP precision 4 % | Not tuned (owner rule: never tune the Radar on Ground Truth); revisit with the owner's Simply Clipping | owner |
| 11 | Overtake model (T-034) | HOLD_POSITION: variant B on main (only the engineer's HOLD stops Our Car's attempts; a rival's HOLD from the Rival Strategy AI only means "not attacking"). `TRD.md:487` defines HOLD_POSITION as "No overtake attempts" and `TRD.md:685` has rivals choose HOLD, so the TRD reads as if rivals' HOLD stops attempts too | Note variant B in TRD OVERTAKE MODEL / RIVAL STRATEGY AI, or switch to variant A (branch `wip/hold-position`), when the owner decides | owner |
| 12 | Docs (`results/CALIBRATION_NOTES.md`) | `python -m pitwall_sim.calibration.fit` rewrites the whole file (`args.notes.write_text`), but the file also holds hand-written sections (owner rounds 13-15, T-02D); a re-run would lose them | Make `fit` write only its generated part (e.g. between markers) or write to a separate file, before the next calibration run (T-02D) | agent |
