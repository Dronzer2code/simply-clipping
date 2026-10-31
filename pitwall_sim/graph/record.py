"""One finished race, as the race graphs need it (Graphify track).

A :class:`RaceRecord` is built only after the chequered flag, from either

- a live session (:func:`from_session`): the pit wall's alerts, calls and decision
  costs, the Reveal recorder's samples (public order and intervals, Radar
  Estimates, and the truth it kept until the flag), the engine's passes, track
  events and lap times; or
- an export folder (:func:`from_export`, ``python -m pitwall_sim.export``): the
  point-of-view car's alerts (built-in, or an estimator's ``alerts.parquet``),
  Radar Estimates against ``truth/ground_truth.parquet``, passes from
  ``truth/events.parquet``; no calls (an export has no engineer).

Battles use the Reveal's rule for every pair of cars: two cars adjacent in the
public order with the interval between them within ``BATTLE_GAP_S``, sampled every
``SAMPLE_S``; samples at most ``MERGE_GAP_S`` apart belong to one battle. Laps are
Our Car's (the point-of-view car's) race laps at the time.

The record is plain data and saved as ``race_record.json`` (``save`` / ``load``),
so ``python -m pitwall_sim.graph.race --run`` can rebuild the graph from a saved
live session.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from pitwall_sim.live.reveal import BATTLE_GAP_S, SAMPLE_S

if TYPE_CHECKING:
    from pitwall_sim.live.session import LiveSession

Array = npt.NDArray[np.float64]
MERGE_GAP_S = 2.0
"""Samples at most this far apart belong to one battle (one missed sample)."""
AT_SPEED_KMH = 150.0
"""Closing speed: the car ahead at least this fast (on a straight, STRUCTURAL)."""
BRAKING_DROP_KMH = 40.0
"""Closing speed: the car ahead lost more than this in one sample = braking (STRUCTURAL)."""
CALL_SOURCES = ("TEXT", "VOICE", "LLM")
"""Radio sources that mean the engineer spoke the call (not a button)."""
FALLBACK_COLOUR = "#8C8C8C"


class RaceNotFinishedError(RuntimeError):
    """A race graph was asked for before the chequered flag (truth is not allowed yet)."""


@dataclass
class CarInfo:
    """One car of the grid."""

    driver_id: str
    code: str
    team: str
    color: str
    finish_position: int | None = None
    status: str = "FINISHED"


@dataclass
class Battle:
    """A continuous period two cars ran adjacent within ``BATTLE_GAP_S``."""

    ahead: str
    """The car ahead when the battle started."""
    behind: str
    start_t_s: float
    end_t_s: float
    start_lap: int
    end_lap: int
    duration_s: float
    """Samples in the battle x ``SAMPLE_S`` (the Reveal counts the same way)."""

    @property
    def cars(self) -> tuple[str, str]:
        """Both cars, sorted."""
        a, b = sorted((self.ahead, self.behind))
        return a, b


@dataclass
class Pass:
    """One completed pass (blue-flag passes left out)."""

    t_s: float
    lap: int
    passer: str
    passed: str


@dataclass
class Incident:
    """A Safety Car / VSC, a pass involving Our Car, or a closing-speed event."""

    kind: str
    """``SC``, ``VSC``, ``PASS`` or ``CLOSING_SPEED``."""
    t_s: float
    lap: int
    end_t_s: float
    cars: list[str]
    detail: str
    value: float | None = None
    """Closing speed: the largest speed difference (km/h)."""


@dataclass
class TruthCheck:
    """An alert checked against the truth after the flag."""

    rival_true_mj: float | None
    our_mj: float | None
    estimate_mj: float | None
    """The Rival's battery the alert was based on (its evidence, else the radar)."""
    right: bool | None
    """ATTACK / DEFEND: was the energy difference real (Test mode's rule)? Others: None."""

    @property
    def error_mj(self) -> float | None:
        """Estimate minus truth."""
        if self.estimate_mj is None or self.rival_true_mj is None:
            return None
        return self.estimate_mj - self.rival_true_mj


@dataclass
class AlertItem:
    """One alert, what the engineer did and what followed."""

    alert_id: str
    t_s: float
    lap: int
    type: str
    rival: str
    branch: str | None
    confidence: float
    our_mj: float | None
    rival_est_mj: float | None
    dv_kmh: float | None
    gap_s: float | None
    option: str
    """The call made, ``ignored``, ``expired``, ``pending`` or ``none (export)``."""
    outcome: str | None
    truth: TruthCheck


@dataclass
class CostItem:
    """A call's decision cost (paired forks, H1)."""

    delta_s: float
    best_option: str
    your_s: float
    best_s: float
    n_seeds: int


@dataclass
class CallItem:
    """One engineer call."""

    index: int
    t_s: float
    lap: int
    alert_id: str | None
    label: str
    kind: str
    """``alert option``, ``radio`` or ``button``."""
    radio_text: str | None
    rival: str | None
    outcome: str | None
    position_before: int
    position_after: int | None
    estimate_mj: float | None
    truth_mj: float | None
    cost: CostItem | None = None


@dataclass
class RivalRadar:
    """Radar Estimate against the truth for one Rival (samples with confidence > 0)."""

    mae_mj: float | None
    bias_mj: float | None
    """Mean of estimate minus truth."""
    n: int


@dataclass
class RaceRecord:
    """Everything one finished race left behind for its graph."""

    run_id: str
    source: str
    """``live`` or ``export``."""
    track_id: str
    seed: int
    laps: int
    rule_set_id: str
    our: str
    cars: dict[str, CarInfo]
    battles: list[Battle] = field(default_factory=list)
    passes: list[Pass] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    alerts: list[AlertItem] = field(default_factory=list)
    calls: list[CallItem] = field(default_factory=list)
    radar: dict[str, RivalRadar] = field(default_factory=dict)
    radar_mae_mj: float | None = None
    lap_times_s: dict[str, list[float]] = field(default_factory=dict)
    max_closing_kmh: dict[str, float] = field(default_factory=dict)
    """Rival -> largest speed difference to Our Car while battling it (km/h)."""
    energy_margin_mj: float = 0.0
    test_mode: bool = False

    # ------------------------------------------------------------------ #
    def save(self, path: Path) -> None:
        """Write the record as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, default=_json_default),
                        encoding="utf-8")  # fmt: skip

    @classmethod
    def load(cls, path: Path) -> RaceRecord:
        """Read a record written by :meth:`save`."""
        d = json.loads(path.read_text(encoding="utf-8"))
        alerts = []
        for a in d.pop("alerts"):
            a["truth"] = TruthCheck(**a["truth"])
            alerts.append(AlertItem(**a))
        calls = []
        for c in d.pop("calls"):
            c["cost"] = CostItem(**c["cost"]) if c["cost"] else None
            calls.append(CallItem(**c))
        return cls(
            cars={k: CarInfo(**v) for k, v in d.pop("cars").items()},
            battles=[Battle(**b) for b in d.pop("battles")],
            passes=[Pass(**p) for p in d.pop("passes")],
            incidents=[Incident(**i) for i in d.pop("incidents")],
            radar={k: RivalRadar(**v) for k, v in d.pop("radar").items()},
            alerts=alerts, calls=calls, **d,
        )  # fmt: skip


def _json_default(x: object) -> object:
    if isinstance(x, np.generic):
        return x.item()
    raise TypeError(f"not JSON serialisable: {type(x).__name__}")


def _num(x: float | None) -> float | None:
    """Return a finite float, or None (JSON has no NaN)."""
    return None if x is None or not math.isfinite(float(x)) else float(x)


# ---------------------------------------------------------------------- #
# Shared rules
# ---------------------------------------------------------------------- #


def judge(alert_type: str, branch: str | None, true_diff_mj: float | None,
          margin_mj: float) -> bool | None:  # fmt: skip
    """Was an ATTACK / DEFEND alert right? (the call summary's Test-mode rule).

    ``true_diff_mj``: the Rival's TRUE battery minus ours when the alert fired. The
    energy branch claims a difference of at least the margin; the observed-clip /
    own-battery branches claim only its sign. Other alert types: None (not judged).
    """
    if true_diff_mj is None or alert_type not in ("ATTACK", "DEFEND"):
        return None
    margin = margin_mj if "energy" in (branch or "energy") else 0.0
    if alert_type == "ATTACK":
        return true_diff_mj <= -margin
    return true_diff_mj >= margin


def find_battles(t_s: Array, lap: Array, order: list[list[str]],
                 interval_s: list[dict[str, float]]) -> list[Battle]:  # fmt: skip
    """Every battle between any two cars (adjacent in the order, within ``BATTLE_GAP_S``)."""
    runs: dict[tuple[str, str], list[tuple[float, float, str, str]]] = {}
    for k in range(t_s.size):
        cars = order[k]
        for j in range(1, len(cars)):
            gap = interval_s[k].get(cars[j]) or 99.0  # 0.0: no timing yet (as the Reveal)
            if not math.isfinite(gap) or gap > BATTLE_GAP_S:
                continue
            key = tuple(sorted((cars[j - 1], cars[j])))
            runs.setdefault(key, []).append(  # type: ignore[arg-type]
                (float(t_s[k]), float(lap[k]), cars[j - 1], cars[j])
            )
    battles = []
    for samples in runs.values():
        start = 0
        for k in range(1, len(samples) + 1):
            if k == len(samples) or samples[k][0] - samples[k - 1][0] > MERGE_GAP_S:
                first, last = samples[start], samples[k - 1]
                battles.append(Battle(
                    first[2], first[3], first[0], last[0], int(first[1]), int(last[1]),
                    (k - start) * SAMPLE_S,
                ))  # fmt: skip
                start = k
    battles.sort(key=lambda b: (b.start_t_s, b.cars))
    return battles


def closing_events(t_s: Array, lap: Array, our: str, order: list[list[str]],
                   interval_s: list[dict[str, float]], speed_kmh: dict[str, Array],
                   threshold_kmh: float) -> tuple[list[Incident], dict[str, float]]:  # fmt: skip
    """Closing-speed incidents of Our Car: the car behind faster by ``threshold_kmh``.

    Within ``BATTLE_GAP_S`` of each other, with the car ahead at speed (at least
    ``AT_SPEED_KMH``, not braking: it lost at most ``BRAKING_DROP_KMH`` since the
    sample before), as the export's closing-speed episodes (a car ahead clipping or
    lifting on a straight; the samples carry no energy states). Also returns, per
    Rival, the largest closing speed seen between it and Our Car (km/h).
    """
    v_our = speed_kmh.get(our)
    if v_our is None:
        return [], {}
    hits: dict[str, list[tuple[float, float, float]]] = {}
    max_dv: dict[str, float] = {}
    for k in range(t_s.size):
        cars = order[k]
        if our not in cars:
            continue
        j = cars.index(our)
        near = []  # (rival, the car ahead, the car behind)
        if j > 0 and (interval_s[k].get(our) or 99.0) <= BATTLE_GAP_S:
            near.append((cars[j - 1], cars[j - 1], our))
        if j + 1 < len(cars) and (interval_s[k].get(cars[j + 1]) or 99.0) <= BATTLE_GAP_S:
            near.append((cars[j + 1], our, cars[j + 1]))
        for rival, ahead, behind in near:
            va, vb = speed_kmh.get(ahead), speed_kmh.get(behind)
            if va is None or vb is None or not (math.isfinite(va[k]) and math.isfinite(vb[k])):
                continue
            braking = k > 0 and math.isfinite(va[k - 1]) and va[k - 1] - va[k] > BRAKING_DROP_KMH
            if va[k] < AT_SPEED_KMH or braking:
                continue
            dv = float(vb[k]) - float(va[k])
            if dv > 0.0:
                max_dv[rival] = max(max_dv.get(rival, 0.0), dv)
            if dv >= threshold_kmh:
                hits.setdefault(rival, []).append((float(t_s[k]), float(lap[k]), dv))
    incidents = []
    for rival, samples in hits.items():
        start = 0
        for k in range(1, len(samples) + 1):
            if k == len(samples) or samples[k][0] - samples[k - 1][0] > MERGE_GAP_S:
                run = samples[start:k]
                peak = max(s[2] for s in run)
                incidents.append(Incident(
                    "CLOSING_SPEED", run[0][0], int(run[0][1]), run[-1][0], [our, rival],
                    f"closing speed {peak:.0f} km/h, {our} / {rival}", peak,
                ))  # fmt: skip
                start = k
    incidents.sort(key=lambda i: i.t_s)
    return incidents, max_dv


def _radar_stats(rivals: tuple[str, ...], est: Array, conf: Array,
                 truth: Array) -> tuple[dict[str, RivalRadar], float | None]:  # fmt: skip
    out = {}
    for k, d in enumerate(rivals):
        known = conf[:, k] > 0.0 if conf.size else np.zeros(0, dtype=bool)
        err = (est[known, k] - truth[known, k]) if known.any() else np.zeros(0)
        out[d] = RivalRadar(_num(np.abs(err).mean()) if err.size else None,
                            _num(err.mean()) if err.size else None, int(err.size))  # fmt: skip
    known = conf > 0.0
    mae = _num(np.abs(est - truth)[known].mean()) if known.any() else None
    return out, mae


def _lap_at(t: float, t_s: Array, lap: Array) -> int:
    if t_s.size == 0:
        return 1
    return max(1, int(np.interp(t, t_s, lap)))


# ---------------------------------------------------------------------- #
# From a live session
# ---------------------------------------------------------------------- #


def run_id_for(track_id: str, seed: int, our: str, laps: int, source: str = "live") -> str:
    """Return the race graph's folder name, e.g. ``live_suzuka_s2_GAS_15l``."""
    return f"{source}_{track_id}_s{seed}_{our}_{laps}l"


def from_session(session: LiveSession) -> RaceRecord:
    """Build the record of a finished live race (raises before the flag)."""
    samples = session.reveal_samples()
    reveal = session.reveal()
    if samples is None or reveal is None:
        raise RaceNotFinishedError("race graphs are built after the chequered flag")
    eng = session.engine
    our = session.setup.our_driver_id
    result = eng.result()
    classification = {d: k + 1 for k, d in enumerate(result.classification)}
    cars = {
        d: CarInfo(d, info["code"], info["team"], info["color"], classification.get(d),
                   str(eng.status[i]))
        for i, (d, info) in enumerate((d, session.drivers[d]) for d in eng.driver_ids)
    }  # fmt: skip
    t, lap = samples.t_s, samples.lap
    end_t = float(t[-1]) + SAMPLE_S if t.size else eng.t
    battles = find_battles(t, lap, samples.order, samples.interval_s)
    passes = [
        Pass(e.t_s, _lap_at(e.t_s, t, lap), eng.driver_ids[e.attacker], eng.driver_ids[e.defender])
        for e in eng.overtake.events
        if e.success and not e.blue_flag and e.t_s <= end_t
    ]
    incidents = _track_incidents(eng.track_events, t, lap)
    incidents += [Incident("PASS", p.t_s, p.lap, p.t_s, [p.passer, p.passed],
                           f"{p.passer} passed {p.passed}") for p in passes
                  if our in (p.passer, p.passed)]  # fmt: skip
    closing, max_dv = closing_events(t, lap, our, samples.order, samples.interval_s,
                                     samples.speed_kmh, eng.app.alerts.closing_dv_kmh)  # fmt: skip
    incidents = sorted(incidents + closing, key=lambda i: i.t_s)
    margin = float(eng.app.alerts.energy_margin_mj)
    alerts = []
    for r in session.summary().records:
        a = r.alert
        rival_true, our_mj = samples.alert_truth.get(a.alert_id, (None, None))
        est = a.evidence.rival_mj
        if est is None and a.rival in samples.rivals and t.size:
            k = min(int(np.searchsorted(t, r.t_s)), t.size - 1)
            est = float(samples.estimate_mj[k, samples.rivals.index(a.rival)])
        diff = None if rival_true is None or our_mj is None else rival_true - our_mj
        alerts.append(AlertItem(
            a.alert_id, r.t_s, a.lap, a.type, a.rival, a.evidence.branch, a.confidence,
            a.evidence.our_mj, a.evidence.rival_mj, a.evidence.dv_kmh, a.evidence.gap_s,
            r.option, r.outcome,
            TruthCheck(rival_true, our_mj, _num(est),
                       judge(a.type, a.evidence.branch, diff, margin)),
        ))  # fmt: skip
    outcome_of = {a.alert_id: a.outcome for a in alerts}
    radio = session.frame().view.radio_log
    calls = []
    for index, (record, context) in enumerate(zip(session.call_log, reveal.calls, strict=True)):
        spoken = next((e for e in radio if e.sender == "ENGINEER" and e.source in CALL_SOURCES
                       and (set(e.command_ids) & set(record.command_ids)
                            or abs(e.t_s - record.t_s) < 1e-6)), None)  # fmt: skip
        radio_call = spoken is not None or record.option_label.startswith("radio:")
        kind = "alert option" if record.alert_id else ("radio" if radio_call else "button")
        if record.alert_id:
            outcome = outcome_of.get(record.alert_id)
        else:
            outcome = _position_change(context.position_before, context.position_after)
        cost = session.costs.get(index)
        calls.append(CallItem(
            index, record.t_s, record.lap, record.alert_id, record.option_label, kind,
            spoken.text if spoken else None, context.rival, outcome, context.position_before,
            context.position_after, _num(context.estimate_mj), _num(context.truth_mj),
            CostItem(cost.delta_s, cost.best_option_label, cost.your_outcome_s,
                     cost.best_outcome_s, cost.n_seeds) if cost else None,
        ))  # fmt: skip
    radar, _ = _radar_stats(samples.rivals, samples.estimate_mj, samples.confidence,
                              samples.truth_mj)  # fmt: skip
    s = session.setup
    return RaceRecord(
        run_id=run_id_for(s.track_id, s.seed, our, eng.laps), source="live",
        track_id=s.track_id, seed=s.seed, laps=eng.laps, rule_set_id=s.rule_set_id, our=our,
        cars=cars, battles=battles, passes=passes, incidents=incidents, alerts=alerts,
        calls=calls, radar=radar, radar_mae_mj=_num(reveal.radar_mae_mj),
        lap_times_s={d: list(v) for d, v in result.lap_times_s.items()},
        max_closing_kmh=max_dv, energy_margin_mj=margin, test_mode=s.test_mode,
    )  # fmt: skip


def _position_change(before: int, after: int | None) -> str | None:
    if after is None:
        return None
    if after < before:
        return "position gained"
    return "position kept" if after == before else "position lost"


def _track_incidents(events: list[tuple[float, str, str]], t_s: Array,
                     lap: Array) -> list[Incident]:  # fmt: skip
    """Safety Car / VSC periods from the engine's track events."""
    out: list[Incident] = []
    for k, (t, kind, reason) in enumerate(events):
        if kind not in ("SC", "VSC"):
            continue
        end = next((e[0] for e in events[k + 1 :] if e[1] == "GREEN"), t)
        name = "Safety Car" if kind == "SC" else "VSC"
        out.append(Incident(kind, t, _lap_at(t, t_s, lap), end, [], f"{name}: {reason}"))
    return out


# ---------------------------------------------------------------------- #
# From an export folder
# ---------------------------------------------------------------------- #


def from_export(folder: Path, config_dir: Path | None = None, alerts_file: Path | None = None,
                estimates_file: Path | None = None) -> RaceRecord:  # fmt: skip
    """Build the record of an exported race (point-of-view car = Our Car).

    ``alerts_file`` / ``estimates_file``: an estimator's outputs (e.g. Simply
    Clipping's ``alerts.parquet`` / ``estimates.parquet``); default the export's
    built-in baseline.
    """
    import pandas as pd

    from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, load_app, load_grid

    config_dir = config_dir or DEFAULT_CONFIG_DIR
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    if not run.get("finished", True):
        raise RaceNotFinishedError(f"{folder} is not a finished race")
    our = str(run["alert_pov"])
    length = float(run["lap_length_m"])
    app = load_app(config_dir)
    grid = load_grid("real_2026", config_dir)
    gt = pd.read_parquet(folder / "truth" / "ground_truth.parquet",
                         columns=["driver", "time_s", "distance_m", "speed_kmh", "battery_mj",
                                  "in_pit"])  # fmt: skip
    drivers = sorted(gt["driver"].unique())
    team = {d.driver_id: t for t in grid.teams for d in t.drivers}
    tick = np.round(gt["time_s"].to_numpy() * 10).astype(np.int64)
    sec = gt[tick % int(round(10 * SAMPLE_S)) == 0]
    dist = sec.pivot_table(index="time_s", columns="driver", values="distance_m")
    speed = sec.pivot_table(index="time_s", columns="driver", values="speed_kmh")
    t = dist.index.to_numpy(dtype=float)
    lap = (dist[our].to_numpy(dtype=float) / length + 1.0) if our in dist else np.ones(t.size)
    lap = np.nan_to_num(np.maximum.accumulate(np.nan_to_num(lap, nan=1.0)), nan=1.0)
    order: list[list[str]] = []
    intervals: list[dict[str, float]] = []
    d_arr, v_arr = dist.to_numpy(dtype=float), speed.to_numpy(dtype=float)
    cols = list(dist.columns)
    for k in range(t.size):
        on = [(d_arr[k, j], cols[j], v_arr[k, j]) for j in range(len(cols))
              if math.isfinite(d_arr[k, j])]  # fmt: skip
        on.sort(key=lambda x: -x[0])
        order.append([c for _, c, _ in on])
        gaps = {}
        for j in range(1, len(on)):
            v_ms = max(on[j][2] / 3.6, 10.0) if math.isfinite(on[j][2]) else 10.0
            gaps[on[j][1]] = (on[j - 1][0] - on[j][0]) / v_ms
        intervals.append(gaps)
    battles = find_battles(t, lap, order, intervals)
    events = pd.read_parquet(folder / "truth" / "events.parquet")
    ov = events[(events["type"] == "overtake") & ~events["blue_flag"].astype(bool)]
    passes = [Pass(float(r.t_start_s), _lap_at(float(r.t_start_s), t, lap), str(r.car_a),
                   str(r.car_b)) for r in ov.itertuples()]  # fmt: skip
    speeds = {c: v_arr[:, j] for j, c in enumerate(cols)}
    closing, max_dv = closing_events(t, lap, our, order, intervals, speeds,
                                     app.alerts.closing_dv_kmh)  # fmt: skip
    incidents = [Incident("PASS", p.t_s, p.lap, p.t_s, [p.passer, p.passed],
                          f"{p.passer} passed {p.passed}") for p in passes
                 if our in (p.passer, p.passed)]  # fmt: skip
    incidents = sorted(incidents + closing, key=lambda i: i.t_s)
    battery = {d: g.sort_values("time_s") for d, g in gt[["driver", "time_s", "battery_mj"]]
               .groupby("driver")}  # fmt: skip

    def true_mj(d: str, at: float) -> float | None:
        g = battery.get(d)
        if g is None or g.empty:
            return None
        k = min(int(np.searchsorted(g["time_s"].to_numpy(), at)), len(g) - 1)
        return float(g["battery_mj"].iloc[k])

    est_path = estimates_file or folder / "baseline" / "builtin_estimates.parquet"
    est = pd.read_parquet(est_path) if est_path.exists() else pd.DataFrame(
        columns=["driver", "time_s", "energy_mj", "confidence"])  # fmt: skip
    est_by = {d: g.sort_values("time_s") for d, g in est.groupby("driver")}

    def est_mj(d: str, at: float) -> float | None:
        g = est_by.get(d)
        if g is None or g.empty:
            return None
        k = int(np.searchsorted(g["time_s"].to_numpy(), at, side="right")) - 1
        return float(g["energy_mj"].iloc[k]) if k >= 0 else None

    rivals = tuple(d for d in drivers if d != our)
    radar = {}
    all_err = []
    for d in rivals:
        g = est_by.get(d)
        if g is None:
            radar[d] = RivalRadar(None, None, 0)
            continue
        g = g[g["confidence"] > 0.0]
        tr = battery.get(d)
        if g.empty or tr is None:
            radar[d] = RivalRadar(None, None, 0)
            continue
        k = np.clip(np.searchsorted(tr["time_s"].to_numpy(), g["time_s"].to_numpy()), 0,
                    len(tr) - 1)  # fmt: skip
        err = g["energy_mj"].to_numpy(dtype=float) - tr["battery_mj"].to_numpy(dtype=float)[k]
        all_err.append(err)
        radar[d] = RivalRadar(_num(np.abs(err).mean()), _num(err.mean()), int(err.size))
    errs = np.concatenate(all_err) if all_err else np.zeros(0)
    mae = _num(np.abs(errs).mean()) if errs.size else None
    al_path = alerts_file or folder / "baseline" / "builtin_alerts.parquet"
    al = pd.read_parquet(al_path) if al_path.exists() else pd.DataFrame()
    margin = float(app.alerts.energy_margin_mj)

    def ahead_of(a: str, b: str, at: float) -> bool | None:
        k = min(int(np.searchsorted(t, at)), t.size - 1)
        cars = order[k]
        if a not in cars or b not in cars:
            return None
        return cars.index(a) < cars.index(b)

    alerts = []
    for n, r in enumerate(al.itertuples() if not al.empty else []):
        at, rival = float(r.time_s), str(r.car_b)
        branch = str(r.branch) if "branch" in al.columns and r.branch is not None else None
        rival_true, our_mj = true_mj(rival, at), true_mj(our, at)
        diff = None if rival_true is None or our_mj is None else rival_true - our_mj
        our_lap = _lap_at(at, t, lap)
        later = float(np.interp(our_lap + 2, lap, t)) if lap[-1] >= our_lap + 2 else float(t[-1])
        before, after = ahead_of(our, rival, at), ahead_of(our, rival, later)
        outcome = None
        if before is not None and after is not None:
            if not before:
                outcome = "pass made" if after else "no pass"
            elif after:
                outcome = "position kept"
            else:
                outcome = "re-passed" if r.type == "REPASS_RISK" else "position lost"
        estimate = est_mj(rival, at)
        alerts.append(AlertItem(
            f"{r.type}-{rival}-{n}", at, int(r.lap), str(r.type), rival, branch,
            float(r.confidence), our_mj, estimate, None, None, "none (export)", outcome,
            TruthCheck(rival_true, our_mj, estimate, judge(str(r.type), branch, diff, margin)),
        ))  # fmt: skip
    laps_df = pd.read_parquet(folder / "feed" / "laps.parquet")
    lap_times = {
        str(d): [float(x.total_seconds()) for x in g.sort_values("LapNumber")["LapTime"]
                 if pd.notna(x)]
        for d, g in laps_df.groupby("Driver")
    }  # fmt: skip
    final = order[-1] if order else []
    cars = {}
    for d in drivers:
        tm = team.get(d)
        colour = str(tm.color_hex) if tm is not None else FALLBACK_COLOUR
        cars[d] = CarInfo(d, d, tm.display_name if tm else "", colour if colour.startswith("#")
                          else FALLBACK_COLOUR,
                          final.index(d) + 1 if d in final else None)  # fmt: skip
    seed = int(run["seed"])
    laps = int(run["laps"])
    return RaceRecord(
        run_id=f"export_{folder.name}", source="export", track_id=str(run["track"]), seed=seed,
        laps=laps, rule_set_id=str(run["rule_set"]), our=our, cars=cars, battles=battles,
        passes=passes, incidents=incidents, alerts=alerts, calls=[], radar=radar,
        radar_mae_mj=mae, lap_times_s=lap_times, max_closing_kmh=max_dv,
        energy_margin_mj=margin,
    )  # fmt: skip


def as_dict(record: RaceRecord) -> dict[str, Any]:
    """Return the record as plain JSON-ready data."""
    data: dict[str, Any] = json.loads(json.dumps(asdict(record), default=_json_default))
    return data
