"""Ground Truth tables of a recorded race (sprint S-1): truth, events, laps, gaps, car params.

``state_true`` applies Simply Clipping's state definitions (docs/planning/SPRINT.md Part
5) to the TRUE power: HARVEST braking; LIFT throttle < 20 %; DEPLOY throttle
>= 95 % with electric power > 150 kW; CLIP throttle >= 95 %, electric power <
50 kW and speed flat or falling; CRUISE otherwise. Electric power is MGU-K
deploy minus harvest (a super-clip is negative).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from pitwall_sim.driver.ai_driver import MODE_CODES
from pitwall_sim.export.truth import TruthRun
from pitwall_sim.race import step_kernel as K
from pitwall_sim.track.zones import zone_mask

MJ, KW, KMH = 1e6, 1e3, 3.6
FULL_THROTTLE, LIFT_THROTTLE = 0.95, 0.20
DEPLOY_W, CLIP_W = 150e3, 50e3
FLAT_ACCEL_MS2 = 0.3
"""\"Speed flat or falling\": below this acceleration (STRUCTURAL)."""
MIN_CLIP_S = 0.3
"""A clip event lasts at least this long (single samples are not events)."""
STATES = ("DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE")
MODE_NAMES = {code: mode.value for mode, code in MODE_CODES.items()}
REPASS_BATTERY_MJ, REPASS_STRAIGHT_M = 1.0, 600.0


def true_states(run: TruthRun) -> npt.NDArray[np.int8]:
    """``state_true`` index into :data:`STATES` per sample and car."""
    d = run.data
    p_elec = d["p_k_w"].astype(np.float64) - d["p_harvest_w"]
    accel = np.gradient(d["v_ms"].astype(np.float64), run.t_s, axis=0)
    full = d["throttle"] >= FULL_THROTTLE
    state = np.full(p_elec.shape, STATES.index("CRUISE"), dtype=np.int8)
    state[full & (p_elec > DEPLOY_W)] = STATES.index("DEPLOY")
    state[full & (p_elec < CLIP_W) & (accel <= FLAT_ACCEL_MS2)] = STATES.index("CLIP")
    state[d["throttle"] < LIFT_THROTTLE] = STATES.index("LIFT")
    state[d["brake"] > 0.0] = STATES.index("HARVEST")
    return state


def ground_truth(run: TruthRun, states: npt.NDArray[np.int8]) -> pd.DataFrame:
    """Return the ``truth/ground_truth.parquet`` table (one row per sample and running car)."""
    e, d = run.engine, run.data
    length = e.trk.length_m
    accel = zone_mask(e.track, e.model.s_m, tag="acceleration_zone")
    k = (d["s_m"] / e.trk.ds_m).astype(np.int64) % accel.size
    cap_kw = np.where(accel[k], e.glb.zone_cap_acceleration_w, e.glb.zone_cap_other_w) / KW
    gap = np.where(np.isfinite(d["gap_ahead_m"]), d["gap_ahead_m"], 1e9).astype(np.float64)
    wake = np.clip(1.0 - gap / e.glb.wake_range_m, 0.0, 1.0)
    straight = d["aero_mode"] == K.STRAIGHT_MODE
    cda = np.where(straight, e.cars.cda_straight, e.cars.cda_corner)
    cda_true = cda * (1.0 - e.glb.drag_reduction_max * wake)
    n_samples, n = d["s_m"].shape
    car = np.broadcast_to(np.arange(n), (n_samples, n))
    keep = d["running"].ravel()
    cols: dict[str, Any] = {
        "driver": np.asarray(e.driver_ids)[car.ravel()],
        "time_s": np.repeat(run.t_s, n),
        "lap": d["lap"].ravel() + 1,
        "distance_m": (d["lap"].astype(np.float64) * length + d["s_m"]).ravel(),
        "lap_distance_m": d["s_m"].ravel(),
        "speed_kmh": d["v_ms"].ravel() * KMH,
        "throttle": d["throttle"].ravel(),
        "brake": (d["brake"] > 0.0).ravel(),
        "battery_mj": d["battery_j"].ravel() / MJ,
        "p_ice_kw": (d["power_w"] - d["p_k_w"]).ravel() / KW,
        "p_k_deploy_kw": d["p_k_w"].ravel() / KW,
        "p_harvest_kw": d["p_harvest_w"].ravel() / KW,
        "superclip": d["superclip"].ravel(),
        "taper_active": d["taper_limited"].ravel(),
        "zone_cap_kw": cap_kw.ravel(),
        "overtake_active": d["overtake_active"].ravel(),
        "energy_mode": np.asarray([MODE_NAMES[c] for c in range(3)])[d["mode"].ravel()],
        "aero_mode": np.where(straight, "STRAIGHT", "CORNER").ravel(),
        "cda_true": cda_true.ravel(),
        "mass_kg": (e.cars.mass_min_kg + d["fuel_kg"]).ravel(),
        "in_pit": d["in_pit"].ravel(),
        "state_true": np.asarray(STATES)[states.ravel()],
    }
    frame = pd.DataFrame({name: np.asarray(v)[keep] for name, v in cols.items()})
    for name in ("speed_kmh", "throttle", "battery_mj", "p_ice_kw", "p_k_deploy_kw",
                 "p_harvest_kw", "zone_cap_kw", "cda_true", "mass_kg"):  # fmt: skip
        frame[name] = frame[name].astype(np.float32)
    return frame


def _runs(mask: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    """(first, last) sample of each run of True."""
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1, strict=True))


def events(run: TruthRun, states: npt.NDArray[np.int8], dv_kmh: float, range_m: float,
           pair: tuple[str, str] | None, trap: tuple[str, ...]) -> pd.DataFrame:  # fmt: skip
    """Return ``truth/events.parquet``: overtakes, re-passes, clips, closing-speed episodes.

    ``scenario_target`` marks events of the scenario's target pair (or trap cars).
    """
    e, d, t = run.engine, run.data, run.t_s
    ids = e.driver_ids
    rows: list[dict[str, Any]] = []
    passes = [ev for ev in e.overtake.events if ev.success]
    for ev in passes:
        rows.append({"type": "overtake", "t_start_s": ev.t_s, "t_end_s": ev.t_s,
                     "car_a": ids[ev.attacker], "car_b": ids[ev.defender], "s_m": ev.s_m,
                     "value": ev.p_pass, "blue_flag": ev.blue_flag})  # fmt: skip
    rows += _repasses(run, passes)
    clip = states == STATES.index("CLIP")
    hz = 1.0 / float(np.median(np.diff(t))) if t.size > 1 else 10.0
    for i, driver in enumerate(ids):
        for a, b in _runs(clip[:, i] & d["running"][:, i]):
            if (b - a + 1) / hz < MIN_CLIP_S:
                continue
            rows.append({"type": "clip", "t_start_s": t[a], "t_end_s": t[b], "car_a": driver,
                         "car_b": None, "s_m": float(d["s_m"][a, i]),
                         "value": float(d["battery_j"][a, i]) / MJ,
                         "superclip": bool(d["superclip"][a : b + 1, i].mean() > 0.5)})  # fmt: skip
    rows += _closing(run, states, dv_kmh, range_m)
    frame = pd.DataFrame(rows)
    for col in ("blue_flag", "superclip"):
        if col not in frame:
            frame[col] = False
        frame[col] = frame[col].eq(True)  # missing (other event types): False
    frame["lap"] = [_lap_at(run, str(r.car_a), float(r.t_start_s)) for r in frame.itertuples()]
    target = np.zeros(len(frame), dtype=bool)
    if pair is not None:
        car_a, car_b = pair
        target |= (frame["car_a"] == car_a) & (frame["car_b"] == car_b)
        target |= (
            (frame["type"].isin(["overtake", "repass"]))
            & (frame["car_a"] == car_b)
            & (frame["car_b"] == car_a)
        )
    if trap:
        target |= (frame["type"] == "clip") & frame["car_a"].isin(trap)
    frame["scenario_target"] = target
    return frame.sort_values("t_start_s", ignore_index=True)


def _lap_at(run: TruthRun, driver: str, t_s: float) -> int:
    i = run.engine.driver_ids.index(driver)
    k = min(int(np.searchsorted(run.t_s, t_s)), run.t_s.size - 1)
    return int(run.data["lap"][k, i]) + 1


def _repasses(run: TruthRun, passes: list[Any]) -> list[dict[str, Any]]:
    """Return each pass undone by the same car within one lap.

    ``value`` = the earliest time after the first pass when RE-PASS RISK was
    possible (passer < 1.0 MJ before a > 600 m straight), NaN if never.
    """
    e, d, t = run.engine, run.data, run.t_s
    length = e.trk.length_m
    straights = [(z.s_start_m, (z.s_end_m - z.s_start_m) % length)
                 for z in e.track.zones if z.type == "straight"]  # fmt: skip
    times = [r["lap_time_s"] for r in run.laps]
    lap_s = float(np.median(times)) if times else 120.0

    def coming_is_long(s: float) -> bool:  # the straight we are on, else the next one
        on = next((n for s0, n in straights if (s - s0) % length <= n), None)
        if on is None:
            on = min(straights, key=lambda z: (z[0] - s) % length)[1]
        return on > REPASS_STRAIGHT_M

    out = []
    for k, first in enumerate(passes):
        if first.blue_flag:
            continue
        back = next((p for p in passes[k + 1 :]
                     if not p.blue_flag and p.attacker == first.defender
                     and p.defender == first.attacker and p.t_s - first.t_s <= lap_s),
                    None)  # fmt: skip
        if back is None:
            continue
        a = first.attacker
        lo, hi = np.searchsorted(t, first.t_s), np.searchsorted(t, back.t_s)
        possible = float("nan")
        for j in range(lo, hi):
            if d["battery_j"][j, a] < REPASS_BATTERY_MJ * MJ and coming_is_long(d["s_m"][j, a]):
                possible = float(t[j])
                break
        out.append({"type": "repass", "t_start_s": first.t_s, "t_end_s": back.t_s,
                    "car_a": e.driver_ids[a], "car_b": e.driver_ids[first.defender],
                    "s_m": back.s_m, "value": possible})  # fmt: skip
    return out


def _closing(run: TruthRun, states: npt.NDArray[np.int8], dv_kmh: float,
             range_m: float) -> list[dict[str, Any]]:  # fmt: skip
    """Return closing-speed episodes: > ``dv_kmh`` on the car ahead within ``range_m``.

    Either car CLIP or LIFT; car_a is the faster car behind, car_b the car ahead.
    """
    e, d, t = run.engine, run.data, run.t_s
    slow = np.isin(states, [STATES.index("CLIP"), STATES.index("LIFT")])
    out = []
    open_: dict[tuple[int, int], list[Any]] = {}
    for j in range(t.size):
        ahead = d["ahead_idx"][j].astype(np.int64)
        valid = (ahead >= 0) & d["running"][j] & ~d["in_pit"][j]
        cars = np.flatnonzero(valid)
        b = ahead[cars]
        dv = (d["v_ms"][j, cars] - d["v_ms"][j, b]) * KMH
        close = (d["gap_ahead_m"][j, cars] <= range_m) & (dv > dv_kmh)
        hit = close & (slow[j, cars] | slow[j, b]) & ~d["in_pit"][j, b]  # not pitting ahead
        now = set()
        for a_, b_, dv_ in zip(cars[hit].tolist(), b[hit].tolist(), dv[hit].tolist(), strict=True):
            key = (a_, b_)
            now.add(key)
            if key in open_:
                open_[key][1] = t[j]
                open_[key][2] = max(open_[key][2], dv_)
            else:
                open_[key] = [t[j], t[j], dv_, float(d["s_m"][j, a_])]
        for key in [k for k in open_ if k not in now and t[j] - open_[k][1] > 1.0]:
            t0, t1, dv_max, s = open_.pop(key)
            out.append({"type": "closing_speed", "t_start_s": t0, "t_end_s": t1,
                        "car_a": e.driver_ids[key[0]], "car_b": e.driver_ids[key[1]],
                        "s_m": s, "value": dv_max})  # fmt: skip
    for key, (t0, t1, dv_max, s) in open_.items():
        out.append({"type": "closing_speed", "t_start_s": t0, "t_end_s": t1,
                    "car_a": e.driver_ids[key[0]], "car_b": e.driver_ids[key[1]],
                    "s_m": s, "value": dv_max})  # fmt: skip
    return out


def laps_and_gaps(run: TruthRun) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return FastF1-style ``laps.parquet`` and ``gaps.parquet`` (lap rows at the line)."""
    e = run.engine
    numbers = {d.driver_id: d.number for t in e.grid.teams for d in t.drivers}
    td = pd.to_timedelta
    laps, gaps = [], []
    for r in run.laps:
        driver = e.driver_ids[r["car"]]
        s1, s2, s3 = r["sectors_s"]
        laps.append({
            "Driver": driver, "DriverNumber": str(numbers[driver]), "Team": e.team_ids[r["car"]],
            "LapNumber": float(r["lap"]), "LapTime": td(r["lap_time_s"], unit="s"),
            "Sector1Time": td(s1, unit="s"), "Sector2Time": td(s2, unit="s"),
            "Sector3Time": td(s3, unit="s"), "LapStartTime": td(r["start_s"], unit="s"),
            "Position": float(r["position"]), "Compound": r["compound"],
            "TyreLife": float(r["tyre_life"]),
            "PitInTime": td(r["pit_in_s"], unit="s") if r["pit_in_s"] is not None else pd.NaT,
            "PitOutTime": td(r["pit_out_s"], unit="s") if r["pit_out_s"] is not None else pd.NaT,
        })  # fmt: skip
        gaps.append({
            "Driver": driver, "LapNumber": float(r["lap"]),
            "Time": td(r["start_s"] + r["lap_time_s"], unit="s"),
            "GapToLeader": r["gap_to_leader_s"], "IntervalToPositionAhead": r["interval_s"],
        })  # fmt: skip
    lap_cols = ["Driver", "DriverNumber", "Team", "LapNumber", "LapTime", "Sector1Time",
                "Sector2Time", "Sector3Time", "LapStartTime", "Position", "Compound",
                "TyreLife", "PitInTime", "PitOutTime"]  # fmt: skip
    gap_cols = ["Driver", "LapNumber", "Time", "GapToLeader", "IntervalToPositionAhead"]
    return pd.DataFrame(laps, columns=lap_cols), pd.DataFrame(gaps, columns=gap_cols)


def car_params(run: TruthRun, fuel_kg: float) -> dict[str, Any]:
    """Return ``truth/car_params.json``: each car's true constants."""
    e, c = run.engine, run.engine.cars
    out = {}
    for i, driver in enumerate(e.driver_ids):
        team = e.perf.teams[e.team_ids[i]]
        scale = team.pu_power_scale
        out[driver] = {
            "team": e.team_ids[i],
            "cda_straight_m2": float(c.cda_straight[i]),
            "cda_corner_m2": float(c.cda_corner[i]),
            "cla_straight_m2": float(c.cla_straight[i]),
            "cla_corner_m2": float(c.cla_corner[i]),
            "p_ice_max_kw": float(c.p_ice_max_w[i]) / KW,
            "p_ice_fuel_flow_limited_kw": float(
                min(c.p_ice_max_w[i], c.ice_efficiency[i] * c.max_fuel_flow_w[i])
            )
            / KW,
            "pu_power_scale": None if isinstance(scale, str) else float(scale),
            "p_k_max_kw": float(c.p_k_max_w[i]) / KW,
            "driveline_efficiency": float(c.driveline_efficiency[i]),
            "discharge_efficiency": float(c.discharge_efficiency[i]),
            "e_usable_max_mj": float(c.e_usable_max_j[i]) / MJ,
            "mass_min_kg": float(c.mass_min_kg[i]),
            "mass_start_kg": float(c.mass_min_kg[i]) + fuel_kg,
            "c_rr": float(c.c_rr[i]),
        }
    return out
