"""F20 calibration fit for one track (T-026, owner round 10).

Two stages, within the physically plausible bounds in ``app.yaml:
calibration.bounds`` (a value that ends on a bound is reported: the model, not
the number, is then wrong):

1. Shared, all teams: SOFT ``mu_base`` and the default ``long_grip_ratio``,
   fitted to the average of the top-5 teams' laps (same Pirelli tyres for
   everyone, so grip must not differ per team). A shared aero set is fitted
   alongside only so the grip fit is not distorted by placeholder aero; only
   the grip values are kept (and the shared aero becomes stage 2's start
   point and the neutral values for fictional teams).
2. Per team: ``cla_corner``, ``cda_straight``, ``cda_corner`` and
   ``pu_power_scale``, fitted to that team's own fastest lap.

Objective: ``(lap-time error / tolerance)^2 + (speed RMSE / RMSE limit)^2``,
minimised with Powell's method on bound-normalised parameters (the lap
simulation is not smooth). Laps use ``compare.simulate_quali_lap`` with the
calibration deploy policy. Plausibility is a constraint inside the fit (owner
round 15): every simulated lap pays a penalty for peak lateral or braking
acceleration above ``max_lateral_g`` / ``max_braking_g`` and for an Esses corner
minimum more than ``esses_max_excess_kmh`` above the real median minimum.

Verdict (owner round 15): MUST every team within ``lap_time_tolerance``, order
within ``max_order_error``, plausibility met on every team's lap, no shared tyre
coefficient (stage 1 grip) on a bound; then PASS with every RMSE within
``speed_rmse_kmh``, ACCEPTED within ``speed_rmse_kmh_provisional`` (per-corner
residuals go to the notes), else FAIL. The config files are rewritten unless
the verdict is FAIL; then the report is printed and the exit code is 3 (stop
and report; bounds are never widened).

Usage::

    python -m pitwall_sim.calibration.fit --track suzuka [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

from pitwall_sim.calibration.compare import (
    ReferenceLap,
    TeamResult,
    TrackArrays,
    compare_teams,
    lap_of,
    load_team_references,
    log_results,
    order_ok,
    rule_set_for_date,
    simulate_quali_lap,
    speed_rmse_kmh,
    track_arrays,
)
from pitwall_sim.car.dynamics import G_MS2
from pitwall_sim.car.lap_sim import LapResult
from pitwall_sim.config.loader import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    load_app,
    load_grid,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import (
    AppConfig,
    Compound,
    RuleSet,
    TeamPerformance,
    TrackConfig,
    TyreConfig,
)
from pitwall_sim.track.builder import TrackModel, read_track_model
from pitwall_sim.track.openf1 import OpenF1Client, OpenF1Error

logger = logging.getLogger(__name__)

AERO = ("cla_corner", "cda_straight", "cda_corner")
STAGE1 = ("mu_base_soft", "long_grip_ratio", "k_load", *AERO)
STAGE2 = (*AERO, "pu_power_scale")
GRIP = ("mu_base_soft", "long_grip_ratio", "k_load")
#: Tyre values (tyres.yaml) among the fitted coefficients; the rest are team values.
TYRE_KEYS = ("mu_base_soft", "k_load")
TOP_N = 5
#: A value within this share of the bound range from a bound counts as on it.
ON_BOUND_SHARE = 0.005
#: Corners whose minimum speed is reported for the pole team: name -> (from, to) corner ids.
REPORT_CORNERS = {"hairpin (T11)": ("T11", "T11"), "Spoon (T13-T14)": ("T13", "T14"),
                  "130R (T15)": ("T15", "T15")}  # fmt: skip
CORNER_WINDOW_M = 60.0

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNAVAILABLE = 2
EXIT_TARGETS_MISSED = 3


@dataclass(frozen=True)
class FitContext:
    """Everything fixed while fitting one track."""

    arrays: TrackArrays
    track: TrackConfig
    rules: RuleSet
    tyres: TyreConfig
    app: AppConfig
    esses_real: dict[str, tuple[float, float]] = field(default_factory=dict)
    """Esses corner -> (s_m, real median minimum km/h), for the plausibility constraint."""


@dataclass(frozen=True)
class FitResult:
    """Fitted values and how the fit went."""

    values: dict[str, float]
    objective: float
    evaluations: int
    on_bound: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Applying coefficients
# --------------------------------------------------------------------------- #


def apply(
    team: TeamPerformance, tyres: TyreConfig, values: dict[str, float]
) -> tuple[TeamPerformance, TyreConfig]:
    """Return the team and tyre config with ``values`` applied.

    ``mu_base_soft`` goes to the SOFT compound and ``k_load`` to the shared tyre
    load sensitivity (owner round 14); the rest are team values.
    """
    team_update = {k: v for k, v in values.items() if k not in TYRE_KEYS}
    if "mu_base_soft" in values:
        soft = tyres.compounds[Compound.SOFT].model_copy(update={"mu_base": values["mu_base_soft"]})
        tyres = tyres.model_copy(update={"compounds": {**tyres.compounds, Compound.SOFT: soft}})
    if "k_load" in values:
        load = tyres.load_sensitivity.model_copy(update={"k_load": values["k_load"]})
        tyres = tyres.model_copy(update={"load_sensitivity": load})
    return team.model_copy(update=team_update), tyres


def simulate(ctx: FitContext, team: TeamPerformance, values: dict[str, float]) -> LapResult:
    """One qualifying lap with ``values`` applied."""
    team2, tyres2 = apply(team, ctx.tyres, values)
    return lap_of(simulate_quali_lap(ctx.arrays, ctx.track, ctx.rules, team2, tyres2, ctx.app))


def objective(sim_time_s: float, target_s: float, rmse_kmh: float, app: AppConfig) -> float:
    """``(lap-time error / tolerance)^2 + (RMSE / RMSE limit)^2``."""
    lap = (sim_time_s - target_s) / target_s / app.calibration.lap_time_tolerance
    speed = rmse_kmh / app.calibration.speed_rmse_kmh
    return lap * lap + speed * speed


#: Name reported when the Straight-Mode-drag ordering constraint is active.
DRAG_ORDER = "cda_straight<=cda_corner"
#: Objective penalty per (m^2)^2 of Straight Mode drag above Corner Mode drag.
DRAG_ORDER_PENALTY = 1e4


def drag_order_penalty(values: dict[str, float]) -> float:
    """Penalty when Straight Mode (wings open) has more drag than Corner Mode.

    Physical plausibility, like the bounds: opening the wings must not add drag.
    Zero when the ordering holds or a value is not being fitted.
    """
    if "cda_straight" not in values or "cda_corner" not in values:
        return 0.0
    excess = values["cda_straight"] - values["cda_corner"]
    return DRAG_ORDER_PENALTY * excess * excess if excess > 0.0 else 0.0


#: Objective penalty per (relative excess over a plausibility limit)^2 (owner round 15).
PLAUSIBILITY_PENALTY = 1e4
#: Window around an Esses corner for its minimum speed, m (as in the report).
ESSES_WINDOW_M = 40.0


def _near(s_m: npt.NDArray[np.float64], centre_m: float, length_m: float) -> npt.NDArray[np.bool_]:
    return np.abs(((s_m - centre_m + length_m / 2) % length_m) - length_m / 2) <= ESSES_WINDOW_M


def esses_real_minima(
    track: TrackConfig, length_m: float, refs: Sequence[ReferenceLap], corners: Sequence[str]
) -> dict[str, tuple[float, float]]:
    """Per Esses corner: ``(s_m, median real minimum km/h)`` within +-40 m."""
    s_of = {c.corner_id: c.s_m for c in track.corners}
    out = {}
    for cid in corners:
        if cid not in s_of:
            continue
        mins = [
            float(ref.speed_kmh[sel].min())
            for ref in refs
            if (sel := _near(ref.s_m, s_of[cid], length_m)).sum() >= 2
        ]
        out[cid] = (s_of[cid], float(np.median(mins)) if mins else float("nan"))
    return out


def plausibility(ctx: FitContext, lap: LapResult) -> tuple[float, float, float]:
    """``(peak lateral g, peak braking g, worst Esses excess km/h)`` of one lap."""
    lat_g, brake_g = peak_accelerations_g(lap, ctx.arrays.kappa)
    s = ctx.arrays.s_m
    length = float(s.size * (s[1] - s[0]))
    excess = [
        float(lap.v_ms[_near(s, sc, length)].min() * 3.6) - real
        for sc, real in ctx.esses_real.values()
        if real == real  # not NaN
    ]
    return lat_g, brake_g, max(excess, default=0.0)


def plausibility_penalty(ctx: FitContext, lap: LapResult) -> float:
    """Constraint term: :data:`PLAUSIBILITY_PENALTY` x squared relative excess over each limit."""
    cal = ctx.app.calibration
    lat_g, brake_g, esses = plausibility(ctx, lap)
    total = 0.0
    for value, limit in (
        (lat_g, cal.max_lateral_g), (brake_g, cal.max_braking_g),
        (esses, cal.esses_max_excess_kmh),
    ):  # fmt: skip
        over = max(value - limit, 0.0) / limit
        total += over * over
    return PLAUSIBILITY_PENALTY * total


def on_bounds(values: dict[str, float], bounds: dict[str, tuple[float, float]]) -> tuple[str, ...]:
    """Names of values within :data:`ON_BOUND_SHARE` of a bound, plus an active drag order."""
    hits = []
    for name, value in values.items():
        lo, hi = bounds[name]
        margin = ON_BOUND_SHARE * (hi - lo)
        if value <= lo + margin or value >= hi - margin:
            hits.append(name)
    if "cda_straight" in values and "cda_corner" in values:
        lo, hi = bounds["cda_straight"]
        if values["cda_straight"] >= values["cda_corner"] - ON_BOUND_SHARE * (hi - lo):
            hits.append(DRAG_ORDER)
    return tuple(hits)


def fit(
    names: Sequence[str],
    start: dict[str, float],
    bounds: dict[str, tuple[float, float]],
    cost: Callable[[dict[str, float]], float],
    max_evals: int,
) -> FitResult:
    """Minimise ``cost`` over ``names`` within ``bounds`` (Powell, bound-normalised)."""
    lows = np.array([bounds[n][0] for n in names])
    spans = np.array([bounds[n][1] - bounds[n][0] for n in names])
    u0 = np.clip((np.array([start[n] for n in names]) - lows) / spans, 0.0, 1.0)
    evaluations = 0

    def to_values(u: np.ndarray) -> dict[str, float]:
        x = lows + np.clip(u, 0.0, 1.0) * spans
        return {n: float(v) for n, v in zip(names, x, strict=True)}

    def f(u: np.ndarray) -> float:
        nonlocal evaluations
        evaluations += 1
        return cost(to_values(u))

    result = minimize(
        f,
        u0,
        method="Powell",
        bounds=[(0.0, 1.0)] * len(names),
        options={"xtol": 1e-3, "ftol": 1e-4, "maxfev": max_evals},
    )
    values = to_values(result.x)
    return FitResult(values, float(result.fun), evaluations, on_bounds(values, bounds))


def stage1(
    ctx: FitContext, base: TeamPerformance, refs: list[ReferenceLap], max_evals: int
) -> FitResult:
    """Shared grip (and nuisance aero) fitted to the top-N teams' average lap."""
    target = float(np.mean([r.lap_time_s for r in refs]))
    bounds = ctx.app.calibration.bounds
    soft_mu = ctx.tyres.compounds[Compound.SOFT].mu_base
    start = {
        "mu_base_soft": float(soft_mu)
        if not isinstance(soft_mu, str)
        else bounds["mu_base_soft"][0],
        "k_load": ctx.tyres.load_sensitivity.k_load,
        **{n: float(getattr(base, n)) for n in ("long_grip_ratio", *AERO)},
    }

    def cost(values: dict[str, float]) -> float:
        sim = simulate(ctx, base, values)
        rmse = float(np.mean([speed_rmse_kmh(sim, r) for r in refs]))
        return (
            objective(sim.lap_time_s, target, rmse, ctx.app)
            + drag_order_penalty(values)
            + plausibility_penalty(ctx, sim)
        )

    return fit(STAGE1, start, bounds, cost, max_evals)


@dataclass(frozen=True)
class TeamJob:
    """One stage-2 fit, picklable for a worker process."""

    ctx: FitContext
    team_id: str
    team: TeamPerformance
    grip: dict[str, float]
    start: dict[str, float]
    ref: ReferenceLap
    max_evals: int


@dataclass(frozen=True)
class TeamFit:
    """A finished stage-2 fit with the lap it produces."""

    team_id: str
    fit: FitResult
    lap_time_s: float
    rmse_kmh: float


def run_team_job(job: TeamJob) -> TeamFit:
    """Fit one team (runs in a worker process)."""
    fitted = stage2(job.ctx, job.team, job.grip, job.start, job.ref, job.max_evals)
    sim = simulate(job.ctx, job.team, {**job.grip, **fitted.values})
    return TeamFit(job.team_id, fitted, sim.lap_time_s, speed_rmse_kmh(sim, job.ref))


def _fit_to_json(f: FitResult) -> dict[str, Any]:
    return {"values": f.values, "objective": f.objective, "evaluations": f.evaluations,
            "on_bound": list(f.on_bound)}  # fmt: skip


def _fit_from_json(d: dict[str, Any]) -> FitResult:
    return FitResult(
        {k: float(v) for k, v in d["values"].items()},
        float(d["objective"]),
        int(d["evaluations"]),
        tuple(d["on_bound"]),
    )


def load_checkpoint(path: Path, key: dict[str, str]) -> dict[str, Any]:
    """Load saved progress for the same track / Rule Set / grid, or start empty."""
    if not path.exists():
        return {"key": key, "stage1": None, "teams": {}}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("key") != key:
        logger.warning(
            "checkpoint %s is for %s, not %s: starting fresh", path, data.get("key"), key
        )
        return {"key": key, "stage1": None, "teams": {}}
    return data


def save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    """Write progress atomically (a crash mid-write keeps the previous file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def stage2(
    ctx: FitContext,
    team: TeamPerformance,
    grip: dict[str, float],
    start: dict[str, float],
    ref: ReferenceLap,
    max_evals: int,
) -> FitResult:
    """One team's aero and ICE scale fitted to its own lap, grip fixed."""
    bounds = ctx.app.calibration.bounds

    def cost(values: dict[str, float]) -> float:
        sim = simulate(ctx, team, {**grip, **values})
        lap = objective(sim.lap_time_s, ref.lap_time_s, speed_rmse_kmh(sim, ref), ctx.app)
        return lap + drag_order_penalty(values) + plausibility_penalty(ctx, sim)

    return fit(STAGE2, start, bounds, cost, max_evals)


# --------------------------------------------------------------------------- #
# Writing the config
# --------------------------------------------------------------------------- #


PROVISIONAL_MARK = "# CALIBRATED-PROVISIONAL (T-026, RMSE limit relaxed)"


def _calibrated_comment(
    track_id: str,
    bounds: tuple[float, float],
    note: str = "",
    provisional: bool = False,
    task: str = "T-026",
) -> str:
    extra = f"; {note}" if note else ""
    if provisional:
        mark = PROVISIONAL_MARK if task == "T-026" else f"# CALIBRATED-PROVISIONAL ({task})"
        return f"{mark} {track_id} bounds {bounds[0]:g}-{bounds[1]:g}{extra}"
    return f"# CALIBRATED {task} {track_id} (bounds {bounds[0]:g}-{bounds[1]:g}{extra})"


def set_team_value(text: str, team_id: str, key: str, value: float, comment: str) -> str:
    """Replace ``key`` inside one team block of performance.yaml, keeping the layout."""
    block = re.search(rf"^  {re.escape(team_id)}:.*\n((?:    .*\n)+)", text, flags=re.MULTILINE)
    if block is None:
        raise ConfigError(f"performance.yaml has no team {team_id}")
    body = block.group(1)
    new_body, n = re.subn(
        rf"^    {re.escape(key)}: .*$",
        f"    {key}: {value:.4f} {comment}",
        body,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise ConfigError(f"performance.yaml team {team_id} has no single {key}")
    return text[: block.start(1)] + new_body + text[block.end(1) :]


def set_soft_mu(text: str, value: float, comment: str) -> str:
    """Replace SOFT ``mu_base`` in tyres.yaml, keeping the layout."""
    block = re.search(r"^  SOFT:\n((?:    .*\n)+)", text, flags=re.MULTILINE)
    if block is None:
        raise ConfigError("tyres.yaml has no SOFT compound")
    body, n = re.subn(
        r"^    mu_base: .*$",
        f"    mu_base: {value:.4f} {comment}",
        block.group(1),
        flags=re.MULTILINE,
    )
    if n != 1:
        raise ConfigError("tyres.yaml SOFT has no single mu_base")
    return text[: block.start(1)] + body + text[block.end(1) :]


def set_k_load(text: str, value: float, comment: str) -> str:
    """Replace the shared ``load_sensitivity.k_load`` in tyres.yaml, keeping the layout."""
    new, n = re.subn(
        r"^  k_load: .*$", f"  k_load: {value:.4f} {comment}", text, flags=re.MULTILINE
    )
    if n != 1:
        raise ConfigError("tyres.yaml has no single load_sensitivity.k_load")
    return new


def write_config(
    config_dir: Path,
    track_id: str,
    grip: dict[str, float],
    shared_aero: dict[str, float],
    per_team: dict[str, dict[str, float]],
    all_team_ids: Sequence[str],
    bounds: dict[str, tuple[float, float]],
    provisional: bool = False,
    task: str = "T-026",
) -> None:
    """Write calibrated values into performance.yaml and tyres.yaml (comments kept).

    ``provisional`` marks every written value ``CALIBRATED-PROVISIONAL`` (owner
    round 11: accepted with the relaxed RMSE limit until T-02A).

    Teams without a reference lap (the fictional grid) get the shared stage-1
    aero and a neutral ICE scale of 1.0, so no team gets an invented advantage.
    """
    perf_path = config_dir / "teams" / "performance.yaml"
    text = perf_path.read_text(encoding="utf-8")
    for team_id in all_team_ids:
        text = set_team_value(
            text, team_id, "long_grip_ratio", grip["long_grip_ratio"],
            _calibrated_comment(
                track_id, bounds["long_grip_ratio"], "shared", provisional, task
            ),
        )  # fmt: skip
        if team_id in per_team:
            for key, value in per_team[team_id].items():
                text = set_team_value(
                    text,
                    team_id,
                    key,
                    value,
                    _calibrated_comment(track_id, bounds[key], provisional=provisional, task=task),
                )
        else:
            neutral = {**shared_aero, "pu_power_scale": 1.0}
            for key, value in neutral.items():
                text = set_team_value(
                    text, team_id, key, value,
                    _calibrated_comment(
                        track_id, bounds[key], "stage-1 shared, neutral team", provisional, task
                    ),
                )  # fmt: skip
    perf_path.write_text(text, encoding="utf-8", newline="\n")

    tyre_path = config_dir / "tyres.yaml"
    tyre_text = set_soft_mu(
        tyre_path.read_text(encoding="utf-8"),
        grip["mu_base_soft"],
        _calibrated_comment(track_id, bounds["mu_base_soft"], "shared", provisional, task),
    )
    if "k_load" in grip:
        tyre_text = set_k_load(
            tyre_text,
            grip["k_load"],
            _calibrated_comment(track_id, bounds["k_load"], "shared", provisional, task),
        )
    tyre_path.write_text(tyre_text, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- #
# Report helpers
# --------------------------------------------------------------------------- #


def peak_accelerations_g(lap: LapResult, kappa: npt.NDArray[np.float64]) -> tuple[float, float]:
    """Peak lateral ``v^2 |kappa|`` and peak braking ``-v dv/ds`` of a lap, in g."""
    ds = float(lap.s_m[1] - lap.s_m[0])
    v = lap.v_ms
    lateral = v * v * np.abs(kappa)
    braking = -v * np.diff(v, append=v[:1]) / ds
    return float(lateral.max() / G_MS2), float(max(braking.max(), 0.0) / G_MS2)


def esses_excess_kmh(
    track: TrackConfig, model: TrackModel, sim: LapResult, refs: Sequence[ReferenceLap],
    corners: Sequence[str],
) -> dict[str, tuple[float, float]]:  # fmt: skip
    """Per corner: (sim minimum, real median minimum) within +-40 m, km/h."""
    length = model.length_m
    s_of = {c.corner_id: c.s_m for c in track.corners}
    out = {}
    for cid in corners:
        if cid not in s_of:
            continue
        sc = s_of[cid]
        near = np.abs(((model.s_m - sc + length / 2) % length) - length / 2) <= 40.0
        mins = []
        for ref in refs:
            sel = np.abs(((ref.s_m - sc + length / 2) % length) - length / 2) <= 40.0
            if sel.sum() >= 2:
                mins.append(float(ref.speed_kmh[sel].min()))
        real = float(np.median(mins)) if mins else float("nan")
        out[cid] = (float(sim.v_ms[near].min() * 3.6), real)
    return out


def corner_residuals(
    track: TrackConfig, model: TrackModel, sims: dict[str, LapResult],
    refs: dict[str, ReferenceLap],
) -> dict[str, list[float]]:  # fmt: skip
    """Per corner: ``[median, worst]`` over teams of (sim - real) minimum speed, km/h."""
    length = model.length_m
    out = {}
    for corner in sorted(track.corners, key=lambda c: c.s_m):
        near = _near(model.s_m, corner.s_m, length)
        diffs = []
        for team, sim in sims.items():
            sel = _near(refs[team].s_m, corner.s_m, length)
            if sel.sum() >= 2:
                diffs.append(float(sim.v_ms[near].min() * 3.6 - refs[team].speed_kmh[sel].min()))
        if diffs:
            worst = max(diffs, key=abs)
            out[corner.corner_id] = [round(float(np.median(diffs)), 1), round(worst, 1)]
    return out


def verdict(results: Sequence[TeamResult], report: dict[str, Any], app: AppConfig) -> str:
    """``PASS``, ``ACCEPTED`` or ``FAIL`` under the owner round 15 acceptance."""
    cal = app.calibration
    extras = report["extras"]
    musts = (
        all(r.lap_time_ok for r in results)
        and order_ok(list(results), cal.max_order_error)
        and bool(extras["plausibility"]["plausible"])
        and not set(extras["on_bound"].get("stage 1", [])) & set(GRIP)
    )
    worst_rmse = max(r.speed_rmse_kmh for r in results)
    if not musts or worst_rmse > cal.speed_rmse_kmh_provisional:
        return "FAIL"
    return "PASS" if worst_rmse <= cal.speed_rmse_kmh else "ACCEPTED"


def corner_min_speeds(
    track: TrackConfig, model: TrackModel, sim: LapResult, ref: ReferenceLap
) -> dict[str, tuple[float, float]]:
    """Minimum (simulated, real) speed in km/h around the report corners."""
    s_of = {c.corner_id: c.s_m for c in track.corners}
    out = {}
    for name, (first, last) in REPORT_CORNERS.items():
        lo, hi = s_of[first] - CORNER_WINDOW_M, s_of[last] + CORNER_WINDOW_M
        sim_sel = (model.s_m >= lo) & (model.s_m <= hi)
        ref_sel = (ref.s_m >= lo) & (ref.s_m <= hi)
        real = float(ref.speed_kmh[ref_sel].min()) if ref_sel.any() else float("nan")
        out[name] = (float(sim.v_ms[sim_sel].min() * 3.6), real)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Run both stages, report, and write the config when every check passes."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True)
    parser.add_argument("--grid", default="real_2026")
    parser.add_argument("--max-evals", type=int, default=400, help="per stage and team")
    parser.add_argument("--dry-run", action="store_true", help="never write the config")
    parser.add_argument(
        "--provisional",
        action="store_true",
        help="accept at calibration.speed_rmse_kmh_provisional and mark values PROVISIONAL",
    )
    parser.add_argument(
        "--notes",
        type=Path,
        default=Path("docs/results/CALIBRATION_NOTES.md"),
        help="bound-hit notes",
    )
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--workers", type=int, default=2, help="stage-2 worker processes")
    parser.add_argument("--checkpoint", type=Path, help="progress file (resumed if present)")
    parser.add_argument("--progress-log", type=Path, help="per-team progress log")
    parser.add_argument(
        "--write-from-report",
        type=Path,
        help="write the config from a saved fit report instead of fitting",
    )
    parser.add_argument("--task", default="T-026", help="task id in the CALIBRATED marker")
    parser.add_argument("--verdict", default="", help="acceptance note for the notes file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.progress_log is not None:
        args.progress_log.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(args.progress_log, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logging.getLogger().addHandler(handler)

    if args.write_from_report is not None:
        return _write_from_report(args)

    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
        model = read_track_model(Path(app.paths.tracks) / f"{track.track_id}.parquet")
        grid = load_grid(args.grid, args.config_dir)
        perf = load_team_performance(args.config_dir)
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

    rules = rule_set_for_date(next(iter(refs.values())).session_date, args.config_dir)
    esses = esses_real_minima(
        track, model.length_m, list(refs.values()), app.calibration.esses_corners
    )
    ctx = FitContext(track_arrays(model, track), track, rules, tyres, app, esses)
    order = sorted(refs, key=lambda t: refs[t].lap_time_s)
    base = perf.teams[order[0]]

    checkpoint_path = args.checkpoint or (
        Path(app.paths.calibration) / f"{track.track_id}_fit_checkpoint.json"
    )
    key = {"track": track.track_id, "rules": rules.rule_set_id, "grid": args.grid}
    progress = load_checkpoint(checkpoint_path, key)

    if progress["stage1"] is None:
        logger.info("stage 1: shared grip from the top %d teams %s", TOP_N, order[:TOP_N])
        s1 = stage1(ctx, base, [refs[t] for t in order[:TOP_N]], args.max_evals)
        progress["stage1"] = _fit_to_json(s1)
        save_checkpoint(checkpoint_path, progress)
    else:
        s1 = _fit_from_json(progress["stage1"])
        logger.info("stage 1: resumed from %s", checkpoint_path)
    grip = {k: s1.values[k] for k in GRIP}
    shared_aero = {k: s1.values[k] for k in AERO}
    logger.info(
        "stage 1 %s (objective %.3f, %d laps, on bound %s)",
        _fmt(s1.values), s1.objective, s1.evaluations, list(s1.on_bound) or "none",
    )  # fmt: skip

    fits: dict[str, FitResult] = {
        t: _fit_from_json(d) for t, d in progress["teams"].items() if t in order
    }
    for team_id in fits:
        logger.info("stage 2 %-13s resumed from checkpoint", team_id)
    jobs = [
        TeamJob(
            ctx,
            t,
            perf.teams[t],
            grip,
            {**shared_aero, "pu_power_scale": 1.0},
            refs[t],
            args.max_evals,
        )  # fmt: skip
        for t in order
        if t not in fits
    ]
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for done in as_completed([pool.submit(run_team_job, job) for job in jobs]):
            team_fit = done.result()
            fits[team_fit.team_id] = team_fit.fit
            progress["teams"][team_fit.team_id] = _fit_to_json(team_fit.fit)
            save_checkpoint(checkpoint_path, progress)
            target = refs[team_fit.team_id].lap_time_s
            logger.info(
                "stage 2 %-13s lap %.3f s (target %.3f, %+.2f %%), RMSE %.1f km/h, on bound %s,"
                " %s (%d laps)",
                team_fit.team_id, team_fit.lap_time_s, target,
                100.0 * (team_fit.lap_time_s - target) / target, team_fit.rmse_kmh,
                list(team_fit.fit.on_bound) or "none", _fmt(team_fit.fit.values),
                team_fit.fit.evaluations,
            )  # fmt: skip
    per_team = {t: fits[t].values for t in order}

    sims = {t: simulate(ctx, perf.teams[t], {**grip, **per_team[t]}) for t in order}
    rmse_limit = (
        app.calibration.speed_rmse_kmh_provisional
        if args.provisional
        else app.calibration.speed_rmse_kmh
    )
    results = compare_teams(sims, refs, app, rmse_limit)
    log_results(results, app, rmse_limit)
    report = _report(
        ctx, model, perf.teams, refs, order[0], grip, per_team, s1, fits, results, sims
    )
    report["provisional"] = args.provisional
    report["rmse_limit_kmh"] = rmse_limit
    report["verdict"] = verdict(results, report, app)
    logger.info("%s", json.dumps(report["extras"], indent=2, default=_json_default))

    out = Path(app.paths.calibration) / f"{track.track_id}_fit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=_json_default), encoding="utf-8")
    logger.info("fit report -> %s", out)

    logger.info("verdict: %s", report["verdict"])
    if report["verdict"] == "FAIL":
        logger.error("targets missed within bounds: config NOT written (stop and report)")
        return EXIT_TARGETS_MISSED
    if args.dry_run:
        logger.info("dry run: config not written")
        return EXIT_OK
    task = args.task
    if report["verdict"] == "ACCEPTED":
        limit = app.calibration.speed_rmse_kmh_provisional
        task = f"{task}, RMSE <= {limit:g} km/h accepted (owner round 15)"
    write_config(args.config_dir, track.track_id, grip, shared_aero, per_team,
                 list(perf.teams), app.calibration.bounds, args.provisional, task)  # fmt: skip
    args.notes.write_text(
        calibration_notes(report, app.calibration.bounds, rmse_limit), encoding="utf-8"
    )
    logger.info("config written: teams/performance.yaml, tyres.yaml; notes -> %s", args.notes)
    return EXIT_OK


def _write_from_report(args: argparse.Namespace) -> int:
    """Write config and notes from a saved fit report (no fitting)."""
    try:
        app = load_app(args.config_dir)
        perf = load_team_performance(args.config_dir)
    except ConfigError as exc:
        logger.error("%s", exc)
        return EXIT_INVALID
    report: dict[str, Any] = json.loads(args.write_from_report.read_text(encoding="utf-8"))
    grip = {k: float(report["stage1"][k]) for k in GRIP}
    shared_aero = {k: float(report["stage1"][k]) for k in AERO}
    per_team = {t: {k: float(v) for k, v in vals.items()} for t, vals in report["per_team"].items()}
    report["provisional"] = args.provisional
    write_config(args.config_dir, report["track_id"], grip, shared_aero, per_team,
                 list(perf.teams), app.calibration.bounds, args.provisional, args.task)  # fmt: skip
    limit = float(report.get("rmse_limit_kmh", app.calibration.speed_rmse_kmh))
    notes = calibration_notes(report, app.calibration.bounds, limit)
    if args.verdict:
        notes += f"\n### Verdict\n\n{args.verdict}\n"
    args.notes.write_text(notes, encoding="utf-8")
    logger.info("config written from %s (%s); notes -> %s", args.write_from_report, args.task,
                args.notes)  # fmt: skip
    return EXIT_OK


def bound_hits(
    values: dict[str, float], bounds: dict[str, tuple[float, float]]
) -> list[tuple[str, float, str]]:
    """``(name, value, 'upper' | 'lower')`` for each value on a bound."""
    hits = []
    for name in on_bounds(values, bounds):
        if name == DRAG_ORDER:
            hits.append((name, values["cda_straight"] - values["cda_corner"], "constraint"))
            continue
        lo, hi = bounds[name]
        side = "upper" if abs(values[name] - hi) <= abs(values[name] - lo) else "lower"
        hits.append((name, values[name], side))
    return hits


def calibration_notes(
    report: dict[str, Any], bounds: dict[str, tuple[float, float]], rmse_limit_kmh: float
) -> str:
    """Markdown notes for docs/results/CALIBRATION_NOTES.md: results and every bound hit."""
    status = "PROVISIONAL" if report.get("provisional") else "final"
    lines = [
        "# Calibration notes",
        "",
        "Generated by `python -m pitwall_sim.calibration.fit` (T-026). A coefficient on a",
        "bound means the model, not the number, is wrong (owner round 10): the fit pushed it",
        "as far as the physically plausible range allows. Bounds: `config/app.yaml`",
        "`calibration.bounds`. Why the fit hits them, and the follow-ups (T-028 super-clip,",
        "T-029 pooled-lap geometry, T-02A final calibration): `docs/spec/TRD.md` CALIBRATION.",
        "",
        f"## {report['track_id']} ({report['rule_set_id']}), {status}",
        "",
        "Acceptance: lap time within 2 % of each team's own target, team order within",
        f"±2 places, speed RMSE ≤ {rmse_limit_kmh:g} km/h.",
        "",
        "| team | target s | sim s | Δ % | RMSE km/h | real | sim |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['team_id']} | {r['target_s']:.3f} | {r['lap_time_s']:.3f} | "
            f"{r['delta_pct']:+.2f} | {r['speed_rmse_kmh']:.1f} | {r['real_position']} | "
            f"{r['sim_position']} |"
        )
    lines += ["", "### Bound hits", "", "| fit | coefficient | value | bound | pushed |",
              "| --- | --- | --- | --- | --- |"]  # fmt: skip
    groups = [("stage 1 (shared)", report["stage1"])] + list(report["per_team"].items())
    for name, values in groups:
        for coef, value, side in bound_hits(values, bounds):
            if coef == DRAG_ORDER:
                lines.append(
                    f"| {name} | `{coef}` | {value:+.4f} (straight - corner) | constraint | "
                    "Straight Mode drag pushed up to Corner Mode drag |"
                )
                continue
            lo, hi = bounds[coef]
            lines.append(
                f"| {name} | `{coef}` | {value:.4f} | {lo:g}-{hi:g} | toward the {side} bound |"
            )
    extras = report["extras"]
    if "verdict" in report:
        lines += ["", f"Verdict (owner round 15 acceptance): **{report['verdict']}**."]
    plaus = extras.get("plausibility", {})
    if "per_team_lateral_braking_g_esses_kmh" in plaus:
        lines += ["", "### Plausibility (every team's lap)", "",
                  "| team | peak lateral g | peak braking g | worst Esses excess km/h |",
                  "| --- | --- | --- | --- |"]  # fmt: skip
        for team, (lat, brake, esses) in plaus["per_team_lateral_braking_g_esses_kmh"].items():
            lines.append(f"| {team} | {lat:.2f} | {brake:.2f} | {esses:+.1f} |")
    if "corner_residuals_kmh" in extras:
        lines += ["", "### Per-corner residuals (sim - real minimum speed, km/h, over teams)", "",
                  "| corner | median | worst |", "| --- | --- | --- |"]  # fmt: skip
        for corner, (median, worst) in extras["corner_residuals_kmh"].items():
            lines.append(f"| {corner} | {median:+.1f} | {worst:+.1f} |")
    lines += [
        "",
        "### Pole team",
        "",
        f"- {extras['pole_team']}: greedy deploy {extras['pole_lap_greedy_s']} s, "
        f"policy deploy {extras['pole_lap_policy_s']} s.",
    ]
    for corner, (sim_v, real_v) in extras["pole_corner_min_kmh_sim_vs_real"].items():
        real_txt = (
            f"{real_v} km/h"
            if real_v == real_v  # not NaN
            else "no valid sample (frozen telemetry dropped)"
        )
        lines.append(f"- {corner}: minimum speed sim {sim_v} km/h, real {real_txt}.")
    return "\n".join(lines) + "\n"


def _json_default(value: object) -> object:
    """Make NumPy scalars JSON-serialisable."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _fmt(values: dict[str, float]) -> str:
    return " ".join(f"{k}={v:.4f}" for k, v in values.items())


def _report(
    ctx: FitContext,
    model: TrackModel,
    teams: dict[str, TeamPerformance],
    refs: dict[str, ReferenceLap],
    pole_team: str,
    grip: dict[str, float],
    per_team: dict[str, dict[str, float]],
    s1: FitResult,
    fits: dict[str, FitResult],
    results: list[TeamResult],
    sims: dict[str, LapResult],
) -> dict[str, object]:
    pole_values = {**grip, **per_team[pole_team]}
    team2, tyres2 = apply(teams[pole_team], ctx.tyres, pole_values)
    greedy = lap_of(
        simulate_quali_lap(ctx.arrays, ctx.track, ctx.rules, team2, tyres2, ctx.app, "greedy")
    )
    policy = simulate(ctx, teams[pole_team], pole_values)
    corners = corner_min_speeds(ctx.track, model, policy, refs[pole_team])
    lat_g, brake_g = peak_accelerations_g(policy, ctx.arrays.kappa)
    cal = ctx.app.calibration
    esses = esses_excess_kmh(ctx.track, model, policy, list(refs.values()), cal.esses_corners)
    worst_excess = max((a - b for a, b in esses.values() if b == b), default=0.0)
    team_plausibility = {t: plausibility(ctx, lap) for t, lap in sims.items()}
    plausible = all(
        lat <= cal.max_lateral_g and brake <= cal.max_braking_g
        and excess <= cal.esses_max_excess_kmh
        for lat, brake, excess in team_plausibility.values()
    )  # fmt: skip
    on_bound = {
        "stage 1": list(s1.on_bound),
        **{t: list(f.on_bound) for t, f in fits.items() if f.on_bound},
    }
    return {
        "track_id": ctx.track.track_id,
        "rule_set_id": ctx.rules.rule_set_id,
        "stage1": s1.values,
        "per_team": per_team,
        "results": [r.__dict__ for r in results],
        "extras": {
            "pole_team": pole_team,
            "pole_lap_greedy_s": round(greedy.lap_time_s, 3),
            "pole_lap_policy_s": round(policy.lap_time_s, 3),
            "pole_corner_min_kmh_sim_vs_real": {
                k: [round(a, 1), round(b, 1)] for k, (a, b) in corners.items()
            },
            "on_bound": on_bound,
            "plausibility": {
                "peak_lateral_g": round(lat_g, 2),
                "peak_braking_g": round(brake_g, 2),
                "esses_min_kmh_sim_vs_real": {
                    k: [round(a, 1), round(b, 1)] for k, (a, b) in esses.items()
                },
                "esses_worst_excess_kmh": round(worst_excess, 1),
                "per_team_lateral_braking_g_esses_kmh": {
                    t: [round(v, 2) for v in vals] for t, vals in team_plausibility.items()
                },
                "plausible": plausible,
            },
            "corner_residuals_kmh": corner_residuals(ctx.track, model, sims, refs),
            "pole_battery_mj_every_250m": [
                round(float(policy.battery_j[i]) / 1e6, 2) for i in range(0, policy.s_m.size, 250)
            ],
        },
    }


if __name__ == "__main__":
    sys.exit(main())
