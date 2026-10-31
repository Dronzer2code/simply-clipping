"""Simply Clipping: rival battery estimates and pit-wall alerts from public telemetry.

The owner's project, a plug-in of the simulator (docs/spec/SIMPLY_CLIPPING_SPEC.md).
The two bridge functions (docs/spec/SIMPLY_CLIPPING_BRIDGE.md)::

    python -m pitwall_sim.bench --sc-module simply_clipping --scenario normal --seeds 6  (offline)
    config/app.yaml  alerts: provider: external:simply_clipping                       (live)

Never imports the simulator and never reads an export's answer sheet (SC-R01,
SC-R02).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from simply_clipping.alerts import no_alerts
from simply_clipping.energy import CarTracker, Estimates, estimates_frame
from simply_clipping.live import Provider, create
from simply_clipping.loader import (
    Config,
    Feed,
    Track,
    car_inputs,
    load_config,
    load_feed,
    load_layout,
)

__all__ = ["Provider", "create", "run"]


def run(
    feed_dir: Path, out_dir: Path, our: str | None, own_file: Path | None, layout_file: Path
) -> None:
    """Offline (the bench): one race's public feed in, estimates and alerts out."""
    cfg = load_config()
    feed = load_feed(feed_dir)
    track = Track.from_layout(load_layout(layout_file))
    trackers, per_car = track_race(feed, track, cfg)
    cda = {d: {m: tr.fit.fitted(m) for m in tr.modes} for d, tr in trackers.items()}
    (out_dir / "cda_fit.json").write_text(json.dumps(cda, indent=1), encoding="utf-8")
    frames = [estimates_frame(d, est, cfg) for d, est in per_car.items()]
    pd.concat(frames, ignore_index=True).to_parquet(out_dir / "estimates.parquet", index=False)
    if our is not None:
        no_alerts().to_parquet(out_dir / "alerts.parquet", index=False)


def track_race(
    feed: Feed, track: Track, cfg: Config
) -> tuple[dict[str, CarTracker], dict[str, Estimates]]:
    """Every car's tracker after the whole race, and its per-point estimates."""
    trackers: dict[str, CarTracker] = {}
    per_car: dict[str, Estimates] = {}
    for driver, car in car_inputs(feed, track.length_m).items():
        tracker = CarTracker(driver, car.team, track, cfg)
        first = tracker.push(car.t_s, car.speed_kmh, car.throttle_pct, car.brake, car.progress_m)
        per_car[driver] = Estimates.concat([first, tracker.flush()])
        trackers[driver] = tracker
    return trackers, per_car
