# DEMO_SC.md — 3-minute Simply Clipping demo (screen recording)

Rehearsed on 2026-10-30 with Simply Clipping v1 (`sc-v1` + the SC-6 radio line
and pit-lane fix), Suzuka, 2026 post-Miami rules, 16x. Race times are simulator
seconds. Answering an alert changes the race, so times after the first answer can
move by a few seconds; the first alerts of the setup are stable.

## Before recording (2 min, off camera)

1. In `config/app.yaml`, under `alerts:`, change `provider: simply_clipping_lite`
   to `provider: external:simply_clipping` (one line; change it back afterwards).
2. Start once so the kernels compile: `python main.py`, then close.
3. Open in an editor: `docs/results/SC_RESULTS.md` (or the README section
   "Simply Clipping") and a terminal in the repository folder.
4. Optional, if `data/sc_real/jpn2026_nor/` is not there yet: run step 6's command
   once (first time it downloads the race from OpenF1, ~5 min; afterwards ~1 min
   from the cache in `data/openf1_cache/`).

## 1. The problem (15 s)

> "In 2026 half the power is battery, and every rival's battery is hidden.
> Simply Clipping reads each rival's public telemetry, estimates its battery,
> and tells the pit wall when to attack or defend."

## 2. Live pit wall with Simply Clipping (40 s)

```powershell
python main.py
```

| Field | Value |
| --- | --- |
| Our team / Our driver | Alpine F1 Team / GAS - Pierre Gasly |
| Seed | **5** |
| Race laps | **3** |
| Scenario | Normal race |
| Pause on alert | on |
| Test mode | on (rivals' TRUE battery shown, red banner) |

Start, then **16x**. Say: "The alerts now come from Simply Clipping: each one has
a one-line radio call made only from its evidence."

| Race time | What happens | What to do |
| --- | --- | --- |
| 10-24 s, lap 0 | The start scramble: several RE-PASS RISK ("Only 0.0 MJ, long straight ahead. SAI can re-pass.") and a CLOSING-SPEED RISK on BOR | **Resume** each (about 5 presses, a second each) |

## 3. Answer an ATTACK and a DEFEND (50 s)

| Race time | What happens | What to do |
| --- | --- | --- |
| ~110 s, lap 0 | **ATTACK** on PER: "PER clipped here last lap. Attack into T16." Below it a **DEFEND** on BOT: "We have 0.6 MJ, straight needs 3.3. Defend T16." | Click the ATTACK card: why = observed clip, clip seen in 100 % of feed samples, **TRUE 0.68 MJ (test mode)**: PER really is low. Press **F1** (Attack now). Then **F1** on the DEFEND. |
| ~136 s, lap 1 | **DEFEND** on PER (energy + own battery): "PER behind has 3.3 MJ, we have 0.7. Defend T3." and a RE-PASS RISK | Show the TRUE battery, press **F1**; Resume the RE-PASS |
| ~142 s | DEFEND / RE-PASS on ALO | F1 or Resume |

Say: "The radar panel is the simulator's own Radar; Simply Clipping's numbers are
in the alert cards."

Fallback if no ATTACK by ~2 min: restart with seed 1 (ATTACK on BEA at ~14 s,
observed clip; DEFEND on OCO at ~126 s).

## 4. Call summary (20 s)

At ~348 s race time (3 laps) the **Call summary** opens by itself: every alert,
the call made (or ignored / expired), what happened in the next 2 laps, and in
Test mode whether each alert was right per Ground Truth (rehearsal: 12 alerts,
2 of the 4 judged right). Fallback: the **Call summary** button.

## 5. Results against the built-in (30 s)

Show `docs/results/SC_RESULTS.md` (test set, seeds 6-10, run once) or the README
table:

> "On 30 test races Simply Clipping's battery error is 0.36-0.88 MJ against
> 0.84-1.28 for the built-in Radar, its confidence is honest (0.8 means right
> about 80 % of the time), CLIP precision is 53-66 % against 4-6 %, and it caught
> the re-pass incident in 67 % of races against 33 %. Not beaten yet: ATTACK
> precision in a normal race, and the closing-speed incident."

## 6. Real-race check (25 s)

```powershell
python -m simply_clipping.real_data --session 11253 --our NOR --out data/sc_real/jpn2026_nor
python -c "import pandas as pd; a = pd.read_parquet('data/sc_real/jpn2026_nor/alerts.parquet'); print(a[(a.car_b == 'HAM') & (a.type == 'REPASS_RISK')][['time_s', 'lap', 'radio']].to_string())"
```

The table lists five RE-PASS RISK calls on HAM; the incident is the rows at
t 4732.5 s (lap 47) and 5015.0 s (lap 50).

> "The real 2026 Japanese Grand Prix from OpenF1. Norris passed Hamilton on laps
> 47 and 50 and clipped on the next straight; Simply Clipping called RE-PASS RISK
> at both passes, 15 and 20 seconds before Hamilton came back past. The lap-22
> Bearman-Colapinto crash it did not catch: Bearman's speed data is frozen before
> the impact."

Afterwards: set `provider: simply_clipping_lite` back in `config/app.yaml`.
