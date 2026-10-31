# DEMO.md — 3-minute demo script (screen recording)

Everything below was rehearsed on 2026-10-27 (Suzuka, 2026 post-Miami rules,
speed 16x; race times are simulator seconds, at 16x one race second is 1/16 s on
screen). Answering an alert changes the race, so later times can move by tens of
seconds; the first alerts of each setup are stable. Before recording: close
other heavy programs, start once so the simulation kernel is compiled
(`python main.py`, then close), and keep this file open on a second screen.

The call summary comes at the flag of the first race, so it follows step 3
directly (steps 5 before 4 below); everything else is in the planned order.

## 1. One line (5 s)

> "In 2026, half the power is battery, and rivals' batteries are hidden. This sim
> puts you on the pit wall."

## 2. Race setup (15 s)

```powershell
python main.py
```

Choose, top to bottom:

| Field | Value |
| --- | --- |
| Track / Rule Set | Suzuka / 2026_post_miami (defaults) |
| Our team / Our driver | Alpine F1 Team / GAS - Pierre Gasly |
| Seed | 42 (default) |
| Race laps | **3** (so the flag, and the call summary, come quickly) |
| Scenario | Normal race |
| Pause on alert | **on** |
| Test mode | **on** (the red "TEST MODE" banner: rivals' true battery shown) |

Click **Start race**, then **16x**. Say: "Our battery is exact; rivals are only
a Radar Estimate from their public telemetry."

## 3. Answer a DEFEND and an ATTACK with F1 (60 s)

| Race time | What happens | What to do |
| --- | --- | --- |
| ~9 s, lap 1 | **DEFEND** on COL ("COL has the battery - defend into T1"), the race pauses | Click the card: the evidence shows our battery, COL's estimate ("assumed full at start"), and in Test mode COL's TRUE battery. Press **F1** (Defend into T1): the radio shows the call and "Copy, defending T1." |
| ~60-100 s, lap 1 | **ATTACK** on BOR ("... attack into T15"), paused | Click the card: "why: energy" or "why: observed clip", estimate vs TRUE battery. Press **F1** (Attack now). |
| ~90 s | Several **CLOSING-SPEED RISK** alerts at once (a car running empty on a straight while others close fast) | Press **F1** (Warn driver) or **Resume** for each; they are quick. |
| ~120-240 s | More DEFEND alerts ("We're short for the straight" = own-battery rule) | F1 or Resume. |

Fallback if no ATTACK by ~2 minutes of race time: restart with **seed 9** (ATTACK
on HUL at ~84 s, energy rule) or use the Closing-speed scenario in step 4 (ATTACK
on COL at ~44 s).

## 5. Call summary at the flag (20 s)

At ~350 s race time (3 laps; about 25 s on screen plus the pauses) the
**Call summary** opens by itself: every alert, the call (or ignored / expired),
what happened in the next 2 laps (pass made / position kept / lost / re-passed),
the totals and, in Test mode, "alert right? (test)" per Ground Truth. Fallback:
press the **Call summary** button at any time.

Close the window.

## 4. The two scenario presets (40 s)

Both run the **full race distance** (Race laps 53): in a 3-lap race every rival
pushes from the start and the situations do not form.

**Re-pass scenario** — `python main.py`: GAS, seed 42, Race laps 53, Scenario
**Re-pass scenario**, Pause on alert on, Test mode on, Start, 16x.

| Race time | What happens | What to do |
| --- | --- | --- |
| ~39 s and ~53 s | DEFEND alerts | **Resume** (not F1: answering changes the race and can stop the re-pass) |
| ~60 s, lap 1 | **RE-PASS RISK** on LIN: "Don't pass yet - you'll be empty on the straight" | Show it, press F1 (Hold behind, harvest) |

Fallback: seed 9 (RE-PASS RISK on LAW at ~203 s, lap 2).

**Closing-speed scenario** — close, `python main.py` again: GAS, seed 42, Race
laps 53, Scenario **Closing-speed scenario**, Pause on alert on, Test mode on.

| Race time | What happens |
| --- | --- |
| ~44 s | ATTACK on COL (Resume or F1) |
| ~91 s, lap 1 | **CLOSING-SPEED RISK** on ALO ("Big closing speed on ALO - careful into ..."), with the cars ahead clipping on the straight while we deploy |

## 6. The test bench (30 s)

```powershell
python -m pitwall_sim.bench --sc-module docs.examples.hello_clipping --scenario normal --seeds 6
```

About 5 s when the race export exists (the overnight batch made it); on a fresh
machine it first exports the race (about 1-2 minutes). Open
`data/sc_out/hello_clipping/BENCH_REPORT.md` (hello_clipping next to the
built-in Radar and the dumb rule on the same race) and `docs/results/SC_RESULTS.md` (the
built-in baseline over 10 seeds x 6 scenarios).

> "This is where my Simply Clipping plugs in: two functions, `run` for the bench
> and `create` for the pit wall. The table shows what it has to beat."

(`docs/spec/SIMPLY_CLIPPING_BRIDGE.md` has the contract.)
