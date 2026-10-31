# DEMO_HACKATHON.md — 4-minute hackathon demo (docs/HACKATHON_SCOPE.md section 8)

Rehearsed headless and in the UI on 2026-10-31 (branch `hack/demo`). Race times are
simulator seconds; at 16x one race second is 1/16 s on screen. The race is
deterministic until your first call, so the first moments are exact; after each
call, later times can move by a few seconds (the table gives the rehearsal's).

## Before going on stage (off camera, 3 min)

1. `python main.py` once and close it (compiles the kernel; the strategy workers
   load the simulator too).
2. Keep this file on a second screen. Close heavy programs: the strategy panel uses
   three background processes.
3. Optional, for instant costs in the Reveal: rehearse the race once with exactly
   the calls below. Costs are cached by race state (`data/cost_cache/`); the same
   calls at the same moments hit the cache. Otherwise they compute after the flag,
   ~5 s per call, with a progress bar (the plots show at once).

## Setup (20 s)

`python main.py`

| Field | Value |
| --- | --- |
| Track / Rule Set | Suzuka / 2026_post_miami |
| Our team / Our driver | Alpine F1 Team / GAS - Pierre Gasly (starts P13, midfield) |
| Seed | **2** |
| Race laps | 15 (default) |
| Safety Car on lap (demo) | **7** |
| Scenario | Normal race |
| Pause on alert | **on** |
| Test mode | **off** (the hidden batteries stay hidden until the Reveal) |

Start race, **16x**. Optional: tick **Driver voice** (team-radio voice, offline).

## Flow (4 minutes)

| Race time (lap) | On screen | Say / do |
| --- | --- | --- |
| 0 s | Pit wall: map, timing, Our Car battery exact, Rival radar with estimates and confidence, strategy panel "waiting for the first lap" | "We see our battery exactly. Theirs we can't see: the radar only estimates it from public telemetry." |
| ~10 s (1) | DEFEND on COL | **F1** (Defend into T1); driver: "Copy, defending T1." |
| ~105 s (1) | **ATTACK on BOR** (observed clip) | **F1**: "Attack now". This is the failed attack: BOR had more energy than we thought (the Reveal shows it). |
| ~119 s (2) | Lap 2 starts | Type in the radio box: **`save this lap, attack into turn 1 next lap`**, Enter. Driver: "Copy, saving this lap, attacking into T1 next lap." The battery climbs this lap, the attack goes in next lap. |
| ~120 s on | Strategy panel fills (refresh ~25 s, shows the lap it was computed at) | "Every lap the pit wall forks the race: stay out vs box now, +1, +2, +3, on Radar Estimates and public tyre data only. Here an early stop doesn't pay: the undercut on BOR is negative, so we stay out." |
| ~123, 218, 428 s | DEFEND on COL, ATTACK on BOR (twice) | **F1** each (fast) |
| ~320, 561 s | CLOSING-SPEED / RE-PASS RISK | **Resume** |
| **~662 s (leader lap 7)** | **SAFETY CAR** banner, amber timing column; driver: "Safety car, safety car. Box or stay out?" | Type **`box box, mediums`**, Enter. "A stop under the Safety Car is cheaper: the field is slow while we're in the pit lane." 10 to 11 Rivals box, the rest stay out (watch the Stops column). |
| ~956 s | "Safety car in this lap." | — |
| ~1103 s | Green flag: "Green flag, we're racing." Driver: "Up to P5." (rehearsal) | "We gained on the cars that stayed out." |
| ~837 / 982 / 1305 s | More ATTACK on BOR, DEFEND on LAW | **F1**, quickly |
| ~1796 s | Flag; the **Call summary** opens on the **Reveal** tab | — |

## Reveal (60 s)

- Plots for the three Rivals we raced most (rehearsal: BOR 880 s, LAW, COL): solid
  = their TRUE battery, now revealed; dashed = what our radar estimated, with its
  confidence band; vertical lines = our calls.
- Header: radar error ~1.1 MJ; **10 of 15 calls made on an estimate off by more than
  1 MJ**. Point at the first ATTACK on BOR: the error column is red.
- Cost column fills: "best call" or "your call: +3.3 s vs best option (Charge, go
  next lap)". The Safety Car stop shows a cost against "not sent": the cost looks
  2 laps ahead, so it sees the time of the stop, not the fresher tyres later. Say it.

## Graphify moment (45 s, right after the Reveal)

Every race becomes a graph of Our Car against every rival after the flag (built in
the background: the Reveal tab says "Race graph ready", then again once the costs
are in). Numbers below are the headless rehearsal with the calls above
(`python -m pitwall_sim.graph.race --simulate --seed 2 --laps 15 --our GAS --sc-lap 7`);
a live race moves a little with your exact calls.

| Time | On screen | Say / do |
| --- | --- | --- |
| 0 s | Reveal tab: **Open race dashboard** | "After the flag the whole race becomes a graph." Tiles: P5, 14 alerts (4 of 9 right per the truth), 11 calls, +8.3 s total call cost, radar error 1.11 MJ. |
| 10 s | Chord diagram: every car on the ring, YOU at the top | "Who we raced: ANT, 614 s within a second of us, then BOR and COL." Click **ANT** on the ring (or its row on the right). |
| 20 s | Rival read accuracy: ANT's bar is red (52 %), alerts right 0 of 2 | "We read ANT worst: the radar thought he was empty, 0.1 MJ. He had 2.5 MJ. Both attacks on him failed." |
| 30 s | **Open race graph** (top right); search **ANT** | Our Car in the middle, ANT in our battle group "GAS-ANT-LIN +1 battle". Click the triangle **ATTACK ANT L7 (energy)**: checked by "Truth ANT L7: true 2.5 MJ, est 0.1 -> WRONG", answered by "Call L7: Attack now", followed by "no pass". |
| 40 s | Back on the Reveal tab, **Ask the pit wall**: "Which alerts were wrong?" | "5 of 9 checked alerts were wrong", both ANT attacks among them. |

Shortcuts: `dashboard.html#car=ANT` and `graph.html#focus=ANT` open with ANT
selected. The graph is also a graphify graph:
`graphify path "GAS" "ANT" --graph graphify-out/races/live_suzuka_s2_GAS_15l/graph.json --undirected`.
Screenshots: `docs/screenshots/race_dashboard.png`, `docs/screenshots/race_graph.png`.

Close with the roadmap (HACKATHON_SCOPE section 9).

## Fallbacks

| If | Then |
| --- | --- |
| An alert is missing | Keep going: the radio message, the Safety Car and the Reveal do not depend on it. |
| The radio box ignores a message | The driver says "Say again?": use the buttons (BOX, ATTACK, PUSH / HARVEST). |
| The strategy panel is slow | Press Refresh, or skip that line; it never slows the race. |
| The live demo fails | Replay viewer on seed 2 (`python -m pitwall_sim.viewer --seed 2`), or the backup video. |
| The race graph is not ready / the browser does not open | Open the rehearsal's files directly: `graphify-out/races/live_suzuka_s2_GAS_15l/dashboard.html` (make them before going on stage with the command above, about 1 minute), or show the two screenshots. |
