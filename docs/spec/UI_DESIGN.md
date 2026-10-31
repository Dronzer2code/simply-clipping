# UI_DESIGN.md — Pit Wall Race Simulator (2026 Regulations)

## PURPOSE

This document defines the desktop UI of `pitwall_sim`: screens, layout, panels, data sources, colours, interactions and UI states.
It applies to everything in `pitwall_sim/ui/`.

Feature IDs come from `docs/spec/PRD.md`. Data objects (`EngineerView`, `RadarEstimate`, `RadioMessage`, `DebriefReport`, `EngineerCommand`) are defined in `docs/spec/TRD.md` DATA CONTRACTS. Runtime refresh behaviour is in `docs/spec/PROCESS_FLOW.md` PF-05.

## CONTEXT

The user is a race engineer for one car (Our Car) on the pit wall. The screen MUST be readable at a glance during `16x` playback. Our Car data is exact. Rival battery data is an estimate with a confidence value and MUST always look like an estimate.

## CONSTRAINTS

- MUST use PySide6 widgets and pyqtgraph for plots and the track map.
- MUST read only `EngineerView` during a race (HR-02 in `CLAUDE.md`).
- MUST refresh at 10 Hz and keep every frame ≤ 100 ms at `16x` (NFR-03).
- MUST NOT run simulation, radar, predictor or LLM work on the UI thread.
- MUST use team colours from `config/grid/<grid>.yaml` `color_hex`, never hard-coded team colours.
- MUST NOT convey identity by colour alone. Several 2026 teams are close in
  colour (Ferrari and Audi are both red; Haas and Cadillac are both light), so
  every car marker, timing row, trace and legend MUST carry the driver `code`
  and, where space allows, the team label beside the colour (owner decision
  2026-10-19). This also keeps the UI readable for colour-blind users.
- MUST fall back to `app.yaml: ui.fallback_palette` for any team whose
  `color_hex` is missing, assigning entries in grid order.
- MUST take the window title from `app.yaml: ui.window_title`
  ("We Are Racing, Not Testing"), never a hard-coded string.
- Dark theme only (pit wall convention). Light theme: out of scope.
- Target resolution: design for 1920×1080; MUST remain usable at 1366×768. Actual target display: UNKNOWN.

## SCREENS

| Screen ID | Screen | Release | Feature |
| --- | --- | --- | --- |
| S1 | Race Setup | R1 | F03, F15, F19 |
| S2 | Pit Wall (main race screen) | R1 (some panels R2/R3) | F15 |
| S3 | Debrief | R3 | F16 |
| S4 | Compare Mode Setup | R4 | F17, F18 |
| S5 | Compare Decision Point overlay | R4 | F17 |
| S6 | Calibration Report viewer | R1 (developer screen, MAY be minimal) | F20 |

## S1 RACE SETUP

```text
┌───────────────────────────────────────────────────────────┐
│  MODE      (•) New Race  ( ) Compare: Decision Points (R4) │
│                           ( ) Compare: Alternate Race (R4) │
│  TRACK     [ Suzuka                  ▼ ]  (UNAVAILABLE greyed) │
│  RULE SET  [ 2026_post_miami         ▼ ]                   │
│  GRID      [ real_2026               ▼ ]                   │
│  OUR CAR   [ team ▼ ] [ driver ▼ ]   (user's favourite)    │
│  WEATHER   [ Dry ▼ ]  (R2: Dry / Mixed / Wet / Random)     │
│  SEED      [ 42 ]  [ random ]                              │
│  LAPS      [ full distance ▼ ]  (full / 50% / 25%)         │
│  HARVEST   [ 8.5 ] MJ/lap  (track override → Rule Set)     │
│                                   [  START RACE  ]         │
└───────────────────────────────────────────────────────────┘
```

- `START RACE` disabled until validation passes (PF-03): Rule Set has no runtime `UNRESOLVED` values, track available, Our Car in grid.
- Validation errors shown inline under the field.
- Race distance options are a structural UI choice; `full` is default.
- `HARVEST` ("Harvest limit (MJ/lap)"): race harvest limit per lap. Pre-filled from the track's `harvest_max_mj_per_lap_race` override, else the Rule Set default; re-filled when track or Rule Set changes. The user MAY edit it before the start; it MUST be > 0. Overtake extra energy is added on top in race. Locked once the race starts.

## S2 PIT WALL LAYOUT

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR: LAP 23/53 │ FLAG GREEN │ ☁ DRY 24°C │ 2026_post_miami │ ⏸ 1x 4x 16x │ sim-behind ● │
├───────────────┬──────────────────────────────────────┬───────────────────────┤
│               │                                      │  OUR CAR STATUS        │
│  TIMING       │          TRACK MAP                   │  battery 2.31 MJ ████▒ │
│  TOWER        │   (all cars, Our Car highlighted,    │  mode BALANCED         │
│               │    zones, SC position)               │  overtake: AVAILABLE   │
│  P  DRV GAP   │                                      │  tyre M 14L wear 38%   │
│  INT TYRE AGE │                                      │  fuel 61.2 kg          │
│  LAST S1 S2 S3│                                      ├───────────────────────┤
│  RADAR ●      │                                      │  RIVAL RADAR           │
│               │                                      │  ahead  NOR ~1.4 MJ 0.7│
│               │                                      │  behind HAM ~2.9 MJ 0.4│
├───────────────┴──────────────────────────────────────┼───────────────────────┤
│  TELEMETRY TRACES (Our Car vs ahead / behind)        │  STRATEGY (R2)         │
│  speed │ throttle │ brake │ battery (ours exact,     │  pit window L24–L28    │
│  rivals = Radar Estimate band)                       │  undercut +1.2 s       │
├──────────────────────────────────────────────────────┼───────────────────────┤
│  COMMAND BAR                                         │  RADIO                 │
│  [PUSH][BALANCED][HARVEST] [OVERTAKE ✓/✗] [LIFT&COAST]│  log + text input (R3) │
│  [BOX ▼ lap ▼ compound] [CANCEL BOX] [DEFEND ▼ corner]│                        │
│  [ATTACK][HOLD][LET BY][PUSH LAP ▼][MANAGE TYRES]    │                        │
└──────────────────────────────────────────────────────┴───────────────────────┘
```

Proportions (structural default): left 20%, centre 50%, right 30%; top region 55% height, traces 25%, command/radio 20%. Panels are `QDockWidget`s so the user MAY rearrange; layout saved in `QSettings`.

## PANEL SPECIFICATIONS

| Panel | File | Data source (`EngineerView` field) | Release |
| --- | --- | --- | --- |
| Top bar | `ui/window.py` | `t_s`, `timing`, `flag`, `weather_public` | R1 (weather R2) |
| Clock controls | `ui/clock.py` | local clock state | R1 |
| Timing tower | `ui/timing_tower.py` | `timing`, `radar` (indicator dot) | R1 |
| Track map | `ui/track_map.py` | `timing` positions, `rival_feed` x/y, `our_car` | R1 |
| Our Car status | `ui/window.py` (status widget) | `our_car` | R1 |
| Rival radar | `ui/radar_panel.py` | `radar` | R1 |
| Telemetry traces | `ui/telemetry_plot.py` | `our_car` history, `rival_feed`, `radar` | R1 |
| Strategy | `ui/strategy_panel.py` | `predictor` | R2 |
| Command bar | `ui/command_bar.py` | emits `EngineerCommand` | R1 |
| Radio | `ui/radio_panel.py` | `radio_log`; text input emits to LLM worker | R1 log + template acks; R3 text input |
| Debrief | `ui/debrief_view.py` | `DebriefReport` + post-race Ground Truth | R3 |

### Timing tower

| Column | Source | Format |
| --- | --- | --- |
| P | position | integer |
| DRV | driver `code` | 3 letters, team colour bar on left |
| GAP | gap to leader | `+12.345`; leader shows `LEADER`; lapped `+1L` |
| INT | interval to car ahead | `+0.812`; ≤ 1.0 s highlighted (Overtake mode range) |
| TYRE | compound | letter in compound colour: S red, M yellow, H white, I green, W blue |
| AGE | tyre age laps | integer |
| LAST | last lap time | `1:32.456` |
| S1 S2 S3 | sector times | MAY be hidden at width < 1600 px |
| ● | Radar state of that Rival | colour of `RadarEstimate.state`; hollow when confidence < 0.5 |

Our Car row: blue background tint. Rows animate position changes over 300 ms.

### Track map

- Track centre line from `data/tracks/<track_id>.parquet`, drawn once as a static `PlotDataItem`.
- Zones drawn as coloured overlays: straight-mode zones thin grey, overtaking zones dashed green, detection points small ticks, pit lane dotted.
- Cars: circles in team colour, driver code label; Our Car larger with blue ring.
- Rivals plotted from `rival_feed` x/y (noisy) — positions MAY jitter slightly; this is intended.
- Safety Car shown as an amber "SC" marker (R2).
- Click a car → that car becomes the comparison target in telemetry traces.

### Our Car status

- Battery: numeric MJ (2 decimals) + horizontal bar from 0 to `e_usable_max_mj`. Exact value, solid fill.
- Per-lap counters: harvested / deployed this lap vs limits.
- Energy Mode, Overtake availability (`AVAILABLE` / `ACTIVE` / `UNAVAILABLE`), aero mode.
- Tyre: compound, age, wear %, temperature (R2 if simplified in MVP).
- Fuel kg, damage indicator (R2), penalties, track-limits warnings (R2).
- Active instructions list (e.g. `DEFEND T1`, `BOX L24 M`).

### Rival radar

- Two fixed rows: car ahead and car behind. Optional pinned extra Rivals (click in timing tower → pin).
- Each row: driver code, `~X.X MJ` (tilde always shown), state chip, confidence 0.00–1.00, last clip location (corner id).
- Estimate bar drawn as a hatched/translucent band, never a solid fill (visually distinct from Our Car's exact battery).
- Confidence < 0.5 → row greyed.
- Delta line: `you +0.9 MJ vs NOR` (our exact − rival estimate).

### Telemetry traces

- Four stacked plots sharing x axis (distance in lap, m): speed (km/h), throttle (%), brake (on/off), battery (MJ).
- Our Car: solid blue line. Comparison car: team colour dashed line. Battery plot for Rival shows Radar Estimate as a band (±(1−confidence)·1 MJ, structural default).
- Window: current lap + previous lap ghost (30% opacity).
- Update via `setData` only; MUST NOT recreate plot items per frame.

### Strategy (R2)

- Pit window bar across lap axis (green span).
- Undercut / overcut gain vs car ahead and behind (seconds, signed).
- Tyre wear forecast line per plan.
- Finishing position distribution per candidate plan (small horizontal bars).
- "Recompute" button; shows spinner while predictor worker runs.

### Command bar

- Buttons map 1:1 to `CommandType` in `docs/spec/TRD.md` ENGINEER COMMANDS.
- Active Energy Mode shown as toggled button.
- `BOX` requires lap + compound selection; button text shows pending box (`BOXING L24 M`) and `CANCEL BOX` enabled only while pending and before pit entry.
- `DEFEND` dropdown lists `corner_id` values from track config; default "next braking zone".
- Rejected command → red flash on button + reason in radio panel.
- Keyboard shortcuts in table below.

### Radio

- Chat-style log: ENGINEER right-aligned, DRIVER left-aligned, timestamps in lap + race time.
- Fallback/template messages marked with a small `T` badge.
- R3: single-line text input + send (Enter). Message appears instantly; driver reply fills in when ready; "…" indicator while LLM worker runs.
- R3: if model not loaded yet, input enabled but status shows `radio model loading` and messages queue.

## COLOURS

| Token | Hex (structural default) | Use |
| --- | --- | --- |
| `bg` | `#101214` | window background |
| `panel` | `#181B1F` | panel background |
| `text` | `#E6E8EB` | primary text |
| `text_dim` | `#8A9099` | secondary text, low confidence |
| `our_car` | `#3D8BFF` | Our Car highlight |
| `deploy_attack` | `#2ECC71` | DEPLOY state, ATTACK, pit window |
| `defend` | `#F5A623` | DEFEND, VSC, SC |
| `clip_risk` | `#FF4D4F` | CLIP state, risk, rejected command, red flag |
| `harvest` | `#00B8D9` | HARVEST state |
| `lift` | `#B37FEB` | LIFT state |
| `cruise` | `#8A9099` | CRUISE state |

Semantic meanings match the Rival Battery Radar project (green = DEPLOY/ATTACK, amber = DEFEND, red = CLIP/RISK, blue = Our Car). Colour MUST NOT be the only signal: state chips also carry text.

Font: system UI font; numbers in a monospace font (e.g. `JetBrains Mono` if installed, else system monospace) so columns align. Base size 12 pt; timing tower 13 pt.

## KEYBOARD SHORTCUTS

| Key | Action |
| --- | --- |
| `Space` | Pause / resume |
| `1` / `2` / `3` | Clock `1x` / `4x` / `16x` |
| `P` / `B` / `H` | Energy Mode PUSH / BALANCED / HARVEST |
| `O` | Toggle overtake permission |
| `L` | Toggle lift-and-coast |
| `D` | DEFEND next braking zone |
| `A` | ATTACK |
| `X` | BOX next lap, keep current compound selection |
| `Esc` | Cancel BOX (if allowed) |
| `/` | Focus radio input (R3) |

## UI STATES

| State | Display |
| --- | --- |
| Paused | Top bar `PAUSED`, traces frozen, commands still accepted (take effect after resume, PF-05) |
| Sim behind | Amber dot + tooltip "sim running at Nx effective" (HR-08) |
| VSC / SC / Red flag (R2) | Full-width banner under top bar in `defend` / `clip_risk` colour; timing tower shows `SC` deltas |
| Rain onset (R2) | Top bar weather icon changes + radio trigger |
| Our Car in pit | Status shows pit phase from PF-12 state machine |
| Our Car DNF | Panels greyed; banner `DNF — lap N`; option to continue watching or go to debrief |
| Chequered | Banner + button `OPEN DEBRIEF` (R3) / `BACK TO SETUP` (R1) |
| Radio model loading (R3) | Radio header status text |

## S3 DEBRIEF (R3)

```text
┌───────────────────────────────────────────────────────────────┐
│ RESULT P6 (+2 vs grid)          SCORE 74/100      seed 42       │
├───────────────────────────────────────────────────────────────┤
│ DECISION TIMELINE (lap axis, markers per Decision Point,        │
│  colour by loss: green ≤ 0.5 s, amber ≤ 3 s, red > 3 s)         │
├──────────────────────────────┬────────────────────────────────┤
│ SELECTED DECISION            │ GROUND TRUTH vs RADAR            │
│ L24 BOX M (yours)            │ battery traces of all cars       │
│ best: BOX L26 H  (−3.4 s)    │ (truth solid, radar estimate     │
│ explanation text             │  dashed) for selected lap range  │
└──────────────────────────────┴────────────────────────────────┘
```

Ground Truth for all cars is shown ONLY here (PF-06 barrier rule).

## S4 / S5 COMPARE MODE (R4)

- S4: Real Race picker (cached races listed, others with `download` action), Our Car picker, mode (Decision Points / Alternate Race + start lap).
- S5 overlay on S2 at each Decision Point: dims the screen, shows "Decision Point: lap 18, SC deployed", accepts commands, `CONFIRM` button, then reveals real team's call and next 3 laps of real outcome side by side with an optional `PLAY MY VERSION` (launches Alternate Race from this point).

## OPEN ITEMS

| Item | Status |
| --- | --- |
| Target display resolution | UNKNOWN |
| Product name for title bar | RESOLVED 2026-10-19 — "We Are Racing, Not Testing", from `app.yaml: ui.window_title` |
| Logo for title bar | UNKNOWN |
| Team colour hex values | FastF1 3.8.3 plotting constants (2026, `official`), marked `# SOURCE: fastf1 3.8.3 plotting constants (2026)` in `config/grid/real_2026.yaml` (owner decision round 3) |
| Final colour palette approval | Accepted as-is (owner decision round 3): structural defaults above; team colours from FastF1 3.8.3 plotting constants (2026) via the grid file. Identity never by colour alone |
