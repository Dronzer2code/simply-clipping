"""Write a track's public layout for an external estimator (Simply Clipping).

    python -m pitwall_sim.export.layout --track suzuka --out data/tracks/suzuka_layout.json

Lap length, the centre line (x, y every ``--step-m`` metres) and the public
zones (with their tags: straight_mode_allowed, acceleration_zone, ...) and
corners. Nothing hidden is written. ``python -m pitwall_sim.bench`` writes it
for the plug-in it runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, load_track
from pitwall_sim.evaluate.baseline import track_model


def layout(
    track_id: str, step_m: float = 2.0, config_dir: Path = DEFAULT_CONFIG_DIR
) -> dict[str, Any]:
    """Return the public layout of ``track_id``."""
    track = load_track(track_id, config_dir)
    model = track_model({"track": track_id}, config_dir)
    k = np.arange(0, model.s_m.size, max(1, round(step_m / (model.length_m / model.s_m.size))))
    return {
        "track_id": track_id,
        "length_m": float(model.length_m),
        "centreline": {
            "s_m": [round(float(v), 2) for v in model.s_m[k]],
            "x_m": [round(float(v), 2) for v in model.x_m[k]],
            "y_m": [round(float(v), 2) for v in model.y_m[k]],
        },
        "zones": [
            {
                "zone_id": z.zone_id,
                "type": z.type,
                "s_start_m": z.s_start_m,
                "s_end_m": z.s_end_m,
                "tags": list(z.tags),
            }
            for z in track.zones
        ],  # fmt: skip
        "corners": [{"corner_id": c.corner_id, "s_m": c.s_m} for c in track.corners],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write the layout JSON."""
    parser = argparse.ArgumentParser(description="Public track layout for an estimator")
    parser.add_argument("--track", default="suzuka")
    parser.add_argument("--step-m", type=float, default=2.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(layout(args.track, args.step_m)), encoding="utf-8")
    print(f"{args.track} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
