"""Baselines on an export's feed (sprint S-3): the built-in Radar and a dumb ATTACK rule.

Both read only ``feed/cars.parquet`` (what Simply Clipping reads) and the
track's public layout, so they are scored on the same input as Simply
Clipping. Lap distance comes from projecting ``x, y`` onto the track centre
line, choosing among the nearest points the one that follows on from the
previous sample (Suzuka crosses over itself).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.spatial import cKDTree

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, load_app, load_track
from pitwall_sim.observe.frames import PublicFeedFrame
from pitwall_sim.observe.radar.energy import RadarEstimator
from pitwall_sim.track.builder import TrackModel, read_track_model

KMH = 3.6
ESTIMATE_EVERY_S = 1.0
"""Baseline estimates are written once a second per car."""
DUMB_GAP_S = 1.0


def track_model(run: dict[str, Any], config_dir: Path = DEFAULT_CONFIG_DIR) -> TrackModel:
    """Return the run's track model (centre line)."""
    app = load_app(config_dir)
    tracks = Path(app.paths.tracks)
    if not tracks.is_absolute():
        tracks = config_dir.resolve().parent / tracks
    return read_track_model(tracks / f"{run['track']}.parquet")


def lap_distance(
    x: npt.NDArray[np.float64], y: npt.NDArray[np.float64], t: npt.NDArray[np.float64],
    speed_kmh: npt.NDArray[np.float64], model: TrackModel, tree: cKDTree | None = None,
) -> npt.NDArray[np.float64]:  # fmt: skip
    """Lap distance (m) of one car's samples, continuous across the crossover."""
    tree = tree or cKDTree(np.column_stack((model.x_m, model.y_m)))
    length = model.length_m
    _, idx = tree.query(np.column_stack((x, y)), k=8)
    cand = model.s_m[idx]
    out = np.empty(x.size)
    out[0] = cand[0, 0]
    for k in range(1, x.size):
        pred = out[k - 1] + speed_kmh[k] / KMH * (t[k] - t[k - 1])
        miss = np.abs((cand[k] - pred + length / 2) % length - length / 2)
        out[k] = cand[k, int(np.argmin(miss))]
    return out


def builtin_radar(run_dir: Path, config_dir: Path = DEFAULT_CONFIG_DIR) -> pd.DataFrame:
    """Run the sim's built-in Radar on the exported feed; return estimates (scorer contract)."""
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    app = load_app(config_dir)
    track = load_track(run["track"], config_dir)
    model = track_model(run, config_dir)
    tree = cKDTree(np.column_stack((model.x_m, model.y_m)))
    zones = [(z.s_start_m, z.s_end_m) for z in track.zones if "straight_mode_allowed" in z.tags]
    cars = pd.read_parquet(run_dir / "feed" / "cars.parquet")
    rows = []
    for driver, c in cars.groupby("driver", sort=False):
        t = c["time"].to_numpy()
        speed = c["speed"].to_numpy()
        s = lap_distance(c["x"].to_numpy(), c["y"].to_numpy(), t, speed, model, tree)
        radar = RadarEstimator(str(driver), app.radar, zones, model.length_m, app.feed.rate_hz)
        throttle, brake, gear = (
            c["throttle"].to_numpy(),
            c["brake"].to_numpy(),
            c["gear"].to_numpy(),
        )
        next_t = -math.inf
        for k in range(t.size):
            frame = PublicFeedFrame(
                float(t[k]), str(driver), float(speed[k]), float(throttle[k]), bool(brake[k]),
                int(gear[k]), 0.0, 0.0, float(s[k]),
            )  # fmt: skip
            est = radar.update([frame])
            if t[k] >= next_t:
                next_t = t[k] + ESTIMATE_EVERY_S
                anchor = radar.anchor_t_s
                rows.append((driver, t[k], est.energy_mj, est.state, est.confidence,
                             t[k] - anchor if radar.anchored else math.nan))  # fmt: skip
    return pd.DataFrame(rows, columns=["driver", "time_s", "energy_mj", "state", "confidence",
                                       "since_anchor_s"])  # fmt: skip


def dumb_alerts(run_dir: Path, pov: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> pd.DataFrame:
    """Return the dumb rule's alerts for ``pov``: car ahead slower on this straight -> ATTACK.

    On a straight with the car ahead within 1 s and slower: ATTACK.

    Once a second; the same rival is not repeated within a lap.
    """
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    track = load_track(run["track"], config_dir)
    model = track_model(run, config_dir)
    length = model.length_m
    tree = cKDTree(np.column_stack((model.x_m, model.y_m)))
    straights = [(z.s_start_m, (z.s_end_m - z.s_start_m) % length)
                 for z in track.zones if z.type == "straight"]  # fmt: skip
    cars = pd.read_parquet(run_dir / "feed" / "cars.parquet")
    grid = np.arange(0.0, float(cars["time"].max()), 1.0)
    race_d, speed = {}, {}
    for driver, c in cars.groupby("driver", sort=False):
        t = c["time"].to_numpy()
        s = lap_distance(c["x"].to_numpy(), c["y"].to_numpy(), t, c["speed"].to_numpy(), model,
                         tree)  # fmt: skip
        d = np.unwrap(s, period=length)  # race distance from the first sample's lap position
        alive = (grid >= t[0]) & (grid <= t[-1])
        race_d[driver] = np.where(alive, np.interp(grid, t, d), np.nan)
        speed[driver] = np.where(alive, np.interp(grid, t, c["speed"].to_numpy()), np.nan)
    if pov not in race_d:
        return pd.DataFrame(columns=["time_s", "lap", "type", "car_a", "car_b", "confidence"])
    others = [d for d in race_d if d != pov]
    rows: list[tuple[Any, ...]] = []
    last: dict[str, float] = {}
    for k, t in enumerate(grid):
        me = race_d[pov][k]
        if np.isnan(me) or not any((me % length - s0) % length <= n for s0, n in straights):
            continue
        ahead = [(race_d[o][k] - me, o) for o in others if race_d[o][k] - me > 0.0]
        if not ahead:
            continue
        gap_m, rival = min(ahead)
        v_ms = max(speed[pov][k] / KMH, 1.0)
        if gap_m / v_ms <= DUMB_GAP_S and speed[rival][k] < speed[pov][k]:
            if me - last.get(rival, -math.inf) >= length:
                last[rival] = me
                rows.append((t, int(me // length) + 1, "ATTACK", pov, rival, 1.0))
    return pd.DataFrame(rows, columns=["time_s", "lap", "type", "car_a", "car_b", "confidence"])
