# SESSION_CONTEXT — handoff for a new agent session

Last updated 2026-10-27, sprint day 9. Read this after `CLAUDE.md` when
you pick the project up in a new chat (any account, any machine). It records
what the previous sessions did and decided that the rest of the docs do not.

## WHERE THE PROJECT STANDS

| Item | State |
| --- | --- |
| Sprint | `docs/planning/SPRINT.md` (owner, deadline 2026-10-31). Days 1–9 done |
| Next | **Bug fixes only until 2026-10-31** (owner, day 9) |
| Parked until after the sprint | `T-02B`/`T-02C`/`T-02D`, `T-038`, `T-062`, R3–R5 |
| Demo | `docs/guides/DEMO.md` (3-minute script, rehearsed), README intro + screenshot + baseline results |
| Gates | ruff check, ruff format --check, mypy strict (`pitwall_sim`), lint-imports (4 contracts), pytest -q: all pass on a clean venv (day 9) |

## OWNER WORKING RULES (from the chats, on top of `CLAUDE.md`)

- Commit + push every finished step without asking, gates green. Tested work
  that misses a target may be committed with `(WIP)` / `(BLOCKED)` in the message.
- Push: `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git push -q origin main`.
  Never force-push without asking.
- Don't ask about placeholders or calibration. Ask only if blocked.
- **Never use Ground Truth to tune the Radar.**
- Owner decisions arrive as "OWNER ANSWERS — ROUND N".
- Every report: before/after numbers, exact commands, screenshot in
  `docs/screenshots/dayN_*.png`.

## WHAT EACH SPRINT DAY BUILT

| Day | Items | Main files |
| --- | --- | --- |
| 1 | `S-2` replay viewer | `pitwall_sim/viewer/` |
| 2 | `A-1` alert provider (`simply_clipping_lite`), `A-5` tests | `pitwall_sim/observe/alerts.py`, `observe/alerts_check.py` |
| 3 | `S-5` live pit wall lite, `A-3` alert panel, `A-2` call options | `pitwall_sim/live/session.py`, `ui/pitwall_lite.py`, `engineer/calls.py` |
| 4 | Alert quality fixes, overtake ATTACK term, `A-4` call summary, `A-6` presets | see below |
| 5 | Persistent ATTACK / DEFEND calls, alert branches (observed clip, own battery), Radar start prior, README | see DAY 5 |
| 6-7 | HOLD variant B, rivals see Our Car, `S-1` export, `S-3` scorer, `S-4` batch | `pitwall_sim/export/`, `evaluate/` |
| 8 | Test bench + hello-world plug-in, baseline table | `pitwall_sim/bench/`, `docs/examples/`, `docs/results/SC_RESULTS.md` |
| 9 | Demo package: `docs/guides/DEMO.md`, README, setup-screen Race laps | see DAY 9 |

## DAY 4 DETAILS

**Step 1 — Radar.** A rival's estimate is "unknown" (confidence 0, NaN in traces)
until its first anchor; `radar.confidence_half_life_s` 120 → 300.
Seed 42: median confidence 0.000 → 0.003, mean 0.059 → 0.089, known 100% → 61%,
≥0.4 6% → 8%. Anchors come only 1–2 times per car, mostly after ~2300 s.

**Step 2 — alerts.** `alerts.min_confidence` 0.4 (below: no alert),
`low_confidence` 0.6 (greyed), `hold_s` 1.0 hysteresis, ATTACK/DEFEND only for
same-lap pairs, CLOSING only with Our Car. Seed 42 counts (ATT/DEF/REPASS/CLOSE):
VER 26/1/1/28 → 2/0/1/0; GAS 22/1/14/24 → 5/1/14/1.

**Step 3 — overtake weights (target NOT met).** Added `w_attack` to the pass
logit (`race/overtake.py`, engine passes `ins.defend`, `ins.attack`). Kept
weights `w_dv_per_ms 0.30, w_overtake_mode 1.5, w_defend 2.5, w_attack 2.5`,
marked `# GAMEPLAY-TUNED (sprint), recalibrate in T-02C`. 75 overtakes/race
(was 128). Paired forks, 20 seeds × 5: ATTACK +8 points (9% vs 1%), DEFEND −10
(10% vs 20%, 2 alerts). Target was +20 for both. Why weights can't reach it:
after most ATTACK alerts Our Car never gets within the 20 m attempt range;
DEFEND only lasts to the next corner while its PUSH costs energy.
The structural change was approved and made on day 5 (below).

**Step 4.** `live/presets.py`: Re-pass scenario (Our Car P10, 2.0 MJ, PUSH +
ATTACK; the car ahead starts empty) and Closing-speed scenario (Our Car P14;
P7–P9 start empty); both fire within 3 laps. `LiveSession.summary()` →
`CallSummary` (option/ignored/expired, outcome over 2 laps, Test-mode truth);
UI `SummaryDialog` opens at the flag. Short races show almost no ATTACK/DEFEND
rows because Radar confidence stays below 0.4 until anchors arrive.

## DAY 5 DETAILS

**Calls last until the situation is over** (`race/engine.py`): DEFEND until the
car behind is > `engineer.defend_clear_gap_s` 1.0 s back or has passed, at most
`engineer.call_max_laps` 2 laps; inside line, deploy only in acceleration zones
(`DriverInstructions.keep_deploy`); option [1] is DEFEND(corner) only. ATTACK
until a pass or 2 laps: PUSH (previous mode restored), PUSH_LAP grip margin
(`follow_close`), Overtake mode when available. Rival AI flags never set
`follow_close` / `keep_deploy`: races without calls are unchanged (overtakes
73 / 101 / 51, mean 75).

**Alert branches** (`observe/alerts.py`): ATTACK (a) energy, (b) observed clip
gated by detection share (feed samples on that straight) >= 0.7; DEFEND (a)
energy, (b) own battery (zone cap x our time on the coming straight > our
battery - 0.3 MJ, car behind not seen clipping). "Seen clipping" = Radar CLIP
for >= `alerts.clip_min_s` 1 s on a straight (single CLIP samples are partial
deployment). Evidence names the branch; headline/radio follow it.

**Radar start prior**: 4 MJ, confidence 0.5 decaying from the first frame;
anchors replace it; label "assumed full at start". Rival AI does NOT read it
(`energies(with_prior=False)`): read by rivals, overtakes rose 75 -> 128.

**Numbers (seed 42 / 20 seeds x 5 forks):** alerts VER 28 (ATT 20, DEF 8),
GAS 34 (ATT 25, DEF 8, REPASS 1; target <= 30 missed by 4). ATTACK +26
(33 % vs 7 %), DEFEND +52 (85 % vs 33 %); from lap 5: +27 / +12. Radar median
confidence 0.005 -> 0.026, known 66 % -> 100 %. Test mode: observed-clip ATTACK
right only 30-55 %, own-battery DEFEND 67-75 %, energy ATTACK 33-50 %.

**Found, not fixed (owner decision):** HOLD_POSITION does not stop overtake
attempts (TRD says it should). Rivals hold whenever they are in a battle and not
attacking, so a fix changes the race balance: a rough check (holding cars hidden
from the overtake stage) gave 41 / 65 / 53 overtakes instead of 73 / 101 / 51,
and the day 5 call numbers would need re-measuring.

## DAY 6 (2026-10-27) — owner plan in docs/planning/SPRINT.md Parts 3-5

- **HOLD_POSITION fix: NOT on main (owner decision pending).** Branch
  `wip/hold-position`: commit `a0a420a` = HOLD stops every car's attempts
  (overtakes 75 -> 80.7 on 3 seeds, 85.6 on 5; ATTACK +27; DEFEND +0, because
  rivals never see Our Car in the feed, treat it as level and HOLD); with rivals
  also seeing Our Car DEFEND is only +3. Commit `df2171a` = only the engineer's
  HOLD stops Our Car's attempts (rival "hold" = not attacking): overtakes
  unchanged 73/101/51, call numbers unchanged.
- **S-1 export** (`pitwall_sim/export/`, commit `a03b5a7`): FastF1-like feed,
  10 Hz truth, events, car_params, run.json; scenarios normal, battles, repass
  (NOR/HAM scripted for 4 laps), closing_speed (BEA behind empty COL), taper,
  cda_trap. Use full races (short races make the Rival Strategy pit on lap 1).
- **S-3 scorer** (`pitwall_sim/evaluate/`, `5dcc7fa`): contract in
  docs/spec/SIMPLY_CLIPPING_BRIDGE.md; baselines = built-in Radar on the exported
  feed + recorded built-in alerts + dumb ATTACK rule. Seed 42 normal: built-in
  energy MAE 0.89 MJ, CLIP precision 4 %, ATTACK right 36 % (clip branch 29 %),
  DEFEND right 50 %; incident checks fail for the built-in alerts.
- Next: day 7 = Simply Clipping v0 package, live plug-in, S-4 batch (seeds 1-5
  tune, 6-10 test), docs/results/SC_RESULTS.md.

## DAY 7 (2026-10-27)

- Owner day-6 answers (docs/planning/SPRINT.md has the plan): HOLD variant B merged
  (`3f0fc92`); **Rivals see Our Car in the Public Feed** (`799d4d9`): ATTACK
  call +26 -> +12, DEFEND +52, overtakes unchanged; the Re-pass preset's ATTACK
  now uses follow_close (all 6 tested cars get RE-PASS RISK in 3 laps).
- **Simply Clipping v0** (`19fe02d`, live `2a90d09`, batch driver `30daa58`):
  `simply_clipping/` package, own track file (`tracks/suzuka.json` from
  `python -m pitwall_sim.export.sc_track`), offline CLI
  `python -m simply_clipping.run`, live plug-in (setup screen "Alert engine").
  Import contracts: it never imports pitwall_sim, the sim never imports it.
- **S-4 batch** (`470ebab`): `python -m pitwall_sim.export --batch 5 --scenario all
  --out data/exports/batch` (resumable, rewrites docs/results/SC_RESULTS.md per run);
  overnight pipeline (scratchpad `overnight.ps1`, log
  `data/exports/batch/overnight.log`): seeds 1-5 export -> SC v0 -> score ->
  seeds 6-10 export -> SC v0 -> score. Don't run timing tests while it runs.
- Repass scenario: seeds 1, 2, 3 produce the target (seed 42 does not): use one
  of them for the demo (owner).
- Next: day 8 = Simply Clipping v1 from the tune-set scores; real Japanese GP check.

## DAY 8 (2026-10-27) — CHANGE OF PLAN (owner)

- **The owner builds Simply Clipping.** The agent's package is removed
  from main and kept on branch `archive/sc-v0` (tag `sc-v0` = v0; the branch's
  last commit = the cancelled v1 work in progress). No setup-screen alert-engine
  option; the generic plug-in stays (`alerts.provider: external:<module>`).
  Day 8 v1 work and the real Japanese GP check are cancelled.
- **Test bench** (`pitwall_sim/bench/`): `python -m pitwall_sim.bench
  --sc-module <module> --scenario all --seeds 6-10`; the plug-in provides
  `run(feed_dir, out_dir, our, own_file, layout_file)` (offline) and
  `create(cfg, track)` (live). Template: `docs/examples/hello_clipping.py`.
  Contract: docs/spec/SIMPLY_CLIPPING_BRIDGE.md. Track layout file:
  `python -m pitwall_sim.export.layout`.
- docs/results/SC_RESULTS.md = the baseline table (built-in, dumb rule) from the
  overnight batch.
- Day 9 = demo package for the SIM (pit wall, alerts, call summary, scorer on
  the built-in baseline); 2026-10-31 bug fixes only.

## DAY 9 (2026-10-27) — demo package

- `docs/guides/DEMO.md`: 3-minute script (GAS, seed 42, Race laps 3, Test mode, pause
  on alert: DEFEND COL ~9 s, ATTACK BOR ~60-100 s, call summary at the flag;
  presets at full distance: RE-PASS RISK on LIN ~60 s, CLOSING-SPEED RISK on ALO
  ~91 s; bench on hello_clipping), with fallback seeds.
- Setup screen: **Race laps** (1-53; 53 = the full race). Presets need the full
  distance (in a short race rivals push from lap 1).
- Bench report covers only the bench's own runs; a plug-in with no alerts scores
  recall 0 (not NaN).
- Every README / DEMO command checked on a fresh clone + clean Python 3.13 venv
  (`pip install -e ".[dev]"`); bench on a fresh machine ~2 min (it exports the
  race first), ~4 s afterwards.
- After day 9: bug fixes only until 2026-10-31 (owner).

## SIMPLY CLIPPING (2026-10-30, branch `simply-clipping`)

- `t-rex` (docs moved into `docs/spec|planning|status|guides|results/`) merged
  into main locally (`1b0b5c2`); branch `simply-clipping` made from it.
- Owner: "START SIMPLY CLIPPING — my own project, built as a plug-in". SC-0
  done: `docs/spec/SIMPLY_CLIPPING_SPEC.md` (rules SC-R01…R08, lessons L-a…L-f,
  targets from SC_RESULTS test set), `simply_clipping/` scaffold (all constants
  in `config.yaml`; stubs name their SC task), import contracts both ways (6
  contracts), TASKS block SC (SC-1…SC-7 provisional until the owner's prompts).
- Scaffold on the bench (normal, seed 6): energy MAE 1.18 MJ, no alerts — same
  as hello_clipping. Tune on seeds 1-5, report 6-10; never read truth/.
- Open: O-1 meaning of "right" for honest confidence (proposed |err| ≤ 0.5 MJ).

## SIMPLY CLIPPING SC-1 … SC-6 (2026-10-30, branch `simply-clipping`)

- Owner prompts SC-1 … SC-6 done, each its own commit; tag `sc-v1` = SC-4 config.
  Spec `docs/spec/SIMPLY_CLIPPING_SPEC.md`; tuning log `docs/results/SC_TUNING.md`;
  results `docs/results/SC_RESULTS.md` (Simply Clipping column + REAL RACE);
  demo `docs/guides/DEMO_SC.md`.
- Test set (once): energy MAE 0.36-0.88 vs 0.84-1.28 MJ; confidence ECE 4-10 vs
  18-34 %; CLIP precision 53-66 vs 4-6 % (recall 19-27 vs 35-41 %); repass
  incident 67 vs 33 %. Not beaten: normal ATTACK precision (0 vs 8 %), closing
  incident (0 vs 0 %, spec O-3: the rule needs DEPLOY, the events are braking).
- Real 2026 Japanese GP (OpenF1 11253): NOR/HAM re-pass caught twice (15 s, 20 s
  lead); BEA/COL lap-22 crash not caught (BEA's speed channel frozen).
- Open for the owner: O-1 (0.5 MJ "right"), O-3 (closing rule vs target).
- Live: `alerts.provider: external:simply_clipping` in config/app.yaml (the repo
  default stays the built-in).

## HACKATHON (2026-10-30/31, branch `hack/demo`, docs/HACKATHON_SCOPE.md)

Sessions 1-9 of the owner's plan, one commit each:
1 data contracts (TrackStatus, RadioEvent, CallRecord + snapshots, CallCost,
StrategyResult; `engineer/records.py`); 2 Safety Car / VSC (H4); 3 Reveal tab
(H1); 4 radio keyword parser (H2, offline); 5 buttons, sim-behind, weather,
15-lap default, overtake difficulty GAMEPLAY-TUNED (8 passes / 15 laps after lap
1; real Japanese GP ~5), 16x clock fix; 6 decision costs (paired forks, cache);
7 strategy panel (background processes, barrier test); 8a unprompted driver
radio, 8b offline driver voice (Windows SAPI + team-radio filter); 9 demo seed 2,
`docs/guides/DEMO_HACKATHON.md`. Not done: 8c hosted LLM (only an OpenAI key on
the machine: owner decides the provider), 8d voice input (faster-whisper not
installed). Known: no undercut window in 15-lap races (tyre wear placeholders
too low); strategy refresh ~25 s (stale by ~3 laps at 16x); 16x frames p99
~30-110 ms with the strategy workers and the post-flag cost thread.

2026-10-31, branch `hack/features` (from main `f08cf4f`; four parallel builds,
merged): **H2/H3** hosted LLM radio + LLM driver replies (`radio/hosted_llm.py`,
`llm_commands.py`, `llm_replies.py`, `live/radio_ai.py`; config `radio_llm`, provider
`null` = off until the owner picks OpenAI or Anthropic and sets the key env var;
LLM → `validate()` → queue, 2 s timeout → keyword parser) and push-to-talk
(`radio/stt.py`, faster-whisper `base.en` in `models/stt`, hold `` ` ``; config
`voice_input`; extras `[llm]`, `[voice]`). **H6** Telemetry tab (speed, throttle,
battery vs lap distance, previous-lap ghost; `ui/telemetry_plot.py`). **E1** rain race
("Rain from lap" on setup → `rain_lap`; Rivals box for inters 0-2 laps after the
crossover; WET never beats INTER with the `tyres.yaml` placeholders) and **T-038**
overtake contact (`race_events.contact_*`, HAND-SET; LIGHT / VSC / SC). **E2** engineer
score in the Reveal (`debrief/scorer.py`, `100·exp(−Σloss/score_scale_s)`). **E3** real
race moment (`replay/real_race.py`, OpenF1 session 11253, "Real race moment" + lap on
setup, `python -m pitwall_sim.replay.real_race --lap 30 --our NOR`; "lap N" = the
leader starting lap N, owner to confirm; config `real_race`, HAND-SET hidden state).
Fix: no strategy refresh / Reveal sampling after the chequered flag (found in the
owner's live run, `data/runs/live_20261031_s42_VER_l15/NOTES.md`). Pitch:
`docs/PITCH.md`. Still open: LLM provider + key, H8 backup video, lapped-car rule.

Owner asked the agent to choose (2026-10-31): E3 "lap N" stays = the leader starting
lap N (F1 timing convention, "LAP 30/53"). Tyre model checked: no bug (dry, laps 3-4
before any stop, seeds 1-3: SOFT 0.051, MEDIUM 0.032, HARD 0.022 wear/lap; the "HARD
faster than MEDIUM" reading mixed in post-stop compounds), so `real_race.wear_per_lap`
was corrected to those values. Lapped-car rule: not built (nobody is lapped in a
15-lap race or from lap 30). WET tyres: left to calibration (HR-09; INTER beats WET
with the placeholders). Checks kept under `data/runs/_tools/` (gitignored):
`rehearse_demo.py` (headless DEMO_HACKATHON run, matched the script) and
`ui_smoke.py` (setup screen → pit wall, 4 scenarios, 22 checks, all OK).

## GRAPHIFY TRACK (2026-10-31, main, repo `Dronzer2code/simply-clipping`)

Owner prompt "GRAPHIFY TRACK - race comparison graphs" (replaced the earlier graphify
prompt). Steps G-1…G-4, one commit each. Spike (step 0): graphify 0.9.96 (`graphifyy`,
a uv tool, not importable) runs `query / path / explain --graph <file>` on a graph.json
we write; its `graph.html` loads vis-network from unpkg (no internet at the venue),
drops custom node fields and colours by community; `cluster-only` re-clusters (our
battle groups lost). So: graph.json in graphify's schema, our own offline viewer and
report, graphify for questions.

- `pitwall_sim/graph/`: `record.py` (RaceRecord from a finished live session or an
  export; battles = the Reveal's rule for every pair; truth checks = Test mode's rule;
  refuses before the flag), `race_graph.py` (graph.json, labels.json, race_report.md,
  graph.html), `dashboard.py` (dashboard.html: tiles, chord, rival read accuracy),
  `ask.py` (presets + `graphify query`), `race.py` CLI (`--run`, `--simulate`).
  vis-network 9.1.6 + d3 7.9.0 vendored in `graph/vendor/`.
- Reveal recorder also keeps public order/intervals, true speeds and each alert's true
  battery, released after the flag only (`LiveSession.reveal_samples`).
- UI: Reveal tab "Open race graph" / "Open race dashboard" / "Ask the pit wall"
  (`ui/race_graph_panel.py`, QThreads; rebuilt once the costs are in).
- Demo (seed 2, 15 laps, SC lap 7, the demo's calls): P5, 14 alerts (4/9 right),
  11 calls, +8.3 s, radar MAE 1.11 MJ; main rival ANT (614 s, radar MAE 1.91 MJ, both
  ATTACKs wrong: est 0.1 vs true 2.5 MJ). Script: DEMO_HACKATHON "Graphify moment".
- Choices made by the agent: closing-speed incident = car behind faster by
  `alerts.closing_dv_kmh`, car ahead at least 150 km/h and not braking (> 40 km/h drop
  per second) (samples carry no energy states); led_to confidence = 0.5 + 0.45 (1 -
  exp(-|cost| / 2 s)); battle groups = heaviest battle pairs first, at most 5 cars,
  battles of 5 s and more; estimate accuracy = 1 - MAE / 4 MJ (owner's formula).

## KNOWN ISSUES

- Full race distance: every car runs out of fuel at laps 41-46 of 53 (DNF "out
  of fuel"; `fuel_start_kg` 70 kg is a placeholder). Parked as `T-02B` (race
  fuel calibration). The demo uses a 3-lap race and the first laps of the presets.

- Timing tests (`test_headless_runtime`, `test_step_kernel` budget, UI 16x
  frame time) fail when the machine is loaded; they pass when it is idle.
- Radar after the first anchor: MAE ≈1.44 MJ, bias −1.41 MJ (anchors on
  super-clips). Not tuned (rule above).
- 5 config keys still `UNRESOLVED`/`UNKNOWN` (logged at start-up).

## COMMANDS

```bash
python main.py                                    # setup → Scenario → Start
python -m pitwall_sim.observe.alerts_check --seed 42 --our GAS
python -m pitwall_sim.engineer.call_outcome --type DEFEND --seeds 20 --variants 5
python -m pitwall_sim.engineer.call_outcome --overtakes 3
python -m pitwall_sim.bench --sc-module docs.examples.hello_clipping --scenario normal --seeds 6
pytest -q; ruff check .; ruff format --check .; mypy pitwall_sim; lint-imports
```
