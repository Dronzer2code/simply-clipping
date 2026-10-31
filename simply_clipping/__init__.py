"""Simply Clipping: rival battery estimates and pit-wall alerts from public telemetry.

The owner's project, a plug-in of the simulator (docs/spec/SIMPLY_CLIPPING_SPEC.md).
The two bridge functions (docs/spec/SIMPLY_CLIPPING_BRIDGE.md)::

    python -m pitwall_sim.bench --sc-module simply_clipping --scenario normal --seeds 6  (offline)
    config/app.yaml  alerts: provider: external:simply_clipping                       (live)

Never imports the simulator and never reads an export's answer sheet (SC-R01,
SC-R02).
"""

from __future__ import annotations

from pathlib import Path

from simply_clipping.alerts import no_alerts
from simply_clipping.energy import prior_estimates
from simply_clipping.live import Provider, create
from simply_clipping.loader import load_config, load_feed, load_layout

__all__ = ["Provider", "create", "run"]


def run(
    feed_dir: Path, out_dir: Path, our: str | None, own_file: Path | None, layout_file: Path
) -> None:
    """Offline (the bench): one race's public feed in, estimates and alerts out.

    Scaffold (SC-0): P1 load and P10 write only; the estimates are the config prior
    and there are no alerts yet. Each SC task fills in its pipeline steps.
    """
    cfg = load_config()
    feed = load_feed(feed_dir)
    load_layout(layout_file)  # P5 / P8 / P9 use the zones and corners (SC-2 on)
    prior_estimates(feed.cars, cfg).to_parquet(out_dir / "estimates.parquet", index=False)
    if our is not None:
        no_alerts().to_parquet(out_dir / "alerts.parquet", index=False)
