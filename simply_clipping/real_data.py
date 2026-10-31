"""A real race from OpenF1, in the bridge's input format, through Simply Clipping (SC-5).

    python -m simply_clipping.real_data --session 11253 --our NOR --out data/sc_real/jpn2026_nor

OpenF1 (https://api.openf1.org, free, no login) gives per car ``car_data`` (speed,
throttle, brake, gear, ~3.7 Hz), ``location`` (x, y, z) and ``laps`` (lap start
times). Responses are cached in ``data/openf1_cache/`` (``sc_<hash>.json``), so a
second run is offline. The conversion writes ``feed/cars.parquet`` (driver,
time, distance, speed, throttle, brake, gear, x, y; time from the race start,
distance integrated from speed, position interpolated to the car_data times)
and ``feed/laps.parquet`` (Driver, LapNumber, LapStartTime, Team), then runs the
same pipeline as the bench.

A real race has no team data for "us": our battery is Simply Clipping's own
estimate of our car (from its public feed), not an exact value.
Own minimal code: the simulator is not imported (SC-R01).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from simply_clipping.alerts import OwnTrack, alerts_frame, offline_alerts
from simply_clipping.energy import Estimates, estimates_frame
from simply_clipping.loader import Config, Track, const, load_config, load_feed, load_layout

logger = logging.getLogger(__name__)
API = "https://api.openf1.org/v1/"
KMH = 3.6


def cache_path(endpoint: str, params: dict[str, Any], cache: Path) -> Path:
    """Where the response to ``endpoint`` with ``params`` is cached."""
    query = urllib.parse.urlencode(params)
    key = hashlib.sha1(f"{endpoint}?{query}".encode()).hexdigest()[:16]
    return cache / f"sc_{endpoint}_{key}.json"


def fetch(endpoint: str, params: dict[str, Any], cache: Path) -> list[dict[str, Any]]:
    """GET ``endpoint`` with ``params`` (cached on disk)."""
    query = urllib.parse.urlencode(params)
    path = cache_path(endpoint, params, cache)
    if path.exists():
        data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return data
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{API}{endpoint}?{query}", timeout=120) as resp:
                data = json.load(resp)
            break
        except OSError as err:  # rate limit or a dropped connection: back off and retry
            logger.warning("OpenF1 %s %s: %s", endpoint, params, err)
            time.sleep(5.0 * (attempt + 1))
    else:
        raise RuntimeError(f"OpenF1 {endpoint} {params}: no answer")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _seconds(dates: pd.Series, t0: pd.Timestamp) -> np.ndarray:
    return np.asarray((pd.to_datetime(dates, utc=True, format="ISO8601") - t0).dt.total_seconds())


def convert(session: int, cache: Path, feed_dir: Path) -> pd.Timestamp:
    """Write ``feed/cars.parquet`` and ``feed/laps.parquet`` for an OpenF1 race; return t0."""
    drivers = fetch("drivers", {"session_key": session}, cache)
    laps = pd.DataFrame(fetch("laps", {"session_key": session}, cache))
    first = laps[laps["lap_number"] == 1]["date_start"].dropna()
    t0 = pd.to_datetime(first, utc=True, format="ISO8601").min()  # lights out
    code = {d["driver_number"]: d["name_acronym"] for d in drivers}
    team = {d["driver_number"]: str(d.get("team_name") or "") for d in drivers}
    cars, lap_rows = [], []
    for number, acronym in sorted(code.items()):
        car = pd.DataFrame(
            fetch("car_data", {"session_key": session, "driver_number": number}, cache)
        )
        loc = pd.DataFrame(
            fetch("location", {"session_key": session, "driver_number": number}, cache)
        )
        if car.empty:
            continue
        t = _seconds(car["date"], t0)
        keep = t >= -60.0
        car, t = car[keep], t[keep]
        order = np.argsort(t, kind="stable")
        car, t = car.iloc[order], t[order]
        speed = car["speed"].to_numpy(dtype=np.float64)
        dt = np.diff(t, prepend=t[0])
        dist = np.cumsum(np.where(dt < 2.0, speed / KMH * dt, 0.0))
        xy = np.zeros((t.size, 2))
        if not loc.empty:
            tl = _seconds(loc["date"], t0)
            o = np.argsort(tl)
            xy[:, 0] = np.interp(t, tl[o], loc["x"].to_numpy(dtype=np.float64)[o]) / 10.0
            xy[:, 1] = np.interp(t, tl[o], loc["y"].to_numpy(dtype=np.float64)[o]) / 10.0
        cars.append(
            pd.DataFrame(
                {
                    "driver": acronym,
                    "time": t,
                    "distance": dist,
                    "speed": speed,
                    "throttle": car["throttle"].to_numpy(dtype=np.float64).clip(0, 100),
                    "brake": car["brake"].to_numpy(dtype=np.float64) > 0,
                    "gear": car["n_gear"].astype(int),
                    "x": xy[:, 0],
                    "y": xy[:, 1],
                }
            )
        )
        mine = laps[laps["driver_number"] == number].dropna(subset=["date_start"])
        for row in mine.itertuples():
            start = pd.to_datetime(row.date_start, utc=True, format="ISO8601") - t0
            lap_rows.append(
                {
                    "Driver": acronym,
                    "LapNumber": float(row.lap_number),
                    "LapStartTime": start,
                    "Team": team[number],
                }
            )
    feed_dir.mkdir(parents=True, exist_ok=True)
    pd.concat(cars, ignore_index=True).to_parquet(feed_dir / "cars.parquet", index=False)
    pd.DataFrame(lap_rows).to_parquet(feed_dir / "laps.parquet", index=False)
    pd.DataFrame({"Driver": pd.Series(dtype=str)}).to_parquet(feed_dir / "gaps.parquet")
    return t0


def own_from_estimates(est: Estimates, track: Track, cfg: Config) -> OwnTrack:
    """Our Car from its own public-feed estimate (a real race has no team data)."""
    own = OwnTrack(cfg, track.length_m)
    lap = np.floor(est.progress_m / track.length_m) + 1
    s = est.progress_m - (lap - 1) * track.length_m
    for i in range(len(est)):
        own.add(
            float(est.t_s[i]),
            int(lap[i]),
            float(s[i]),
            float(est.v_ms[i]),
            float(est.energy_mj[i]),
            float(est.throttle_pct[i]),
            bool(est.brake[i]),
        )
    return own


def run_real(feed_dir: Path, out_dir: Path, our: str, layout_file: Path) -> pd.DataFrame:
    """Simply Clipping on a converted real race; our battery = our own estimate."""
    from simply_clipping import history, track_race

    cfg = load_config()
    track = Track.from_layout(load_layout(layout_file))
    _, per_car = track_race(load_feed(feed_dir), track, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [estimates_frame(d, est, cfg) for d, est in per_car.items()]
    pd.concat(frames, ignore_index=True).to_parquet(out_dir / "estimates.parquet", index=False)
    hists = {d: history(e, cfg) for d, e in per_car.items() if d != our}
    rows = offline_alerts(hists, own_from_estimates(per_car[our], track, cfg), our, track, cfg)
    alerts = alerts_frame(rows)
    alerts.to_parquet(out_dir / "alerts.parquet", index=False)
    logger.info("%s: %d alerts, %s", our, len(alerts), const(cfg, "alerts.tick_s"))
    return alerts


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch, convert and run one real race."""
    parser = argparse.ArgumentParser(description="A real OpenF1 race through Simply Clipping")
    parser.add_argument("--session", type=int, default=11253, help="OpenF1 session_key")
    parser.add_argument("--our", required=True, help="Our Car's driver code, e.g. NOR")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("data/openf1_cache"))
    parser.add_argument("--layout", type=Path, default=Path("data/tracks/suzuka_layout.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    feed = args.out / "feed"
    if not (feed / "cars.parquet").exists():
        t0 = convert(args.session, args.cache, feed)
        (args.out / "t0.txt").write_text(str(t0), encoding="utf-8")
    alerts = run_real(feed, args.out, args.our, args.layout)
    print(f"{len(alerts)} alerts for {args.our} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
