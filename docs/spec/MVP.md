# MVP.md — Pit Wall Race Simulator (2026 Regulations)

## PURPOSE

This document defines the minimum version of `pitwall_sim` that must be built first, and the order of releases after it.
Feature IDs (`F01`–`F20`) and requirement IDs refer to `PRD.md`. Technical details are in `TRD.md`. Runtime flows are in `PROCESS_FLOW.md`.

## CONTEXT

`pitwall_sim` is a desktop 2D F1 race simulator under the 2026 regulations. The user is the race engineer of one car (Our Car). Rival battery state is hidden and is shown only as a Radar Estimate from noisy public telemetry. The full product (`PRD.md`) includes all 2026 tracks, weather, incidents, a Gemma radio, debrief and real-race compare modes.

The MVP exists to prove the core loop before the expensive features are built:

```text
simulate a believable 2026 race
→ user makes energy, overtake, driver and pit calls
→ user sees own car exactly and rivals only through the Radar Estimate
→ result changes because of those calls
```

## MVP BOUNDARY STATUS

CONFIRMED by the owner on 2026-10-19, with additions. On top of the dependency-ordered
baseline, the MVP also includes:

- Safety Car, Virtual Safety Car, and the incidents that trigger them (`F06`, partial).
- AI Driver mistakes (`F04`), because they are what generates those incidents.
- Dynamic weather (`F07`), with intermediate and wet tyres and the matching `BOX` reactions (`FR-CTRL-06`).

Still deferred to R2: red flags, track-limits warnings and penalties, reliability DNFs,
the tyre temperature model, and the Strategy Predictor (`F13`).

Agents MUST build in the order of this document unless the owner changes it.

## MVP OBJECTIVE

A user can run a full 22-car race at Suzuka under either Rule Set, act as race engineer through UI buttons, see Rival batteries only as Radar Estimates, react to Safety Cars, Virtual Safety Cars and rain, and finish the race with a result that depends on their calls.

## MVP SCOPE

### Included

| Feature | MVP extent |
| --- | --- |
| F01 Track Builder | Suzuka only. Builder MUST be generic (no Suzuka-specific code) |
| F02 Car Physics | Powertrain, battery, Straight Mode / Corner Mode aero, fuel, dirty air, tyres with wear including intermediate and wet compounds (temperature model MAY be simplified to constant optimal temperature) |
| F03 Rule Sets | Both `2026_pre_miami` and `2026_post_miami` |
| F04 AI Driver | Speed-profile following, Energy Mode execution, attack/defend, and mistakes (mistakes INCLUDED by owner decision 2026-10-19) |
| F05 Race Engine | Standing start, gaps, overtakes, pit lane, finish |
| F06 Race Events (partial) | Incidents from driver mistakes and overtake contact, Virtual Safety Car, Safety Car. Red flag, track limits, penalties and reliability DNFs excluded |
| F07 Weather | Dynamic dry/damp/wet states, track wetness, grip change, track evolution, noisy public forecast |
| F08 Rival Strategy AI | Basic: one-stop/two-stop plans and energy mode switching per team |
| F09 Snapshot | Save/restore and deterministic seed (required early because later features depend on it) |
| F10 Public Feed | 4 Hz noisy Rival telemetry + public timing |
| F11 Rival Battery Radar | Radar Estimate with confidence, fed only by Public Feed |
| F12 Engineer Commands | All commands, including the SC/VSC/weather reactions (`FR-CTRL-06`) |
| F15 Pit Wall UI | Timing tower, track map, telemetry traces, radar panel, Our Car status, clock controls, command buttons, flag banners and weather display |
| F19 Grid Config | Real grid file (frozen at the Singapore GP entry list) + fictional grid file |
| F20 Calibration Tooling | Suzuka lap-time and speed-trace comparison |

### Excluded from MVP (built in later releases)

| Feature | Release |
| --- | --- |
| F06 remainder: red flag, track-limits warnings and penalties, reliability DNFs | R2 |
| F02 tyre temperature model (MVP fixes temperature at optimal) | R2 |
| F13 Strategy Predictor | R2 |
| F14 Two-Way Radio (Gemma) | R3 |
| F16 Debrief & Scoring | R3 |
| F17 Compare Mode — Decision Points | R4 |
| F18 Compare Mode — Alternate Race | R4 |
| F01 remaining 2026 calendar tracks | R5 |

## MVP REQUIREMENTS

| ID | Requirement |
| --- | --- |
| MVP-01 | Suzuka model built from FastF1 geometry with tagged zones (straight, braking, acceleration, overtaking, detection point, pit lane). |
| MVP-02 | Single-car Suzuka calibration (NFR-06; owner round 15). MUST: every team's lap time within 2% of its own 2026 Japanese GP qualifying target (OpenF1; FastF1 needs an F1TV login), team order within ±2, plausibility limits met (peak lateral ≤ 5.5 g, peak braking ≤ 6.0 g, Esses ≤ 15 km/h over the real minimum speeds), no bound hits on shared tyre coefficients. SHOULD: speed RMSE ≤ 15 km/h; 15–20 km/h with every MUST met is accepted with the per-corner residuals in `docs/results/CALIBRATION_NOTES.md`. Provisional now (`T-02A` fit 2, CALIBRATED-PROVISIONAL); MVP sign-off (`T-080`) uses the `T-02D` calibration. |
| MVP-03 | Battery energy of every car MUST stay within the Rule Set usable window at every step. |
| MVP-04 | Speed tapers, zone caps, Overtake mode and super-clipping MUST follow the selected Rule Set file. |
| MVP-05 | A full 22-car race runs headless in 10 s or less (NFR-02). |
| MVP-06 | Same seed + same commands → identical race (state hash equal at finish). |
| MVP-07 | UI runs at 10+ fps at `16x`; clock supports `PAUSE`, `1x`, `4x`, `16x`. |
| MVP-08 | No in-race UI component can read Rival Ground Truth (enforced by architecture and a test; see `TRD.md`). |
| MVP-09 | Every MVP Engineer Command changes Our Car's behaviour measurably (test per command). |
| MVP-10 | At least one Rival team pits and changes Energy Mode without user input during a race. |
| MVP-11 | A driver mistake can cause an incident, and an incident can raise a Virtual Safety Car or a Safety Car. A Safety Car bunches the field. |
| MVP-12 | Rain can start during a race, change grip, and make intermediate or wet tyres the faster choice; the crossover MUST emerge from the per-compound grip curves, not from a hard-coded rule. |
| MVP-13 | `BOX` under Safety Car costs measurably less time than `BOX` under green flag (`FR-CTRL-06`). |

## RELEASE PLAN

| Release | Adds | Done when |
| --- | --- | --- |
| R1 = MVP | Scope above | All MVP-01…MVP-13 pass |
| R2 | F06 remainder (red flag, track limits, penalties, DNFs), tyre temperature, F13 | Penalties and red flags play out correctly; predictor shows pit window and undercut gap |
| R3 | F14, F16 | Free-text commands work with clarification fallback; debrief lists Decision Points with best call |
| R4 | F17, F18 | A Real Race replays with decision pauses, and can be continued as an Alternate Race |
| R5 | Remaining 2026 tracks | Every calendar track passes NFR-06 calibration |

## BUILD ORDER INSIDE THE MVP

```text
1. config schemas + Rule Set files (F03, F19)
2. Track Builder for Suzuka (F01)
3. Single-car physics + calibration script (F02, F20)  → gate: MVP-02
4. AI Driver + 22-car Race Engine (F04, F05)           → gate: MVP-05
5. Snapshot + determinism (F09)                         → gate: MVP-06
6. Rival Strategy AI basic (F08)                        → gate: MVP-10
7. Driver mistakes, incidents, VSC, SC (F04, F06 part)  → gate: MVP-11
8. Weather + wet tyres (F07)                            → gate: MVP-12
9. Public Feed + Rival Battery Radar (F10, F11)
10. Engineer Commands incl. SC/VSC/weather (F12)        → gates: MVP-09, MVP-13
11. Pit Wall UI (F15)                                   → gates: MVP-07, MVP-08
```

## CONSTRAINTS

- MVP MUST NOT include Gemma or any LLM dependency (the `radio` extra exists but MVP code MUST NOT import `llama_cpp`).
- MVP MUST NOT hard-code Suzuka-specific logic; all track specifics live in `config/tracks/suzuka.yaml`.
- MVP MUST implement `F09` Snapshot even though Debrief is excluded, because R3 and R4 depend on it.

## OPEN ITEMS

| Item | Status |
| --- | --- |
| Owner confirmation of MVP boundary | RESOLVED 2026-10-19 — confirmed with the additions above |
| Time budget per release | UNKNOWN |
| Target laptop hardware for NFR-02 / MVP-05 | RESOLVED 2026-10-19 — 8 GB RAM, CPU only, no GPU |
