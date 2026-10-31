# IMPROVEMENTS.md: hackathon showcase review (2026-10-31)

A review of the code, the docs and three live checks: the owner's run (seed 42), a
headless rehearsal of `DEMO_HACKATHON.md`, and a UI smoke test of `main.py`. Nothing
here is built yet. Each item says what to change, where in the code, and why it
helps the judges. Items are ordered by value for the demo.

## 1. Simply Clipping today

| Part | What it does | Where |
| --- | --- | --- |
| Signal pipeline | Resamples public speed data to 10 Hz with no interpolation over gaps, smooths it (Savitzky-Golay 7/2), computes acceleration | `simply_clipping/physics.py` |
| Power model | Wheel power from mass (including falling fuel), drag and rolling resistance; electric power = wheel power / η − ICE power per maker | `physics.py` |
| Drag (CdA) fit | Per car and aero mode, from full-throttle runs with partial deploy allowed (lesson L-c) | `physics.py` |
| States | DEPLOY / CLIP / HARVEST / LIFT / CRUISE per point; the speed taper is never read as a clip (L-b) | `simply_clipping/energy.py` |
| Energy estimate | Integrates harvest − deploy within the lap limit; an EMPTY anchor only on the real "ran out" pattern, not on super-clips (L-a) | `energy.py` |
| Confidence | From time since the last anchor, missing data and fit quality, calibrated on seeds 1-5 so that 0.8 means right about 80 % of the time (L-e) | `energy.py`, `config.yaml` |
| Alerts | ATTACK, DEFEND, RE-PASS RISK, CLOSING-SPEED RISK (one per episode, L-f), each with a radio line of at most 12 words | `simply_clipping/alerts.py`, `battles.py` |
| Live plug-in | `create(cfg, track)` → `update(view)` returns alerts for the pit wall | `simply_clipping/live.py` |
| Real race | Runs on the 2026 Japanese GP from OpenF1 | `simply_clipping/real_data.py` |
| Bench | Scored against the built-in radar on test seeds 6-10 | `python -m pitwall_sim.bench --sc-module simply_clipping` |

Test-set results: energy MAE 0.36-0.88 MJ against 0.84-1.28 MJ for the built-in;
CLIP precision 53-66 % against 4-6 %; calibration error (ECE) 4-10 % against 18-34 %.
Weak spots: ATTACK recall is 0 % (built-in 100 %), closing-incident pass is 0 %
(open item O-3), and it can't tell when a car's data has frozen (the real BEA case).

## 2. The biggest gap: judges don't see Simply Clipping

In the live app:
- The radar panel and the Reveal plot the simulator's built-in radar (`view.radar`). See `pitwall_sim/live/reveal.py` (`sample`, `on_call`) and the radar panel in `pitwall_sim/ui/pitwall_lite.py`.
- Alerts come from `alerts.provider: simply_clipping_lite`, also built in (`config/app.yaml`).
- Simply Clipping's live provider returns alerts only; it has no estimates to show.

So the on-screen numbers are the weaker estimator: radar MAE 1.13-1.26 MJ in the live runs, against 0.39 MJ for Simply Clipping on the bench.

| # | Change | Where | Why |
| --- | --- | --- | --- |
| 1 | Add `estimates()` to the live provider: latest energy, confidence and state per rival | `simply_clipping/live.py` (no `pitwall_sim` import, SC-R01) | Gives the pit wall its numbers |
| 2 | Accept an optional `estimates()` from the provider; the radar panel and Reveal use it when present and fall back to `view.radar` | `pitwall_sim/live/session.py`, `live/reveal.py`, radar panel in `ui/pitwall_lite.py` | Judges see the better estimator. Barrier holds: the plug-in reads public data only. |
| 3 | Add a setup switch "Radar: built-in / Simply Clipping" (default Simply Clipping for the demo) | `ui/setup_screen.py`, `LiveSetup` | One click; no YAML editing on stage |
| 4 | Reveal plots three lines: truth, built-in estimate (dashed grey), Simply Clipping (dashed amber), with each one's MAE in the header | `live/reveal.py`, `RevealTab` | Shows the bench result live: "our radar 0.4 MJ off, the simple one 1.2" |
| 5 | Show the live state chip (DEPLOY / CLIP / HARVEST) next to each rival from Simply Clipping | radar panel | Makes "clipping" visible as it happens |

## 3. Make the idea visible to non-F1 judges

| # | Change | Where | Why |
| --- | --- | --- | --- |
| 6 | Clip markers on the track map: a short flash and a tag ("BOR clipped, ~0.3 MJ") where a rival clips | `ui/track_map.py` (empty stub) or the map in `pitwall_lite.py`; data from item 1 | The core idea in one second, no explanation needed |
| 7 | First-run overlay: 4 callouts ("your car, exact", "rivals, estimated", "alerts", "talk to the driver"), dismissable | new `ui/onboarding.py`, shown from `PitWallWindow` | Judges unfamiliar with F1 get oriented in 10 s |
| 8 | Hover tooltips on jargon (Overtake mode, Straight Mode, harvest, MJ) using the PITCH glossary | `pitwall_lite.py` labels | Cuts verbal explanation during the demo |
| 9 | Battery bars that show uncertainty as a range (e.g. 1.6-2.4 MJ), not a number plus "conf 0.17" | radar panel | "Confidence 0.17" means nothing to a judge; a wide bar does |

## 4. Smoother demo flow

| # | Change | Where | Why |
| --- | --- | --- | --- |
| 10 | "Judge demo" preset button: seed 2, GAS, 15 laps, SC lap 7, Pause on alert, Simply Clipping radar | `ui/setup_screen.py`, `live/presets.py` | The setup screen has 12 fields; one click avoids mistakes on stage |
| 11 | Start the strategy workers while the setup screen is open | `live/strategy.py` `StrategyWorker.start` called from `main.py` | The first refresh takes ~30 s; the panel says "waiting" during the opening of the demo |
| 12 | Script to pre-fill `data/cost_cache/` for the demo calls | from `data/runs/_tools/rehearse_demo.py` | The Reveal costs show at once instead of ~2.7 s per call |
| 13 | Alert countdown bar and a sound on a new alert | `AlertCard` in `pitwall_lite.py` | The 8 s expiry is invisible today; in the owner's run all 7 alerts expired unanswered |
| 14 | Larger-text "projector mode" (font scale 1.3, thicker plot lines) | `pitwall_lite.py` `_label`, plot pens | Readable from the back of a room |

## 5. Existing features to improve

| # | Issue seen | Change | Where |
| --- | --- | --- | --- |
| 15 | The driver repeated "Battery's 0.0, I'll be slow down the straight." 13 times in the rehearsal, and the grammar is off | Rewrite as "Battery's low for the straight." Say it at most once per lap, and stay quiet while the engineer has already called HARVEST | `live/driver_radio.py` |
| 16 | 6 ATTACK alerts on HAD at T15 on consecutive laps, 4 with no pass (owner's run, built-in radar underestimating) | After 2 failed attacks on the same rival, suppress for 2 laps or show "last 2 attacks failed" on the card | alert provider / `AlertCard` |
| 17 | Strategy refresh takes ~25 s, about 3 laps stale at 16x; "4 forks x 6 laps" is the fallback size | Refresh only on a lap change or a big event; show the age ("from lap 5") in amber when stale | `live/strategy.py`, strategy panel |
| 18 | The undercut never pays in 15-lap races (tyre wear placeholders) | Add a "long race" demo variant (from the lap-30 real moment, where tyres matter), not hand-tuned wear (HR-09) | `DEMO_HACKATHON.md`, presets |
| 19 | The Reveal is a table plus 3 plots | Add a "your key moment" card: the costliest call, with the rival's true vs estimated battery at that instant, and the best option | `RevealTab` |
| 20 | Engineer score is shown but can't be shared | Add a "Copy result" or PNG export of the score card (seed, car, score, best and worst call) | `RevealTab` |
| 21 | Telemetry has no brake trace or rival comparison | Add brake and a selectable rival line from the public feed (T-075) | `ui/telemetry_plot.py` |
| 22 | The real race moment ends without comparing to reality | After the flag, show "Real result" next to the sim result, and what the real team did at lap 30 (light PF-18) | `replay/real_race.py`, Reveal |
| 23 | Real-race lap times ~111 s against ~95 s real | Calibration (T-02B, T-02C), not hand-tuning | calibration tasks |
| 24 | Every car carries ~85 kg of extra fuel in a 15-lap race | Set fuel from race length (T-02B, owner) | `LiveSetup.fuel_kg` |

## 6. Simply Clipping: next steps

| # | Change | Why |
| --- | --- | --- |
| 25 | Frozen-channel detector: if speed hasn't changed for N samples while the car moves on timing, mark "no data" and decay confidence | The missed real crash (BEA, lap 22) |
| 26 | ATTACK recall: also fire on a strong single-straight clip this lap (not only last lap), with lower confidence | Recall is 0 % against 100 % for the built-in |
| 27 | Owner decisions O-1 (0.5 MJ "right" tolerance) and O-3 (closing rule against target) | Unblocks the last two targets |
| 28 | Live estimates (item 1) plus a small "estimator health" line: anchors seen, time since last clip | Makes confidence understandable |
| 29 | More real races from OpenF1 (any 2026 session key) on the bench | "Works on every 2026 race so far" is a stronger claim than one race |

## 7. Bigger additions (after the hackathon)

- Challenge mode: fixed scenarios ("Suzuka lap 30, NOR, beat 80 points") with a local leaderboard.
- Two-player mode: two engineers on rival cars, each seeing only public data about the other.
- Gemma on-device radio (R3), so the AI radio works with no key and no internet.
- More tracks (track builder plus calibration).

## 8. PITCH.md: suggested edits (not applied)

Accuracy:
- It says Simply Clipping is "the radar" users see in the race. By default the live radar is the built-in one (section 2). Either build items 1-4 first, or say it plainly: "tested offline and on real data; drives the alerts when switched on".
- "Attack a car with less energy and you pass it" is too strong; use "usually".
- "Running in about 8 seconds" should say it is the headless 53-lap race.

Simplicity and tone:
- Drop the emoji legend; use plain "Works / Needs API key / Planned".
- Merge the five feature tables into one table with an "Area" column.
- Cut the bold in most sentences, plus the flourishes ("finally understand", "The big idea in one sentence").
- Explain "how far confidence is from the real hit rate" in one line; judges won't know ECE.
- Keep: the 30-second problem, the clipping idea, how a race goes, the results table, the glossary.

## 9. Suggested order with limited time

1. Items 1-4: Simply Clipping as the live radar, side by side in the Reveal. This is the biggest showcase gain.
2. Items 10-13: judge preset, worker pre-warm, cost cache, alert countdown.
3. Items 6 and 15: clip markers and the driver radio fix.
4. Section 8 pitch edits.
5. Then 19, 20 and 22 for the Reveal story.
