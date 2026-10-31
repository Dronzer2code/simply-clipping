# SIMPLY_CLIPPING_BRIDGE.md — Test bench for your Simply Clipping

You build Simply Clipping (your Rival Battery Radar) as your own package; the
simulator is the test bench. It never imports your package: it loads it by name.

## 0. QUICK START

1. Copy `docs/examples/hello_clipping.py` to `my_clipping/__init__.py` in the
   repository folder (or anywhere on your Python path) and run the bench on it:

   ```powershell
   python -m pitwall_sim.bench --sc-module my_clipping --scenario all --seeds 6-10
   ```

   For every scenario and seed it exports the race (or reuses the export in
   `data/exports/batch`), calls your `run(...)`, scores your files next to the
   baselines and writes `data/sc_out/my_clipping/BENCH_REPORT.md`. Re-running
   skips finished steps; `--rerun` runs your module again after you changed it.
   Seeds 1-5 are the tune set, 6-10 the test set: tune on 1-5, report 6-10.
2. Replace the two function bodies with Simply Clipping (section 2).
3. Live: put `provider: external:my_clipping` under `alerts:` in
   `config/app.yaml`; the pit wall (`python main.py`) then runs your alerts.

## 1. EXPORT (`python -m pitwall_sim.export`)

```powershell
python -m pitwall_sim.export --seed 42 --scenario normal --out data/exports/suzuka_normal_s42
python -m pitwall_sim.export --seed 42 --scenario all --out data/exports/s42
```

Options: `--track suzuka`, `--rules 2026_post_miami|2026_pre_miami`, `--laps N`
(default: the full race; short races distort pit strategy), `--fuel-kg 110`.
A full Suzuka race exports in a few minutes. All 22 cars are exported.

| Path | Content |
| --- | --- |
| `feed/car_data.parquet` | FastF1-like raw car stream: `Driver`, `SessionTime` (timedelta), `Speed` (km/h, σ 0.5 noise), `RPM` (not simulated: NaN), `nGear` (speed bands), `Throttle` (0-100, integer), `Brake` (bool). No DRS. |
| `feed/pos_data.parquet` | Raw position stream: `Driver`, `SessionTime`, `X`, `Y`, `Z` (decimetres, FastF1 units; σ 1 m noise), `Status`. |
| `feed/cars.parquet` | **Simply Clipping input.** Per car the two streams merged like FastF1 `merge_channels` (union of timestamps; speed, throttle, x, y linear; brake and gear held) and `add_distance`: `driver`, `time` (s), `distance` (m, integrated from speed since the car's first sample), `speed` (km/h), `throttle` (0-100), `brake` (bool), `gear`, `x`, `y` (m). |
| `feed/laps.parquet` | FastF1 columns: `Driver`, `DriverNumber`, `Team` (team_id), `LapNumber`, `LapTime`, `Sector1Time`-`Sector3Time`, `LapStartTime`, `Position`, `Compound`, `TyreLife`, `PitInTime`, `PitOutTime` (timedeltas). |
| `feed/gaps.parquet` | Per car per lap at the line: `Driver`, `LapNumber`, `Time`, `GapToLeader`, `IntervalToPositionAhead` (s). |
| `truth/ground_truth.parquet` | 10 Hz per running car: `driver`, `time_s`, `lap`, `distance_m`, `lap_distance_m`, `speed_kmh`, `throttle`, `brake`, `battery_mj`, `p_ice_kw`, `p_k_deploy_kw`, `p_harvest_kw`, `superclip`, `taper_active` (MGU-K limited by the speed taper), `zone_cap_kw`, `overtake_active`, `energy_mode`, `aero_mode`, `cda_true` (incl. slipstream), `mass_kg` (incl. fuel), `in_pit`, `state_true`. |
| `truth/events.parquet` | `type` (overtake, repass, clip, closing_speed), `t_start_s`, `t_end_s`, `lap`, `car_a`, `car_b`, `s_m`, `value` (overtake: p_pass; clip: battery at start; closing_speed: max Δv km/h; repass: earliest time RE-PASS RISK was possible), `blue_flag`, `superclip`, `scenario_target`. |
| `truth/car_params.json` | Per car: true CdA / ClA per aero mode, ICE power (with `pu_power_scale`, and fuel-flow limited), MGU-K max, efficiencies, usable battery, mass at start. |
| `baseline/builtin_alerts.parquet` | The sim's built-in alert provider (`simply_clipping_lite`), as the point-of-view car's pit wall saw them live (`alert_pov` in run.json). |
| `run.json` | Seed, Rule Set, track, scenario, laps, commit, grid order, scripted / held cars, target pair, trap cars, `targets` (did the race produce the scenario's target event?). |

`state_true` uses Simply Clipping's definitions on the TRUE power (electric =
MGU-K deploy − harvest): HARVEST braking; LIFT throttle < 20 %; DEPLOY throttle
≥ 95 % and > 150 kW; CLIP throttle ≥ 95 %, < 50 kW and speed flat or falling
(acceleration ≤ 0.3 m/s²); CRUISE otherwise.

Scenarios (`--scenario`): `normal`, `battles` (grid slowest first), `repass`
(NOR / HAM scripted for 4 laps: NOR spends its battery passing, HAM keeps
energy and re-passes), `closing_speed` (BEA in PUSH closes on COL, which
starts right ahead of it with an empty battery), `taper` (everyone pushes all race: long MGU-K-taper
stretches), `cda_trap` (every fourth car starts empty and never harvests on
purpose: straights start empty). `high_drag_full`, `partial_deploy`,
`pu_spread`: not built yet.

## 2. YOUR PACKAGE: TWO FUNCTIONS

Template (runs as is): `docs/examples/hello_clipping.py`.

### `run(feed_dir, out_dir, our, own_file, layout_file) -> None` (offline, the bench)

**Read** (and nothing else):

| Argument | What it is |
| --- | --- |
| `feed_dir` | The export's `feed/` folder: `cars.parquet` (your main input), `laps.parquet`, `gaps.parquet`, and the raw `car_data.parquet` / `pos_data.parquet` (section 1). Public data only, all 22 cars. |
| `our` | The driver code the alerts are for ("us"), or `None` (estimates only). |
| `own_file` | A `ground_truth.parquet`. You may read the rows of `our` ONLY: a team knows its own exact battery, throttle and position, never another car's. |
| `layout_file` | The track's public layout JSON: `track_id`, `length_m`, `centreline` (`s_m`, `x_m`, `y_m` every 2 m), `zones` (`zone_id`, `type`, `s_start_m`, `s_end_m`, `tags` such as `straight_mode_allowed`, `acceleration_zone`; `s_end_m < s_start_m` crosses the line), `corners` (`corner_id`, `s_m`). Written by `python -m pitwall_sim.export.layout`. |

Never read `truth/`, `baseline/` or `run.json`: that is the answer sheet.

**Write** into `out_dir`:

| File | Columns |
| --- | --- |
| `estimates.parquet` (required) | `driver`, `time_s`, `energy_mj`, `state` (DEPLOY, CLIP, HARVEST, LIFT, CRUISE), `confidence` (0-1; 0 = unknown, not scored); optional `since_anchor_s` (seconds since your last re-anchor, for the drift curve). Any rate; once a second per car is plenty. |
| `alerts.parquet` (when `our` is given) | `time_s`, `lap`, `type` (ATTACK, DEFEND, REPASS_RISK, CLOSING_SPEED_RISK), `car_a` (= `our`), `car_b` (the rival), `confidence`; optional `branch` (which of your rules fired). One row per alert, when it fires. |
| `cda_fit.json` (optional) | `{"VER": {"straight": 0.81, "corner": 1.02}, ...}` (m², per aero mode) |

### `create(cfg, track) -> provider` (live, the pit wall)

Called once when `alerts.provider: external:<your module>`. `provider.update(view)`
is then called a few times a second and returns the alerts active now. `view`
has `t_s`; `our_car` (exact: `driver_id`, `s_m`, `lap`, `battery_mj`, `v_ms`,
`throttle`, `brake`, `status`); `timing` (`order`, `interval_s`, `laps_down`,
`last_lap_s`); `rival_feed` ({driver: frames of the last 120 s}, each frame
`t_s`, `speed_kmh`, `throttle_pct`, `brake`, `gear`, `x_m`, `y_m`, `distance_m`
= lap distance); `radar` (the pit wall's own estimates: ignore them). `track`
has `official_length_m`, `zones`, `corners` (as in the layout file). Return
objects with the fields of `pitwall_sim.observe.alerts.Alert`: `alert_id`,
`type`, `rival`, `lap`, `corner_id`, `evidence` (`our_mj`, `rival_mj`, `dv_kmh`,
`gap_s`, `rival_state`, `last_clip_s_m`, `branch`, ...), `confidence`,
`created_t`, `expires_t`; the pit wall shows them, offers the call options and
lists them in the call summary.

## 3. SCORER (`python -m pitwall_sim.evaluate`)

```powershell
python -m pitwall_sim.evaluate --run data/exports/suzuka_normal_s42 --baseline
python -m pitwall_sim.evaluate --run data/exports/suzuka_normal_s42 --estimates <out>/estimates.parquet --alerts <out>/alerts.parquet --name "Simply Clipping" --baseline
```

Prints one column per estimator and writes `evaluate_report.json` into the run
folder. Baselines: **built-in** = the sim's Radar run on the exported
`cars.parquet` (lap distance from projecting x, y onto the centre line) plus the
recorded built-in alerts; **dumb rule** = "on a straight, the car ahead within
1 s is slower → ATTACK" for the same point-of-view car.

Metrics:

- energy: MAE, p90, bias vs `battery_mj`; by Energy Mode; confidence ≥ 0.5 vs
  < 0.5; by time since the last anchor.
- state: confusion matrix vs `state_true`; CLIP precision / recall; false CLIPs
  while `taper_active`.
- CdA: fitted vs `car_params.json` (% error); cda_trap cars apart.
- alerts per type: recall (an alert for the same pair within 2 laps before the
  event), lead time (median, share ≥ 5 s, share < 1 s), precision (a matching
  event within 2 laps after the alert), alerts per race (flag > 100), and for
  ATTACK / DEFEND "right per truth" (rival's true battery below / above ours),
  per branch.
- incidents (`repass`, `closing_speed`): an alert for the target pair fired
  before the event, and the lead time.

Events per alert type: ATTACK — car_a passes car_b; DEFEND — car_b passes
car_a; REPASS_RISK — car_a passed car_b and was re-passed (event = the re-pass);
CLOSING_SPEED_RISK — a closing-speed episode between the two.

## 4. BATCH AND BASELINE TABLE

```powershell
python -m pitwall_sim.export --batch 5 --scenario all --out data/exports/batch      # seeds 1-5
python -m pitwall_sim.export --seeds 6-10 --scenario all --out data/exports/batch  # seeds 6-10
python -m pitwall_sim.evaluate.batch --batch data/exports/batch --write docs/results/SC_RESULTS.md
```

Resumable (finished runs are skipped). `docs/results/SC_RESULTS.md` holds the baseline
table (built-in, dumb rule) from the overnight batch; any estimator folder in
`data/sc_out/<name>/` (the bench writes them) becomes another column. A batch
run takes about 1.5 minutes per race (export + scoring) on the 8 GB laptop.

