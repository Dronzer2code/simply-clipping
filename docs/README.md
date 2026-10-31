# docs/ — index: which document holds what

Start here to find anything in the docs. The docs were sorted into topic folders on
2026-10-28; no content was removed. Every file name is unique across the folders, so
a bare name in the text (`TRD.md`, `TASKS.md`, ...) means the file listed below.
Repository rules for agents stay in `CLAUDE.md` at the repository root.

## FOLDER LAYOUT

```text
docs/
├── README.md                     this index
├── COLLAB_SUMMARY.md             one-page project summary for collaborators: setup, status, open items
├── PITCH.md                      plain-language pitch for judges: the idea, every feature, results
├── HACKATHON_SCOPE.md            what the hackathon builds (H1-H8, E1-E3), fallbacks, done checklist
├── spec/        what to build (stable requirements and contracts)
│   ├── PRD.md                    product: scope, glossary, features F01-F20, requirements, decisions
│   ├── MVP.md                    release R1 boundary, MVP-01..13 acceptance, release plan R1-R5
│   ├── TRD.md                    technical design: algorithms, config schemas, data contracts, rule values
│   ├── PROCESS_FLOW.md           runtime flows PF-01..PF-18
│   ├── UI_DESIGN.md              screens, panels, colours, shortcuts, UI states
│   ├── SIMPLY_CLIPPING_BRIDGE.md interface contract: export, plug-in functions, scorer, batch
│   └── SIMPLY_CLIPPING_SPEC.md   Simply Clipping (owner's estimator): rules, pipeline, lessons, targets
├── planning/    what to do next
│   ├── TASKS.md                  every task: ID, files, dependencies, acceptance, status
│   ├── SPRINT.md                 owner's deadline sprint texts (verbatim)
│   ├── BUILD_PROMPTS.md          operator prompts that drive an agent through TASKS.md
│   └── IMPROVEMENTS.md           showcase review: Simply Clipping features, UI/feature improvements, pitch edits
├── status/      where the project stands
│   ├── SESSION_CONTEXT.md        handoff log: what each session / sprint day did and decided
│   └── PROJECT_STATUS.md         status audit after a clean local run: done, to come, needs changes
├── guides/      how to run things
│   ├── SETUP.md                  install, data download, commands, troubleshooting
│   ├── DEMO.md                   3-minute demo script with timings and fallbacks
│   ├── DEMO_SC.md                3-minute Simply Clipping demo (live alerts, results, real race)
│   └── DEMO_HACKATHON.md         4-minute hackathon demo (seed 2: radio, strategy, Safety Car, Reveal)
├── results/     measured numbers (written by code)
│   ├── CALIBRATION_NOTES.md      calibration fits, bound hits, owner rounds 13-15
│   ├── SC_RESULTS.md             estimator table: built-in, dumb rule, Simply Clipping; real race
│   └── SC_TUNING.md              Simply Clipping tuning log (seeds 1-5 only), per SC step
├── examples/    hello_clipping.py: template estimator plug-in (module docs.examples.hello_clipping)
└── screenshots/ dayN_*.png, demo_pitwall.png (README and report screenshots)
```

## READING ORDER

| Situation | Read |
| --- | --- |
| New agent session | `CLAUDE.md` → `status/SESSION_CONTEXT.md` → `status/PROJECT_STATUS.md` → `spec/PRD.md` GLOSSARY + FEATURES → `planning/TASKS.md` → the `spec/TRD.md` sections the task names |
| Before any build task | `spec/MVP.md` (is it in the current release?) |
| Sprint work (until 2026-10-31) | `planning/SPRINT.md`, then `planning/TASKS.md` block S |
| Setting up a machine | `guides/SETUP.md` (root `README.md` has the short Windows quick start) |
| Working on export / scorer / bench / estimators | `spec/SIMPLY_CLIPPING_BRIDGE.md`, `results/SC_RESULTS.md`, `examples/hello_clipping.py` |
| Any `SC-n` task (Simply Clipping, branch `simply-clipping`) | `spec/SIMPLY_CLIPPING_SPEC.md`, then `planning/TASKS.md` block SC, then `spec/SIMPLY_CLIPPING_BRIDGE.md` |
| Touching calibration | `spec/TRD.md` CALIBRATION, `results/CALIBRATION_NOTES.md` |

## DOCUMENT CATALOGUE

"Edited by": *owner* = decisions only the owner makes; *agent* = kept up to date by
agents as work is done; *generated* = rewritten by a command (do not hand-edit, see
GENERATED FILES).

### spec/ — requirements and contracts

| File | Holds | Main sections | Edited by |
| --- | --- | --- | --- |
| `PRD.md` | Product definition; source of feature IDs `F01`–`F20` and requirement IDs | RELATED DOCUMENTS, CONTEXT (2026 power unit, race engineer role, Rival Battery Radar), PRODUCT IDENTITY, GLOSSARY, SCOPE, FEATURES, FUNCTIONAL REQUIREMENTS (`FR-CTRL-*`, screens, realism, extras), NON-FUNCTIONAL REQUIREMENTS (`NFR-*`), CONSTRAINTS, DECISIONS LOG, OPEN ITEMS, SUCCESS CRITERIA | owner |
| `MVP.md` | What R1 contains and in which order it is built | MVP BOUNDARY STATUS, MVP SCOPE (included / excluded), MVP REQUIREMENTS (`MVP-01`…`MVP-13`), RELEASE PLAN (R1–R5), BUILD ORDER INSIDE THE MVP, CONSTRAINTS, OPEN ITEMS | owner |
| `TRD.md` | How everything is implemented (1466 lines) | ARCHITECTURE PRINCIPLES, TECHNOLOGY STACK, REPOSITORY STRUCTURE, SIMULATION CORE (time stepping, per-step order, step kernel, longitudinal dynamics, powertrain, battery, aero, tyres, fuel, dirty air), AI DRIVER, OVERTAKE MODEL, PIT LANE, RACE EVENTS, WEATHER, RIVAL STRATEGY AI, SNAPSHOT AND DETERMINISM, PUBLIC FEED, RIVAL BATTERY RADAR, ENGINEER COMMANDS, STRATEGY PREDICTOR, TWO-WAY RADIO, REAL RACE REPLAY AND COMPARE, DEBRIEF AND SCORING, CALIBRATION, CONFIG SCHEMAS, DATA CONTRACTS, THREADING MODEL, PERFORMANCE BUDGETS, TESTING, RULE SET VALUES, OPEN ITEMS | agent (rule values: owner) |
| `PROCESS_FLOW.md` | Step-by-step runtime flows, and how far each one is built | FLOW INDEX, IMPLEMENTATION STATUS (per-flow done / needs refinement / not implemented, sprint flows not yet described), a Status block under every flow, PF-01 track build … PF-18 alternate race (PF-04 tick, PF-06 info barrier, PF-07 command by button, PF-11 overtake, PF-12 pit stop, PF-13 incidents / VSC / SC, PF-14 weather), OPEN ITEMS | agent |
| `UI_DESIGN.md` | Look and behaviour of every screen | CONSTRAINTS, SCREENS, S1 RACE SETUP, S2 PIT WALL LAYOUT, PANEL SPECIFICATIONS (timing tower, track map, Our Car, rival radar, traces, strategy, command bar, radio), COLOURS, KEYBOARD SHORTCUTS, UI STATES, S3 DEBRIEF, S4 / S5 COMPARE, OPEN ITEMS | agent (palette accepted by owner) |
| `SIMPLY_CLIPPING_BRIDGE.md` | Contract between the sim and an external battery estimator | 0 QUICK START, 1 EXPORT (feed + Ground Truth files), 2 YOUR PACKAGE (`run(...)` offline, `create(...)` live), 3 SCORER, 4 BATCH AND BASELINE TABLE | agent |
| `SIMPLY_CLIPPING_SPEC.md` | The owner's Simply Clipping estimator, agent-first | PURPOSE, RULES (`SC-R01`…`SC-R08`), PACKAGE LAYOUT, PIPELINE (P1-P10), STATES, ALERT RULES, LESSONS FROM THE SIMULATOR (`L-a`…`L-f`), CONTRACT, TARGETS, CONFIG, TEST PLAN, OPEN ITEMS | owner (rules, targets), agent (status) |

### planning/ — work to do

| File | Holds | Main sections | Edited by |
| --- | --- | --- | --- |
| `TASKS.md` | The one task list; status of every task | RULES (status values), S (sprint block), R1 Blocks 0–8 (`T-001`…`T-080`), R2 (`T-100`…), R3 (`T-200`…), R4 (`T-300`…), R5 (`T-400`…) | agent (status), owner (parking / order) |
| `SPRINT.md` | Owner's sprint instructions, **verbatim** (paths inside refer to the pre-2026-10-28 layout; header maps them) | Part 1 deadline sprint, Part 2 alerts + call the driver, Part 3 day-5 answers, Part 4 days 6–9 plan, Part 5 Simply Clipping test-bench addendum | owner only |
| `BUILD_PROMPTS.md` | Copy-paste prompts for a human operator | OPERATOR RULES, P-00 session start, P-01…P-11 (R1 blocks), P-20…P-22 (later releases), P-REVIEW, P-FIX, P-UNBLOCK | agent |

### status/ — where the project stands

| File | Holds | Main sections | Edited by |
| --- | --- | --- | --- |
| `SESSION_CONTEXT.md` | Chronological handoff: decisions and numbers not recorded elsewhere | WHERE THE PROJECT STANDS, OWNER WORKING RULES, WHAT EACH SPRINT DAY BUILT, DAY 4 … DAY 9 details, KNOWN ISSUES, COMMANDS | agent, at the end of each session |
| `PROJECT_STATUS.md` | Snapshot audit from a clean install and run (2026-10-28) | HOW IT WAS RUN, RUN RESULTS, WORK DONE, ON ITS WAY (R1 remaining, MVP acceptance table, later releases), NEEDS CHANGES (found by running) | agent, after each full run |

### guides/ — how to run

| File | Holds | Main sections | Edited by |
| --- | --- | --- | --- |
| `SETUP.md` | Everything to install, run and test | REQUIREMENTS, 1 clone + venv, 2 dependencies, 3 import contracts, 4 real data (FastF1 / OpenF1, track builder, calibration compare), 5 Gemma model (R3), 6 COMMANDS, 7 CONFIG FILES, 8 VERIFY, TROUBLESHOOTING | agent |
| `DEMO.md` | 3-minute screen-recording script | 1 one line, 2 race setup, 3 DEFEND + ATTACK with F1, 4 scenario presets, 5 call summary, 6 test bench (with fallback seeds) | agent |

### results/ — measured numbers

| File | Holds | Main sections | Edited by |
| --- | --- | --- | --- |
| `CALIBRATION_NOTES.md` | Suzuka calibration results and history | pre-Miami PROVISIONAL fit (bound hits, pole team), T-02A final fit, placeholders accepted in round 13, round 13 diagnosis, round 14 changes, last fit, owner round 15, T-02D constrained fit | generated (top) + agent (round sections) |
| `SC_RESULTS.md` | Estimator / alert baseline table | TEST SET (seeds 6–10) and TUNE SET (seeds 1–5), one table per scenario: battles, cda_trap, closing_speed, normal, repass, taper | generated |

## WHERE TO FIND IT (TOPIC LOOKUP)

| Looking for | Go to |
| --- | --- |
| Meaning of a term (Our Car, Rival, Ground Truth, Radar Estimate, Energy Mode, super-clip, …) | `spec/PRD.md` GLOSSARY |
| Race comparison graph / race dashboard of one race (Graphify track) | root `README.md` "Race graphs (Graphify)"; code `pitwall_sim/graph/`; output `graphify-out/races/<run_id>/`; demo moment in `guides/DEMO_HACKATHON.md` |
| Feature `F01`–`F20` | `spec/PRD.md` FEATURES |
| Requirement `FR-*` / `NFR-*` | `spec/PRD.md` FUNCTIONAL / NON-FUNCTIONAL REQUIREMENTS |
| Owner decisions (dated) | `spec/PRD.md` DECISIONS LOG; sprint decisions in `planning/SPRINT.md`; later ones in `status/SESSION_CONTEXT.md` |
| Is X in the current release? | `spec/MVP.md` MVP SCOPE and RELEASE PLAN |
| MVP acceptance `MVP-01`…`MVP-13` (definition) | `spec/MVP.md` MVP REQUIREMENTS |
| MVP acceptance (current pass / fail) | `status/PROJECT_STATUS.md` MVP acceptance today |
| Hard rules `HR-01`…`HR-10`, git / commit rules | root `CLAUDE.md` |
| Task status, dependencies, acceptance | `planning/TASKS.md` |
| What is built / still to come / needs changes | `status/PROJECT_STATUS.md` |
| Which runtime flow (PF-01…PF-18) is done, needs refinement or is not implemented | `spec/PROCESS_FLOW.md` IMPLEMENTATION STATUS and the Status block under each flow |
| Why something was decided during the sprint, per-day numbers | `status/SESSION_CONTEXT.md` DAY 4 … DAY 9 |
| Known bugs and limitations | `status/SESSION_CONTEXT.md` KNOWN ISSUES, `status/PROJECT_STATUS.md` NEEDS CHANGES |
| 2026 rule values (energy, tapers, zone caps, mass, fuel flow) | `spec/TRD.md` RULE SET VALUES; files `config/rules/*.yaml` |
| Powertrain / battery / aero / tyres / fuel / dirty-air physics | `spec/TRD.md` SIMULATION CORE |
| Order of operations in one simulation step | `spec/TRD.md` Per-step order; `spec/PROCESS_FLOW.md` PF-04 |
| AI Driver, Energy Modes, mistakes | `spec/TRD.md` AI DRIVER |
| Overtake probability, HOLD / ATTACK / DEFEND effect | `spec/TRD.md` OVERTAKE MODEL; `spec/PROCESS_FLOW.md` PF-11 |
| Pit lane, pit stop | `spec/TRD.md` PIT LANE; `spec/PROCESS_FLOW.md` PF-12 |
| Safety Car, VSC, incidents | `spec/TRD.md` RACE EVENTS; `spec/PROCESS_FLOW.md` PF-13 |
| Weather, wet tyres | `spec/TRD.md` WEATHER; `spec/PROCESS_FLOW.md` PF-14 |
| Rival strategy | `spec/TRD.md` RIVAL STRATEGY AI; `spec/PROCESS_FLOW.md` PF-10 |
| Seeds, RNG streams, snapshot / fork | `spec/TRD.md` SNAPSHOT AND DETERMINISM |
| Public Feed (4 Hz, noise, dropout) | `spec/TRD.md` PUBLIC FEED |
| Rival Battery Radar algorithm and constants | `spec/TRD.md` RIVAL BATTERY RADAR |
| What the UI may see (info barrier), `EngineerView` | `spec/TRD.md` DATA CONTRACTS; `spec/PROCESS_FLOW.md` PF-06 |
| Engineer Commands and their parameters | `spec/TRD.md` ENGINEER COMMANDS; `spec/PROCESS_FLOW.md` PF-07 |
| Alerts (ATTACK, DEFEND, RE-PASS, CLOSING) and call options | `planning/SPRINT.md` Part 2; `status/SESSION_CONTEXT.md` DAY 4–5 |
| Radio / Gemma model (R3) | `spec/TRD.md` TWO-WAY RADIO; `spec/PROCESS_FLOW.md` PF-08, PF-09; `guides/SETUP.md` section 5 |
| Debrief (R3), compare modes (R4) | `spec/TRD.md` DEBRIEF AND SCORING, REAL RACE REPLAY AND COMPARE; `spec/PROCESS_FLOW.md` PF-16…PF-18 |
| Strategy Predictor (R2) | `spec/TRD.md` STRATEGY PREDICTOR; `spec/PROCESS_FLOW.md` PF-15 |
| Config file schemas (`app.yaml`, rules, tracks, grid) | `spec/TRD.md` CONFIG SCHEMAS; file list in `guides/SETUP.md` section 7 |
| Dataclasses (`CarState`, `RaceState`, `EngineerView`, …) | `spec/TRD.md` DATA CONTRACTS |
| Package layout | `spec/TRD.md` REPOSITORY STRUCTURE |
| Threads, time budgets, test plan | `spec/TRD.md` THREADING MODEL, PERFORMANCE BUDGETS, TESTING |
| Calibration method | `spec/TRD.md` CALIBRATION; `spec/PROCESS_FLOW.md` PF-02 |
| Calibration results, bound hits | `results/CALIBRATION_NOTES.md` |
| Track building (FastF1 / OpenF1) | `spec/PROCESS_FLOW.md` PF-01; `guides/SETUP.md` section 4; track model format and zones in `spec/TRD.md` CONFIG SCHEMAS `config/tracks/<track_id>.yaml` |
| Screens, panels, colours, shortcuts | `spec/UI_DESIGN.md` |
| Export format, plug-in functions, scorer metrics | `spec/SIMPLY_CLIPPING_BRIDGE.md` |
| Baseline numbers for estimators and alerts | `results/SC_RESULTS.md` |
| Template estimator plug-in | `examples/hello_clipping.py` |
| Simply Clipping rules, pipeline, lessons, targets | `spec/SIMPLY_CLIPPING_SPEC.md`; package `simply_clipping/` (constants in `simply_clipping/config.yaml`) |
| Install, commands, pytest markers, troubleshooting | `guides/SETUP.md` |
| Demo recording | `guides/DEMO.md` |
| Prompts to run an agent | `planning/BUILD_PROMPTS.md` |
| How code and docs connect | `graphify-out/GRAPH_REPORT.md` (repository root; rebuild with `graphify update .`) |

## GENERATED FILES

| File | Written by | Note |
| --- | --- | --- |
| `results/SC_RESULTS.md` | `python -m pitwall_sim.export --batch ...` (`--results`) and `python -m pitwall_sim.evaluate.batch` (`--write`) | Whole file rewritten after every batch run |
| `results/CALIBRATION_NOTES.md` | `python -m pitwall_sim.calibration.fit` (`--notes`) | Whole file rewritten: the hand-written round sections below the generated part would be lost; copy them first (`status/PROJECT_STATUS.md` NEEDS CHANGES 12) |

## WHERE NEW DOCUMENTS GO

| New document is about | Folder |
| --- | --- |
| A requirement, design or interface contract | `spec/` |
| Tasks, plans, owner instructions | `planning/` |
| Progress, handoff, audits, reports (e.g. `T-080` `MVP_REPORT.md`) | `status/` |
| Install, run, demo, how-to | `guides/` |
| Numbers a command writes | `results/` |

Add every new file to the tables above and to the DOCUMENT MAP in `CLAUDE.md`.
