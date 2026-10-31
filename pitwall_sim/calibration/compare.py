"""F20 calibration compare CLI: simulated laps vs the real reference laps (T-025/T-026, PF-02).

Reference (owner OK before T-025; FastF1 has no data without an F1TV login):
2026 qualifying laps from OpenF1: lap times from ``/laps``, speed traces from
``/car_data`` mapped onto the centre line through ``/location``. Responses are
cached in ``paths.openf1_cache``, so a rerun is offline.

Targets (owner round 10): each team's fastest lap of the session (the better
of its two drivers; drivers are matched to teams by car number on the grid).
MVP-02 additionally needs the pole team within 2% of the pole lap.

Each team's car is simulated over one flying lap under qualifying conditions:
the Rule Set in force on the reference date (``--rules`` overrides), SOFT tyres,
a full battery, the Rule Set qualifying harvest limit, the track's
``quali_fuel_kg``, and the calibration deploy policy: ``policy`` (T-028, default:
deploy anywhere at full throttle within the Rule Set caps, super-clip the energy
shortfall at the ends of the acceleration zones), ``zones`` (T-026: deploy only
in acceleration zones) or ``greedy`` (no plan). Lap-time delta, speed RMSE and the team order are
printed and written to ``data/calibration/<track_id>.parquet``.

Usage::

    python -m pitwall_sim.calibration.compare --track suzuka
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, get_args

import numpy as np
import numpy.typing as npt
import polars as pl
import pyarrow.parquet as pq

from pitwall_sim.calibration.deploy_policy import (
    DeployPlan,
    PolicyResult,
    settle_deploy_anywhere,
    settle_plan,
    settle_spread,
)
from pitwall_sim.car.battery import battery_params, superclip_harvest_w
from pitwall_sim.car.deploy_allocation import allocate, profile_full_throttle
from pitwall_sim.car.fuel import fuel_params
from pitwall_sim.car.lap_sim import LapResult, simulate_lap
from pitwall_sim.car.speed_profile import reference_params, speed_profile
from pitwall_sim.config.loader import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    load_app,
    load_grid,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import (
    AppConfig,
    Compound,
    GridConfig,
    RuleSet,
    TeamPerformance,
    TrackConfig,
    TyreConfig,
)
from pitwall_sim.track.builder import TrackModel, project_path_to_s, read_track_model
from pitwall_sim.track.openf1 import (
    OPENF1_POS_UNIT_M,
    OpenF1Client,
    OpenF1Error,
    fastest_lap,
    find_session,
    lap_samples,
)
from pitwall_sim.track.zones import zone_mask

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
type DeployMode = Literal["policy", "anywhere", "zones", "greedy"]
DEPLOY_MODES: tuple[str, ...] = ("policy", "anywhere", "zones", "greedy")

MS_TO_KMH = 3.6
RULE_SET_IDS: tuple[str, ...] = get_args(RuleSet.model_fields["rule_set_id"].annotation)

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNAVAILABLE = 2


@dataclass(frozen=True)
class ReferenceLap:
    """A real lap the simulation is compared with."""

    lap_time_s: float
    s_m: FloatArray
    """Centre-line distance of each speed sample."""
    speed_kmh: FloatArray
    session_date: date
    source: dict[str, str]


@dataclass(frozen=True)
class TrackArrays:
    """The track grid and zone masks a lap simulation needs (computed once)."""

    s_m: FloatArray
    kappa: FloatArray
    straight_mode: BoolArray
    accel_zone: BoolArray
    length_m: float


@dataclass(frozen=True)
class TeamResult:
    """One team's simulated lap against its target."""

    team_id: str
    target_s: float
    lap_time_s: float
    delta_pct: float
    speed_rmse_kmh: float
    lap_time_ok: bool
    speed_ok: bool
    real_position: int
    sim_position: int
    harvested_mj: float
    drawn_mj: float


# --------------------------------------------------------------------------- #
# Reference laps
# --------------------------------------------------------------------------- #


def _timestamp(row: dict[str, Any]) -> float:
    return datetime.fromisoformat(str(row["date"])).timestamp()


#: Channels compared to detect frozen car_data (a dropout repeating the last value).
_FROZEN_KEYS = ("speed", "rpm", "n_gear", "throttle", "brake")
#: This many identical consecutive samples count as a frozen stretch.
FROZEN_RUN = 3


def valid_car_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop OpenF1 car_data samples that are not real measurements.

    - throttle or brake above 100 (OpenF1's out-of-range marker, e.g. 104);
    - frozen stretches: :data:`FROZEN_RUN` or more consecutive samples with all
      of speed, rpm, gear, throttle and brake identical (a telemetry dropout
      filled with the last value). The first sample of such a run is kept.
    """

    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row.get(k) for k in _FROZEN_KEYS)

    keep = [
        float(r.get("throttle") or 0) <= 100.0 and float(r.get("brake") or 0) <= 100.0 for r in rows
    ]
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and key(rows[j + 1]) == key(rows[i]):
            j += 1
        if j - i + 1 >= FROZEN_RUN:
            for k in range(i + 1, j + 1):
                keep[k] = False
        i = j + 1
    return [r for r, ok in zip(rows, keep, strict=True) if ok]


def reference_from_lap(
    session: dict[str, Any], lap: dict[str, Any], model: TrackModel, client: OpenF1Client
) -> ReferenceLap:
    """Map one OpenF1 lap's speed samples onto the centre line.

    Raises:
        OpenF1Error: No location or car data for the lap.

    """
    session_key = str(session["session_key"])
    location = lap_samples(client, session_key, lap, "location")
    raw_car_data = lap_samples(client, session_key, lap, "car_data")
    car_data = valid_car_samples(raw_car_data)
    if len(location) < 2 or not car_data:
        raise OpenF1Error(
            f"no location / car_data for car {lap['driver_number']} lap {lap['lap_number']}"
        )
    t_loc = np.array([_timestamp(r) for r in location])
    # Path-continuous projection: nearest-point projection jumps between the
    # two branches where a track crosses itself (Suzuka's figure-eight bridge).
    s_loc = project_path_to_s(
        model,
        [r["x"] * OPENF1_POS_UNIT_M for r in location],
        [r["y"] * OPENF1_POS_UNIT_M for r in location],
    )
    t_car = np.array([_timestamp(r) for r in car_data])
    s_car = np.interp(t_car, t_loc, s_loc) % model.length_m
    speed = np.array([float(r["speed"]) for r in car_data])
    order = np.argsort(s_car)
    return ReferenceLap(
        lap_time_s=float(lap["lap_duration"]),
        s_m=s_car[order],
        speed_kmh=speed[order],
        session_date=datetime.fromisoformat(str(session["date_start"])).date(),
        source={
            "provider": "openf1",
            "session_key": session_key,
            "driver_number": str(lap["driver_number"]),
            "lap_number": str(lap["lap_number"]),
            "car_samples_dropped": str(len(raw_car_data) - len(car_data)),
        },
    )


def load_reference_lap(track: TrackConfig, model: TrackModel, client: OpenF1Client) -> ReferenceLap:
    """Fetch the session's fastest lap (pole) and map its speed samples.

    Raises:
        OpenF1Error: No session, lap, location or car data.

    """
    session, lap = fastest_lap(track, client)
    return reference_from_lap(session, lap, model, client)


def section_coverage(s_m: FloatArray, length_m: float, section_m: float) -> tuple[int, int]:
    """Track sections of ``section_m`` holding at least one sample, and the section count."""
    n_sections = int(np.ceil(length_m / section_m))
    covered = np.unique(np.floor((np.asarray(s_m) % length_m) / section_m).astype(np.int64))
    return int(covered.size), n_sections


def load_team_references(
    track: TrackConfig,
    model: TrackModel,
    client: OpenF1Client,
    grid: GridConfig,
    min_sections: int | None = None,
    section_m: float = 250.0,
    max_laps_tried: int = 8,
) -> dict[str, ReferenceLap]:
    """Each team's fastest timed lap of the session (the better of its drivers).

    The lap TIME is always the team's fastest lap. With ``min_sections`` the
    speed TRACE comes from the team's fastest lap whose valid speed samples
    cover at least that many ``section_m`` sections (owner round 13: frozen
    car_data can leave a fast lap with no trace for part of the track); a team
    with no such lap among its ``max_laps_tried`` fastest is left out with a
    warning. Drivers are matched to teams by car number on ``grid``.

    Raises:
        OpenF1Error: No session, timed laps, or samples for a team's lap.

    """
    session = find_session(track, client)
    session_key = str(session["session_key"])
    number_to_team = {d.number: t.team_id for t in grid.teams for d in t.drivers}
    by_team: dict[str, list[dict[str, Any]]] = {}
    for lap in client.get("laps", [("session_key=", session_key)]):
        if not (lap.get("lap_duration") and lap.get("date_start")) or lap.get("is_pit_out_lap"):
            continue
        team_id = number_to_team.get(int(lap["driver_number"]))
        if team_id is None:
            logger.warning("car %s is not on grid %s; skipped", lap["driver_number"], grid.grid_id)
            continue
        by_team.setdefault(team_id, []).append(lap)
    if not by_team:
        raise OpenF1Error(f"no timed laps in OpenF1 session {session_key}")
    refs: dict[str, ReferenceLap] = {}
    for team_id, laps in by_team.items():
        laps.sort(key=lambda lap: float(lap["lap_duration"]))
        fastest = reference_from_lap(session, laps[0], model, client)
        if min_sections is None:
            refs[team_id] = fastest
            continue
        for lap in laps[:max_laps_tried]:
            try:
                ref = fastest if lap is laps[0] else reference_from_lap(session, lap, model, client)
            except OpenF1Error as exc:  # e.g. not cached and the API refuses (live session)
                logger.warning("%s: lap %s skipped: %s", team_id, lap["lap_number"], exc)
                continue
            covered, n_sections = section_coverage(ref.s_m, model.length_m, section_m)
            if covered >= min_sections:
                source = {**ref.source, "target_lap_number": fastest.source["lap_number"],
                          "target_driver_number": fastest.source["driver_number"],
                          "sections_covered": f"{covered}/{n_sections}"}  # fmt: skip
                refs[team_id] = ReferenceLap(
                    fastest.lap_time_s, ref.s_m, ref.speed_kmh, ref.session_date, source
                )
                break
        else:
            logger.warning(
                "%s: none of its %d fastest laps covers %d sections; left out",
                team_id, max_laps_tried, min_sections,
            )  # fmt: skip
    return refs


def rule_set_for_date(on: date, config_dir: Path) -> RuleSet:
    """Pick the Rule Set in force on a date: the latest ``effective_from`` not after it.

    Raises:
        ConfigError: No Rule Set was in force on that date.

    """
    candidates = []
    for rule_set_id in RULE_SET_IDS:
        rules = load_rule_set(rule_set_id, config_dir)
        if not isinstance(rules.effective_from, str) and rules.effective_from <= on:
            candidates.append(rules)
    if not candidates:
        raise ConfigError(f"no Rule Set in force on {on}")
    return max(candidates, key=lambda r: r.effective_from)


# --------------------------------------------------------------------------- #
# Simulation under reference (qualifying) conditions
# --------------------------------------------------------------------------- #


def track_arrays(model: TrackModel, track: TrackConfig) -> TrackArrays:
    """Grid and zone masks for the lap simulation."""
    return TrackArrays(
        s_m=model.s_m,
        kappa=model.curvature_per_m,
        straight_mode=zone_mask(track, model.s_m, tag="straight_mode_allowed"),
        accel_zone=zone_mask(track, model.s_m, tag="acceleration_zone"),
        length_m=model.length_m,
    )


def quali_fuel_kg(track: TrackConfig) -> float:
    """Return the track's qualifying fuel load.

    Raises:
        ConfigError: The track does not set ``quali_fuel_kg``.

    """
    fuel = track.quali_fuel_kg
    if fuel is None or isinstance(fuel, str):
        raise ConfigError(f"track {track.track_id} needs quali_fuel_kg, which is {fuel}")
    return float(fuel)


def simulate_quali_lap(
    arrays: TrackArrays,
    track: TrackConfig,
    rules: RuleSet,
    team: TeamPerformance,
    tyres: TyreConfig,
    app: AppConfig,
    deploy: DeployMode = "policy",
    compound: Compound = Compound.SOFT,
) -> PolicyResult | LapResult:
    """One flying lap under qualifying conditions; a :class:`PolicyResult` with ``policy``.

    Raises:
        ConfigError: A value the simulation needs is still a placeholder.

    """
    limit = rules.energy.harvest_max_mj_per_lap_quali
    if isinstance(limit, str):
        raise ConfigError(f"energy.harvest_max_mj_per_lap_quali is {limit}")
    fuel_kg = quali_fuel_kg(track)
    prof = reference_params(rules, team, tyres, compound, app, track, fuel_kg)
    batt = battery_params(rules, team, float(limit))
    fuel = fuel_params(rules, team)

    def run(plan: DeployPlan | None) -> LapResult:
        return simulate_lap(
            arrays.s_m,
            arrays.kappa,
            arrays.straight_mode,
            arrays.accel_zone,
            arrays.length_m,
            prof,
            batt,
            fuel,
            battery_start_j=batt.e_usable_max_j,
            fuel_kg=fuel_kg,
            deploy_zone=None if plan is None else plan.deploy_zone,
            zone_budget_j=None if plan is None else plan.zone_budget_j,
            superclip=None if plan is None else plan.superclip,
        )

    if deploy == "greedy":
        return run(None)
    if deploy == "policy":  # owner round 14: spread the energy by gain per MJ
        profile = speed_profile(
            arrays.s_m, arrays.kappa, arrays.straight_mode, arrays.accel_zone, arrays.length_m, prof
        )
        ds = arrays.length_m / arrays.s_m.size
        full = profile_full_throttle(profile.v_accel_ms, profile.v_brake_ms, profile.v_corner_ms)
        alloc = allocate(
            profile.v_ref_ms, full, arrays.accel_zone, ds, prof.powertrain,
            batt.discharge_efficiency,
        )  # fmt: skip
        # Qualifying: the battery may end near empty at the line.
        return settle_spread(
            track, arrays.s_m, alloc, batt.e_usable_max_j, 0.0, batt.harvest_limit_j,
            superclip_harvest_w(batt), run, batt.e_usable_max_j,
        )  # fmt: skip
    if deploy == "anywhere":  # T-028 (owner decision (c)): deploy anywhere, clip the shortfall
        return settle_deploy_anywhere(
            track, arrays.s_m, batt.harvest_limit_j, superclip_harvest_w(batt), run
        )
    return settle_plan(  # T-026: deploy only in acceleration zones
        track,
        arrays.s_m,
        batt.e_usable_max_j,
        batt.harvest_limit_j,
        superclip_harvest_w(batt),
        run,
    )


def lap_of(result: PolicyResult | LapResult) -> LapResult:
    """Return the simulated lap of a policy or greedy result."""
    return result.lap if isinstance(result, PolicyResult) else result


def speed_rmse_kmh(sim: LapResult, ref: ReferenceLap) -> float:
    """RMSE of simulated vs real speed at the real samples' positions."""
    s_ext = np.concatenate((sim.s_m, [sim.s_m[-1] + (sim.s_m[1] - sim.s_m[0])]))
    v_ext = np.concatenate((sim.v_ms, sim.v_ms[:1])) * MS_TO_KMH
    sim_at_ref = np.interp(ref.s_m, s_ext, v_ext)
    return float(np.sqrt(np.mean((sim_at_ref - ref.speed_kmh) ** 2)))


def positions(times: dict[str, float]) -> dict[str, int]:
    """1-based order of teams by time."""
    return {team_id: i + 1 for i, team_id in enumerate(sorted(times, key=times.__getitem__))}


def compare_teams(
    sims: dict[str, LapResult],
    refs: dict[str, ReferenceLap],
    app: AppConfig,
    rmse_limit_kmh: float | None = None,
) -> list[TeamResult]:
    """Score each team's simulated lap against its own target; real-order sorted.

    ``rmse_limit_kmh`` overrides ``calibration.speed_rmse_kmh`` (provisional runs).
    """
    real_pos = positions({t: refs[t].lap_time_s for t in sims})
    sim_pos = positions({t: sims[t].lap_time_s for t in sims})
    tol = app.calibration
    limit = tol.speed_rmse_kmh if rmse_limit_kmh is None else rmse_limit_kmh
    results = []
    for team_id in sorted(sims, key=real_pos.__getitem__):
        sim, ref = sims[team_id], refs[team_id]
        delta = (sim.lap_time_s - ref.lap_time_s) / ref.lap_time_s
        rmse = speed_rmse_kmh(sim, ref)
        results.append(
            TeamResult(
                team_id=team_id,
                target_s=ref.lap_time_s,
                lap_time_s=sim.lap_time_s,
                delta_pct=100.0 * delta,
                speed_rmse_kmh=rmse,
                lap_time_ok=abs(delta) <= tol.lap_time_tolerance,
                speed_ok=rmse <= limit,
                real_position=real_pos[team_id],
                sim_position=sim_pos[team_id],
                harvested_mj=sim.harvested_j / 1e6,
                drawn_mj=sim.drawn_j / 1e6,
            )
        )
    return results


def order_ok(results: list[TeamResult], max_error: int) -> bool:
    """Every team's simulated position within ``max_error`` places of its real one."""
    return all(abs(r.sim_position - r.real_position) <= max_error for r in results)


def write_report(
    results: list[TeamResult],
    rules: RuleSet,
    out_dir: Path,
    track_id: str,
    extra: dict[str, str] | None = None,
) -> Path:
    """Write ``<out_dir>/<track_id>.parquet``: one row per team, context in the metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{track_id}.parquet"
    table = pl.DataFrame([asdict(r) for r in results]).to_arrow()
    meta = {"track_id": track_id, "rule_set_id": rules.rule_set_id, **(extra or {})}
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def log_results(
    results: list[TeamResult], app: AppConfig, rmse_limit_kmh: float | None = None
) -> None:
    """Print the comparison table."""
    tol = app.calibration
    limit = tol.speed_rmse_kmh if rmse_limit_kmh is None else rmse_limit_kmh
    logger.info(
        "%-13s %8s %8s %8s %9s %5s %5s  %s",
        "team",
        "target",
        "sim",
        "delta%",
        "RMSE km/h",
        "real",
        "sim",
        f"(|delta| <= {tol.lap_time_tolerance:.0%}, RMSE <= {limit:g})",
    )
    for r in results:
        logger.info(
            "%-13s %8.3f %8.3f %+8.2f %9.1f %5d %5d  %s",
            r.team_id,
            r.target_s,
            r.lap_time_s,
            r.delta_pct,
            r.speed_rmse_kmh,
            r.real_position,
            r.sim_position,
            "PASS" if r.lap_time_ok and r.speed_ok else "FAIL",
        )
    logger.info(
        "team order within +-%d places: %s",
        tol.max_order_error,
        "PASS" if order_ok(results, tol.max_order_error) else "FAIL",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print lap-time delta, speed RMSE and order per team. Exit 0 OK, 1 invalid, 2 no data."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True, help="track_id, e.g. suzuka")
    parser.add_argument(
        "--rules", choices=RULE_SET_IDS, help="default: in force on the reference date"
    )
    parser.add_argument("--grid", default="real_2026", help="grid whose teams are simulated")
    parser.add_argument("--team", help="one team_id (default: every team on the grid)")
    parser.add_argument("--deploy", choices=DEPLOY_MODES, default="policy")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
        model = read_track_model(Path(app.paths.tracks) / f"{track.track_id}.parquet")
        grid = load_grid(args.grid, args.config_dir)
        teams = load_team_performance(args.config_dir)
        tyres = load_tyres(args.config_dir)
    except (ConfigError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return EXIT_INVALID

    client = OpenF1Client(app.openf1, Path(app.paths.openf1_cache))
    try:
        refs = load_team_references(
            track, model, client, grid, app.calibration.min_section_coverage,
            app.calibration.coverage_section_m,
        )  # fmt: skip
    except OpenF1Error as exc:
        logger.error("UNAVAILABLE: reference laps: %s", exc)
        return EXIT_UNAVAILABLE

    team_ids = [args.team] if args.team else [t for t in grid.team_ids if t in refs]
    session_date = next(iter(refs.values())).session_date
    try:
        rules = (
            load_rule_set(args.rules, args.config_dir)
            if args.rules
            else rule_set_for_date(session_date, args.config_dir)
        )
        arrays = track_arrays(model, track)
        sims = {
            t: lap_of(
                simulate_quali_lap(arrays, track, rules, teams.teams[t], tyres, app, args.deploy)
            )
            for t in team_ids
        }
    except (ConfigError, KeyError) as exc:
        logger.error("%s", exc)
        return EXIT_INVALID

    pole = min(refs.values(), key=lambda r: r.lap_time_s)
    logger.info(
        "%s: rules %s, deploy %s, pole %.3f s (OpenF1 session %s, car %s, %s)",
        track.track_id,
        rules.rule_set_id,
        args.deploy,
        pole.lap_time_s,
        pole.source["session_key"],
        pole.source["driver_number"],
        session_date,
    )
    results = compare_teams(sims, {t: refs[t] for t in sims}, app)
    log_results(results, app)
    path = write_report(
        results,
        rules,
        Path(app.paths.calibration),
        track.track_id,
        {
            "deploy": args.deploy,
            "pole_s": repr(pole.lap_time_s),
            "date": session_date.isoformat(),
            "pole_source": json.dumps(pole.source),
        },  # fmt: skip
    )
    logger.info("report -> %s", path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
