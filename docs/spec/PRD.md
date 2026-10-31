# PRD.md — Pit Wall Race Simulator (2026 Regulations)

## PURPOSE

This document defines WHAT is being built, WHY, and WHAT it must do.
It is the source of truth for product scope, features, requirements, and decisions.

An agent reading this document MUST be able to understand the product without any prior conversation.

## RELATED DOCUMENTS

| Document | Responsibility | Relationship to this PRD |
| --- | --- | --- |
| `PRD.md` (this file) | What and why | Defines feature IDs `F01`–`F20` and requirement IDs used by all other documents |
| `MVP.md` | Minimum version to build first | Selects a subset of the features defined here |
| `TRD.md` | Technical implementation | Implements the requirements defined here |
| `PROCESS_FLOW.md` | Runtime flows and user journeys | Describes how the features defined here interact at runtime |
| `UI_DESIGN.md` | Screens, layout, colours, interactions | Implements `F15` and UI parts of `F16`–`F18` |
| `TASKS.md` | Ordered build tasks | Breaks the features defined here into tasks per release |
| `SETUP.md` | Environment, commands | How to install, run and test |
| `BUILD_PROMPTS.md` | Operator prompts | Prompts that drive an agent through `TASKS.md` |
| `CLAUDE.md` (repo root) | Agent entry point | Hard rules and workflow for coding agents |
| `Rival Battery Radar — MVP Spec` (external, existing) | Separate prior project: battery estimator for real 2026 races | This product embeds that estimator as feature `F11`. Critical context is restated below; the external spec is not required to understand this PRD |

## CONTEXT

### The 2026 Formula 1 power unit

- From 2026, F1 power units deliver roughly 50% of power from the internal combustion engine (ICE, ~400 kW) and 50% from the electric motor-generator (MGU-K, up to 350 kW). The MGU-H is removed.
- Battery (energy store) charge therefore decides much of the race: overtakes, defending, and re-passes depend on who has energy available on each straight.
- A team sees its own car's battery state of charge. A team does NOT see rival cars' battery state. TV broadcasts do not show it.
- Drivers and engineers manage energy using deployment modes, harvesting under braking, lift-and-coast, and "super-clipping" (harvesting at full throttle at the end of straights, which reduces speed).
- Rules include an Overtake mode (available within 1 s of the car ahead) that allows extra electrical deployment.
- The FIA changed several energy rules mid-season, effective from the Miami Grand Prix (3 May 2026). Both rule versions exist and MUST be supported (see `F03`).

### The race engineer role

On the pit wall, a race engineer for one car:

- Sees their own car's exact telemetry and battery state.
- Sees public timing (positions, gaps, lap times) and limited information about rivals.
- Decides energy usage, overtake timing, tyre and pit strategy, reactions to safety cars and weather.
- Communicates decisions to the driver by team radio.

### The prior project: Rival Battery Radar

A separate existing project estimates every car's hidden battery energy from public telemetry (speed, throttle, brake) using a physics model, and raises ATTACK / DEFEND / RE-PASS RISK / CLOSING-SPEED RISK alerts. In this product it is reused as the rival battery estimate shown to the user (`F11`).

## PRODUCT IDENTITY

| Item | Value |
| --- | --- |
| Product name | **We Are Racing, Not Testing** (display name, window title; owner decision 2026-10-19) |
| Working code identifier | `pitwall_sim` |
| Product type | Single-user desktop race simulator / strategy game |
| Target user | One person acting as the race engineer of one selected car (primary user: the project owner). The user picks their favourite team and driver as Our Car on the Race Setup screen |
| Platform | Desktop, 2D, PySide6 (decided). Target hardware: laptop, 8 GB RAM, CPU only, no GPU (owner decision 2026-10-19) |

## OBJECTIVE

Build an F1-like synthetic race simulator, faithful to the 2026 regulations, in which the user acts as race engineer for one selected car on the pit wall. The user makes the decisions a real race engineer makes, with the same information limits (own car fully visible, rival batteries hidden), and receives a debrief comparing their calls with the best possible calls.

Secondary objective: replay real 2026 races and compare the user's calls against what the real team did.

## GLOSSARY (CANONICAL TERMS)

All project documents MUST use these names.

| Term | Definition |
| --- | --- |
| Our Car | The single car the user engineers |
| Rival | Any car other than Our Car |
| Race Engineer | The user |
| AI Driver | Software that drives each car, including Our Car, following engineer commands |
| Engineer Command | A typed, validated instruction from the Race Engineer to Our Car's AI Driver |
| Rule Set | A configuration file defining 2026 power unit and race rules (`2026_pre_miami`, `2026_post_miami`) |
| Ground Truth | The true simulated state of every car (including hidden battery energy) |
| Public Feed | The subset of information a real team can see about Rivals: timing plus noisy, low-rate telemetry |
| Radar Estimate | Rival battery estimate produced by the Rival Battery Radar from the Public Feed |
| Snapshot | A complete, restorable copy of race state at one moment |
| Fork | Restoring a Snapshot and continuing with a different decision |
| Decision Point | A moment where an engineer decision is evaluated (debrief) or requested (compare mode) |
| Energy Mode | One of `PUSH`, `BALANCED`, `HARVEST` |
| Clock Speed | Simulation playback speed: `PAUSE`, `1x`, `4x`, `16x` |
| Real Race | A real 2026 race loaded from FastF1 data |
| Straight Mode / Corner Mode | The two 2026 active aerodynamics states (low drag / high downforce) |

## SCOPE

### In scope

- Full 2026 calendar tracks, built from real track geometry.
- 22-car field. Real 2026 drivers and teams by default, switchable to a fictional grid by configuration.
- Both 2026 Rule Sets, selectable per race.
- All features `F01`–`F20` below.

### Out of scope

| Item | Status |
| --- | --- |
| 3D graphics | Out of scope (decided: 2D) |
| Web or mobile app | Out of scope (decided: desktop) |
| Voice radio (speech-to-text / text-to-speech) | Out of scope (decided: free text) |
| Multiplayer / multiple users | Out of scope |
| Live connection to real ongoing races | Out of scope |
| Export of noisy telemetry + Ground Truth log as a Radar test dataset | Not selected by owner. MAY be added later |
| Driver-in-the-loop driving (user drives the car) | Out of scope |
| Car setup / garage work | Out of scope |
| Seasons, championships, career mode | UNRESOLVED (not discussed) |

## FEATURES

| ID | Feature | Summary |
| --- | --- | --- |
| F01 | Track Builder | Builds each track model from real geometry: centre line, curvature, corner speed limits, zones |
| F02 | Car Physics | Powertrain, battery, active aero, tyres, fuel, dirty air, team performance differences |
| F03 | Rule Sets | Switchable 2026 rules (`2026_pre_miami`, `2026_post_miami`) loaded from config |
| F04 | AI Driver | Drives every car; executes Engineer Commands for Our Car; attacks, defends, makes mistakes |
| F05 | Race Engine | Time-stepped 22-car race: start, gaps, overtakes, pit lane, finish |
| F06 | Race Events | Safety Car, Virtual Safety Car, red flag, incidents, crashes, track limits, penalties, DNFs |
| F07 | Weather | Dynamic rain, track wetness, track evolution, changing grip |
| F08 | Rival Strategy AI | Each Rival team runs its own hidden energy and pit strategy |
| F09 | Snapshot | Save, restore and fork race state; deterministic replay from seed |
| F10 | Public Feed | Produces the limited, noisy information a real team sees about Rivals |
| F11 | Rival Battery Radar | Estimates Rival battery energy from the Public Feed; never reads Ground Truth |
| F12 | Engineer Commands | All decisions available to the Race Engineer, as typed commands |
| F13 | Strategy Predictor | Tyre wear, pit window and undercut/overcut forecasts |
| F14 | Two-Way Radio | Free-text radio both ways; local Gemma model parses engineer text and writes driver replies |
| F15 | Pit Wall UI | Timing tower, track map, telemetry traces, radar panel, strategy panel, radio panel, clock controls |
| F16 | Debrief & Scoring | After the race: the user's calls vs the best calls, computed using Ground Truth |
| F17 | Compare Mode — Decision Points | Replay a Real Race; pause at real decision moments; user decides; reveal the real team's call |
| F18 | Compare Mode — Alternate Race | Start from a Real Race at a chosen lap and let the race diverge based on the user's calls |
| F19 | Grid Config | Real 2026 grid or fictional grid via config file |
| F20 | Calibration Tooling | Compares simulated laps and races against real 2026 data per track |

## FUNCTIONAL REQUIREMENTS

### Engineer controls (`F12`)

| ID | Requirement |
| --- | --- |
| FR-CTRL-01 | The Race Engineer MUST be able to set Our Car's Energy Mode (`PUSH`, `BALANCED`, `HARVEST`). |
| FR-CTRL-02 | The Race Engineer MUST be able to allow or forbid Overtake mode use, optionally per lap and per zone. |
| FR-CTRL-03 | The Race Engineer MUST be able to set lift-and-coast instructions (on/off, target zones). |
| FR-CTRL-04 | The Race Engineer MUST be able to call a pit stop on a chosen lap with a chosen tyre compound, and cancel it before pit entry. |
| FR-CTRL-05 | The Race Engineer MUST be able to give driver instructions: `DEFEND` (optional corner), `ATTACK`, `HOLD_POSITION`, `LET_TEAMMATE_BY`, `PUSH_LAP`, `MANAGE_TYRES`. |
| FR-CTRL-06 | The Race Engineer MUST be able to react to Safety Car, Virtual Safety Car and weather changes using the same commands (e.g. pit under SC, switch to intermediate tyres). |
| FR-CTRL-07 | Every command MUST be issuable from UI buttons and from free-text radio (`F14`). |

### Pit wall screens (`F15`)

| ID | Requirement |
| --- | --- |
| FR-SCR-01 | The UI MUST show a Rival battery panel using the Radar Estimate with a confidence value. It MUST NOT show Rival Ground Truth during a race. |
| FR-SCR-02 | The UI MUST show live telemetry traces (speed, throttle, brake, battery energy) for Our Car vs the car ahead and the car behind. Rival traces MUST come from the Public Feed. |
| FR-SCR-03 | The UI MUST show a track map with all cars and a timing tower with positions, gaps, intervals, tyre compound, tyre age and sector times. |
| FR-SCR-04 | The UI MUST show a strategy panel with tyre wear forecast, pit window and undercut/overcut gap forecasts (`F13`). |
| FR-SCR-05 | The UI MUST show Our Car's exact battery energy, Energy Mode, Overtake mode availability, tyre state and fuel. |
| FR-SCR-06 | The UI MUST provide clock controls: `PAUSE`, `1x`, `4x`, `16x`. |

### Simulation realism (`F01`–`F08`)

| ID | Requirement |
| --- | --- |
| FR-SIM-01 | Car physics MUST model ICE power, MGU-K deployment with speed tapers and zone caps, battery usable window, harvesting under braking, super-clipping, Overtake mode, Straight Mode / Corner Mode aero, tyre wear and temperature, fuel burn and dirty air. |
| FR-SIM-02 | Teams MUST differ in power unit output, drag and efficiency, set in config. |
| FR-SIM-03 | All Rule Set numbers MUST come from config files; no rule number may be hard-coded. |
| FR-SIM-04 | Rival teams MUST run their own strategies (`F08`) using only their own Ground Truth and the Public Feed of other cars. |
| FR-SIM-05 | The simulation MUST include driver mistakes, crashes, track-limits warnings, time penalties and DNFs. |
| FR-SIM-06 | The simulation MUST include dynamic weather (dry, damp, wet) with changing grip and track evolution. |
| FR-SIM-07 | Overtakes MUST be decided by modelled factors (speed difference, zone, tyre and energy state, driver instruction), not pure chance. |
| FR-SIM-08 | The same seed and the same Engineer Commands MUST produce an identical race. |

### Extras (`F14`, `F16`, `F17`, `F18`)

| ID | Requirement |
| --- | --- |
| FR-EXT-01 | The Race Engineer MUST be able to type free-text radio messages. A deterministic keyword pre-parser MUST handle unambiguous phrases, and a local fine-tuned Gemma 3 270M model MUST convert the rest into Engineer Commands under a forced JSON schema. |
| FR-EXT-02 | If the radio message cannot be converted with confidence, the AI Driver MUST reply with a clarification request and no command MUST be executed. |
| FR-EXT-03 | The AI Driver MUST send free-text radio replies and unprompted messages (e.g. tyre complaints, low battery). Replies MUST be template-generated; the model MAY only rephrase a template. Replies MUST state only facts present in Our Car's Ground Truth or the Public Feed. |
| FR-EXT-04 | After each race, the debrief MUST list Decision Points, the user's call, the best call, and the outcome difference, plus an overall score. |
| FR-EXT-05 | Compare Mode — Decision Points MUST pause a Real Race replay at real decision moments, take the user's call, then reveal the real team's call and its outcome. |
| FR-EXT-06 | Compare Mode — Alternate Race MUST initialise the simulator from a Real Race state at a chosen lap and continue it as a simulated race. |

## NON-FUNCTIONAL REQUIREMENTS

| ID | Requirement |
| --- | --- |
| NFR-01 | The application MUST run fully offline on one laptop once data and model files are cached. |
| NFR-02 | A full race MUST simulate headless (no UI) in 10 s or less on the target laptop (8 GB RAM, CPU only, no GPU). The measured time MUST be reported. |
| NFR-03 | The UI MUST refresh at 10 frames per second or more at `16x` Clock Speed. |
| NFR-04 | The UI thread MUST NOT block on simulation or Gemma calls. |
| NFR-05 | Radio command parse result MUST appear within 2 s of sending; slower parses MUST NOT freeze the UI. |
| NFR-06 | Simulated lap times MUST be within 2% of real 2026 reference laps for each track (see `F20`). |

## CONSTRAINTS

- MUST be desktop 2D using PySide6.
- MUST use Python as the primary language (consistent with the Rival Battery Radar project).
- MUST use FastF1 as the source of real track geometry and Real Race data.
- MUST use a local, fine-tuned Gemma 3 270M model for radio; MUST NOT require a cloud LLM API. Fine-tuning, forced JSON-schema output and a keyword pre-parser are REQUIRED (see `TRD.md` TWO-WAY RADIO).
- MUST NOT show Rival Ground Truth in any in-race view.
- MUST support both Rule Sets through config, not code branches scattered through modules.
- Real team and driver names MAY be used for personal use. Public release with real names, logos or liveries: UNRESOLVED (licensing).

## DECISIONS LOG

Decisions made by the project owner:

| Topic | Decision |
| --- | --- |
| Project length | Longer project (weeks). Exact duration: UNKNOWN |
| Team size | UNKNOWN |
| Product name | "We Are Racing, Not Testing". Code package stays `pitwall_sim` |
| Language version | Python 3.13 |
| Target hardware | Laptop, 8 GB RAM, CPU only, no GPU |
| Radio model | Gemma 3 270M GGUF, fine-tuning required, grammar-forced output, keyword pre-parser, template driver replies |
| Grid | Real 2026 teams and drivers, frozen at the Singapore GP entry list for New Race mode; compare modes use the replayed race's own entry list |
| MVP boundary | Confirmed, plus Safety Car, VSC, the incidents that trigger them, driver mistakes, and dynamic weather with intermediate/wet tyres |
| Debrief score scale | `debrief.score_scale_s` = 20 s |
| Rule version | Switchable: `2026_pre_miami` and `2026_post_miami` |
| Clock | Live with speed control (`PAUSE`, `1x`, `4x`, `16x`) |
| Platform | Desktop 2D, PySide6 |
| Grid | Real 2026 grid by default, switchable to fictional via config |
| Tracks | Full 2026 calendar |
| Compare mode | Both Decision Points and Alternate Race |
| Radio | Free text both ways |
| Engineer controls | Energy & overtake calls; tyre & pit strategy; driver instructions; SC/VSC/weather calls |
| Screens | Rival battery radar; live telemetry traces; track map + timing tower; strategy predictor |
| Realism | Rival team AI; car physics depth; incidents & penalties; dynamic weather |
| Extras | Two-way radio (Gemma); Real race compare mode; Debrief & scoring |

## OPEN ITEMS

| Item | Status |
| --- | --- |
| Product name | **We Are Racing, Not Testing** (display name, window title; owner decision 2026-10-19) |
| Target laptop hardware (CPU, GPU, RAM) | 8 GB RAM, CPU only, no GPU (owner decision 2026-10-19) |
| Radio model | Gemma 3 270M instruct (`gemma-3-270m-it`), fine-tuned, GGUF Q8_0 preferred (owner decision 2026-10-19) |
| Exact project duration and team size | UNKNOWN |
| Public release and licensing of real names | Personal use only for now (owner decision round 3); public release UNRESOLVED |
| Championship / career mode | UNRESOLVED |
| Exact numeric rule values not yet verified against FIA regulations | See `TRD.md` section RULE SET VALUES |

## SUCCESS CRITERIA

- A user can run a full simulated race at any 2026 track as race engineer, issue all command types by button and by free text, and receive a debrief.
- Rival batteries are never visible in race; the Radar Estimate is shown instead.
- Lap times are within 2% of real reference laps (NFR-06).
- The same seed and commands reproduce the same race (FR-SIM-08).
- A Real Race can be replayed in Decision Points mode and continued in Alternate Race mode.
