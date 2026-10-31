"""FastF1-like feed files from a recorded race (sprint S-1, docs/planning/SPRINT.md Part 5).

Per car two raw streams, like FastF1's ``car_data`` and ``pos_data``, sampled
from the Ground Truth at their own rate (``export.stream_rate_hz``) with their
own timestamps and +- ``jitter_s`` jitter, single dropped frames (``drop_p``)
and occasional gaps (``gap_rate_per_min``, ``gap_s``):

- ``car_data``: Driver, SessionTime, Speed (km/h, noise), RPM (not simulated:
  NaN), nGear (speed bands), Throttle (0-100, integer), Brake (bool).
- ``pos_data``: Driver, SessionTime, X, Y, Z (FastF1 units: decimetres; noise),
  Status.

``cars.parquet`` merges the two per car the way FastF1's ``merge_channels``
does (union of timestamps; continuous channels interpolated linearly, gear and
brake held from the previous sample) and integrates speed into ``distance``
(FastF1 ``add_distance``): columns driver, time (s), distance (m), speed
(km/h), throttle, brake, gear, x, y (m). No DRS column (none in 2026).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from pitwall_sim.config.models import ExportConfig
from pitwall_sim.export.truth import TruthRun

KMH = 3.6
DM = 10.0
"""FastF1 position units per metre."""


def _times(rng: np.random.Generator, t0: float, t1: float, cfg: ExportConfig) -> npt.NDArray[Any]:
    """One stream's timestamps between ``t0`` and ``t1`` after jitter and dropouts."""
    lo, hi = cfg.stream_rate_hz
    period = 1.0 / rng.uniform(lo, hi)
    start = t0 + rng.uniform(0.0, period)
    t = np.arange(start, t1, period)
    t = t + rng.uniform(-cfg.jitter_s, cfg.jitter_s, t.size)
    keep = rng.random(t.size) >= cfg.drop_p
    n_gaps = rng.poisson(cfg.gap_rate_per_min * (t1 - t0) / 60.0)
    for g0, length in zip(
        rng.uniform(t0, t1, n_gaps), rng.uniform(*cfg.gap_s, n_gaps), strict=True
    ):
        keep &= (t < g0) | (t > g0 + length)
    return np.sort(t[keep & (t >= t0) & (t <= t1)])


def streams(
    run: TruthRun, cfg: ExportConfig, rng: np.random.Generator, gear_upshift_kmh: list[float]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (car_data, pos_data) for every car (all 22, Our Car included)."""
    e, d, t = run.engine, run.data, run.t_s
    model = e.model
    length = e.trk.length_m
    cars, pos = [], []
    for i, driver in enumerate(e.driver_ids):
        alive = np.flatnonzero(d["running"][:, i])
        if alive.size < 2:
            continue
        t0, t1 = float(t[alive[0]]), float(t[alive[-1]])
        dist = d["lap"][:, i].astype(np.float64) * length + d["s_m"][:, i]
        tc = _times(rng, t0, t1, cfg)
        speed = np.interp(tc, t, d["v_ms"][:, i]) * KMH
        speed = np.maximum(speed + rng.normal(0.0, cfg.speed_noise_kmh, tc.size), 0.0)
        throttle = np.clip(np.round(np.interp(tc, t, d["throttle"][:, i]) * 100.0), 0, 100)
        prev = np.clip(np.searchsorted(t, tc, side="right") - 1, 0, t.size - 1)
        brake = d["brake"][prev, i] > 0.0
        cars.append(pd.DataFrame({
            "Driver": driver, "SessionTime": pd.to_timedelta(tc, unit="s"),
            "Speed": speed.astype(np.float32), "RPM": np.float32("nan"),
            "nGear": np.searchsorted(np.asarray(gear_upshift_kmh), speed).astype(np.int8) + 1,
            "Throttle": throttle.astype(np.int16), "Brake": brake,
        }))  # fmt: skip
        tp = _times(rng, t0, t1, cfg)
        s = np.interp(tp, t, dist) % length
        x = np.interp(s, model.s_m, model.x_m) + rng.normal(0.0, cfg.position_noise_m, tp.size)
        y = np.interp(s, model.s_m, model.y_m) + rng.normal(0.0, cfg.position_noise_m, tp.size)
        pos.append(pd.DataFrame({
            "Driver": driver, "SessionTime": pd.to_timedelta(tp, unit="s"),
            "X": (x * DM).astype(np.float32), "Y": (y * DM).astype(np.float32),
            "Z": np.float32(0.0), "Status": "OnTrack",
        }))  # fmt: skip
    return pd.concat(cars, ignore_index=True), pd.concat(pos, ignore_index=True)


def merge(car_data: pd.DataFrame, pos_data: pd.DataFrame) -> pd.DataFrame:
    """Return ``cars.parquet``: car and position channels merged per car, FastF1-style."""
    out = []
    for driver, car in car_data.groupby("Driver", sort=False):
        posd = pos_data[pos_data["Driver"] == driver]
        tc = car["SessionTime"].dt.total_seconds().to_numpy()
        tp = posd["SessionTime"].dt.total_seconds().to_numpy()
        t = np.union1d(tc, tp)
        speed = np.interp(t, tc, car["Speed"].to_numpy(np.float64))
        prev = np.clip(np.searchsorted(tc, t, side="right") - 1, 0, tc.size - 1)
        distance = np.concatenate(([0.0], np.cumsum(0.5 * (speed[1:] + speed[:-1]) / KMH
                                                    * np.diff(t))))  # fmt: skip
        out.append(pd.DataFrame({
            "driver": driver, "time": t, "distance": distance, "speed": speed,
            "throttle": np.interp(t, tc, car["Throttle"].to_numpy(np.float64)),
            "brake": car["Brake"].to_numpy()[prev],
            "gear": car["nGear"].to_numpy()[prev],
            "x": np.interp(t, tp, posd["X"].to_numpy(np.float64)) / DM,
            "y": np.interp(t, tp, posd["Y"].to_numpy(np.float64)) / DM,
        }))  # fmt: skip
    return pd.concat(out, ignore_index=True)
