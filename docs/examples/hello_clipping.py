"""hello_clipping: the smallest plug-in the test bench and the pit wall accept.

Copy this file into your own package (say ``my_clipping/__init__.py``) and replace
the two function bodies with Simply Clipping. It must not import pitwall_sim.

    python -m pitwall_sim.bench --sc-module my_clipping --scenario all --seeds 6-10   (offline)
    config/app.yaml  alerts: provider: external:my_clipping                         (live)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def run(
    feed_dir: Path, out_dir: Path, our: str | None, own_file: Path | None, layout_file: Path
) -> None:
    """Offline (the bench): read one race's public feed, write your estimates and alerts.

    feed_dir    the export's feed/ folder: cars.parquet, laps.parquet, gaps.parquet
                (+ the raw car_data.parquet, pos_data.parquet)
    out_dir     write estimates.parquet, alerts.parquet (if ``our``), cda_fit.json (optional)
    our         the car the alerts are for (None: no alerts wanted)
    own_file    that car's own exact data (a team knows its own battery): a
                ground_truth.parquet whose rows you may read for ``our`` ONLY
    layout_file the track's public layout JSON (length, centre line, zones, corners)
    """
    cars = pd.read_parquet(feed_dir / "cars.parquet")
    track = json.loads(layout_file.read_text(encoding="utf-8"))
    del track  # a real estimator uses the zones (straight_mode_allowed, ...) and corners
    once_a_second = cars.assign(sec=cars["time"].astype(int)).groupby(["driver", "sec"]).first()
    est = once_a_second.reset_index()
    state = pd.Series("CRUISE", index=est.index)
    state[est["throttle"] >= 95] = "DEPLOY"  # hello world: full throttle = deploying
    state[est["throttle"] < 20] = "LIFT"
    state[est["brake"]] = "HARVEST"
    pd.DataFrame({
        "driver": est["driver"], "time_s": est["time"], "energy_mj": 2.0,  # "half full"
        "state": state, "confidence": 0.1,
    }).to_parquet(out_dir / "estimates.parquet", index=False)  # fmt: skip
    if our is not None:
        alerts = pd.DataFrame(columns=["time_s", "lap", "type", "car_a", "car_b", "confidence"])
        alerts.to_parquet(out_dir / "alerts.parquet", index=False)  # no alerts: honest at least


class Provider:
    """Live (the pit wall): ``update`` gets a view a few times a second."""

    def __init__(self, cfg: Any, track: Any) -> None:
        """``cfg``: the pit wall's alert thresholds; ``track``: zones and corners."""
        self.track = track

    def update(self, view: Any) -> list[Any]:
        """``view``: t_s, our_car (exact), timing (order, interval_s, laps_down,
        last_lap_s), rival_feed {driver: frames of the last 120 s}, radar (the
        pit wall's own estimates: ignore them). Return the alerts active now."""
        return []


def create(cfg: Any, track: Any) -> Provider:
    """Live: the pit wall calls this once (``alerts.provider: external:<module>``)."""
    return Provider(cfg, track)
