"""Race export for testing Simply Clipping (sprint S-1, docs/planning/SPRINT.md Parts 1 and 5).

    python -m pitwall_sim.export --seed 42 --scenario normal --out data/exports/<run_id>

Writes ``<out>/feed/`` (what a real team sees, FastF1-like: car_data, pos_data,
cars, laps, gaps), ``<out>/truth/`` (ground_truth at 10 Hz, events, car_params)
and ``<out>/run.json``. All 22 cars are exported (a test dataset).
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, load_grid
from pitwall_sim.export import feed, scenarios, tables, truth
from pitwall_sim.export.scenarios import Scenario, ScenarioSetup
from pitwall_sim.race.engine import RaceEngine, RaceSetup

logger = logging.getLogger(__name__)

EXPORT_SALT = 0x5C1
"""The feed sampling RNG is ``default_rng([seed, EXPORT_SALT])`` (export only, not the race)."""
BATTLE_GAP_S = 1.0
TRAP_EMPTY_MJ = 0.3
FEED_FILES = ("cars", "laps", "gaps", "car_data", "pos_data")
DEFAULT_POV = "GAS"
"""A midfield car (alerts need fights) when the scenario scripts none."""
ALERT_COLUMNS = ("time_s", "lap", "type", "car_a", "car_b", "confidence", "branch")


def alerts_frame(alerts: list[Any], pov: str | None) -> pd.DataFrame:
    """Alerts in the scorer contract (car_a: the car they are for, car_b: the rival)."""
    rows = [{"time_s": a.created_t, "lap": a.lap, "type": a.type,
             "car_a": pov, "car_b": a.rival, "confidence": a.confidence,
             "branch": a.evidence.branch or ""} for a in alerts]  # fmt: skip
    return pd.DataFrame(rows, columns=list(ALERT_COLUMNS))


def default_order(grid_id: str, config_dir: Path) -> tuple[str, ...]:
    """Return the grid file's driver order (the race's default starting order)."""
    grid = load_grid(grid_id, config_dir)
    return tuple(d.driver_id for t in grid.teams for d in t.drivers)


def _pace(setup: RaceSetup, config_dir: Path) -> dict[str, float]:
    """Each car's reference lap time (energy-unlimited) at the start."""
    probe = RaceEngine(setup, config_dir)
    return {d: probe.car_plans[i].lap_time_s for i, d in enumerate(probe.driver_ids)}


def _commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=True, cwd=Path(__file__).parent).stdout.strip()  # fmt: skip
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                               check=True, cwd=Path(__file__).parent).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


def targets(
    setup: ScenarioSetup, run: truth.TruthRun, events: pd.DataFrame, gt: pd.DataFrame
) -> dict[str, Any]:
    """Did the race produce the scenario's target? (``produced`` and the numbers)."""
    out: dict[str, Any] = {"target": setup.target, "produced": True}
    if setup.scenario == "battles":
        d = run.data
        close = d["running"] & (d["gap_ahead_m"] / np.maximum(d["v_ms"], 1.0) <= BATTLE_GAP_S)
        out["battle_share"] = float(close.sum() / max(d["running"].sum(), 1))
        out["produced"] = out["battle_share"] > 0.0
    elif setup.scenario in ("repass", "closing_speed"):
        kind = "repass" if setup.scenario == "repass" else "closing_speed"
        hits = events[(events["type"] == kind) & events["scenario_target"]]
        if kind == "repass":  # the passer re-passed after RE-PASS RISK was possible
            assert setup.pair is not None
            hits = hits[(hits["car_a"] == setup.pair[0]) & hits["value"].notna()]
        out["produced"] = bool(len(hits))
        out["events"] = hits[["t_start_s", "t_end_s", "car_a", "car_b", "value"]].to_dict("records")
    elif setup.scenario == "taper":
        deploying = gt["p_k_deploy_kw"] > 0.0
        out["taper_share_of_deploy"] = float(gt.loc[deploying, "taper_active"].mean())
        out["produced"] = out["taper_share_of_deploy"] > 0.0
    elif setup.scenario == "cda_trap":
        starts = _straight_starts(run, setup.trap_cars)
        out["trap_straight_starts"] = len(starts)
        out["empty_share"] = float(np.mean([b < TRAP_EMPTY_MJ for b in starts])) if starts else 0.0
        out["produced"] = out["empty_share"] > 0.0
    return out


def _straight_starts(run: truth.TruthRun, cars: tuple[str, ...]) -> list[float]:
    """Battery (MJ) of ``cars`` at each straight-zone entry."""
    e, d = run.engine, run.data
    starts = [z.s_start_m for z in e.track.zones if z.type == "straight"]
    out = []
    for driver in cars:
        i = e.driver_ids.index(driver)
        s = d["s_m"][:, i]
        for s0 in starts:
            crossed = (s[:-1] < s0) & (s[1:] >= s0) & d["running"][1:, i]
            out += (d["battery_j"][1:, i][crossed] / 1e6).tolist()
    return out


def export_race(
    out: Path, seed: int = 42, scenario: Scenario = "normal", track: str = "suzuka",
    rules: str = "2026_post_miami", laps: int | None = None, fuel_kg: float = 110.0,
    config_dir: Path = DEFAULT_CONFIG_DIR, alert_pov: str | None = "",
) -> dict[str, Any]:  # fmt: skip
    """Race one scenario and write the export to ``out``; return run.json's content.

    ``alert_pov``: the car whose built-in alerts are kept as the baseline
    (``""``: the scenario's point-of-view car, else ``DEFAULT_POV``; ``None``: none).
    """
    started = time.perf_counter()
    base = RaceSetup(track_id=track, rule_set_id=rules, seed=seed, laps=laps, fuel_kg=fuel_kg)
    order = default_order(base.grid_id, config_dir)
    pace = _pace(base, config_dir) if scenario == "battles" else {}
    probe_laps = laps if laps is not None else 0
    setup = scenarios.plan(scenario, order, pace, probe_laps)
    engine = RaceEngine(
        RaceSetup(track_id=track, rule_set_id=rules, seed=seed, laps=laps, fuel_kg=fuel_kg,
                  grid_order=setup.grid_order, our_driver_id=setup.scripted),
        config_dir,
    )  # fmt: skip
    if scenario == "taper":  # push the whole race, whatever its length
        setup = scenarios.plan(scenario, order, pace, engine.laps)
    scenarios.apply(setup, engine)
    pov = (setup.pov or DEFAULT_POV) if alert_pov == "" else alert_pov
    run = truth.record(engine, engine.app.export.truth_hz, pov,
                       lambda e: scenarios.on_tick(setup, e))  # fmt: skip
    states = tables.true_states(run)
    gt = tables.ground_truth(run, states)
    alerts = engine.app.alerts
    ev = tables.events(run, states, alerts.closing_dv_kmh, alerts.closing_range_m, setup.pair,
                       setup.trap_cars)  # fmt: skip
    laps_df, gaps_df = tables.laps_and_gaps(run)
    rng = np.random.default_rng([seed, EXPORT_SALT])
    car_data, pos_data = feed.streams(run, engine.app.export, rng, engine.app.feed.gear_upshift_kmh)
    files = {
        "feed/car_data.parquet": car_data, "feed/pos_data.parquet": pos_data,
        "feed/cars.parquet": feed.merge(car_data, pos_data), "feed/laps.parquet": laps_df,
        "feed/gaps.parquet": gaps_df, "truth/ground_truth.parquet": gt,
        "truth/events.parquet": ev,
        "baseline/builtin_alerts.parquet": alerts_frame(run.alerts, pov),
    }  # fmt: skip
    for name, frame in files.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out / name, index=False)
    (out / "truth" / "car_params.json").write_text(
        json.dumps(tables.car_params(run, fuel_kg), indent=2), encoding="utf-8"
    )
    info = {
        "seed": seed, "rule_set": rules, "track": track, "scenario": scenario,
        "laps": engine.laps, "fuel_kg": fuel_kg, "commit": _commit(),
        "scripted_car": setup.scripted, "held_cars": list(setup.held), "alert_pov": pov,
        "pair": setup.pair,
        "trap_cars": list(setup.trap_cars), "grid_order": list(setup.grid_order or order),
        "truth_hz": engine.app.export.truth_hz, "export": engine.app.export.model_dump(),
        "lap_length_m": engine.trk.length_m, "finished": engine.finished,
        "race_time_s": engine.t, "targets": targets(setup, run, ev, gt),
        "wall_s": round(time.perf_counter() - started, 1),
    }  # fmt: skip
    (out / "run.json").write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
    logger.info("export %s seed %d -> %s (%.0f s)", scenario, seed, out, info["wall_s"])
    return info
