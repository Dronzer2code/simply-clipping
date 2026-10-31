"""Live plug-in for the pit wall: ``create(cfg, track)`` -> provider (bridge section 2).

The pit wall calls ``provider.update(view)`` a few times a second with ``t_s``,
``our_car`` (exact), ``timing``, ``rival_feed`` (last 120 s per car) and ``radar``
(the sim's own estimates: never used here). Alerts are returned as plain objects
with the fields of the sim's ``Alert``; this package never imports the sim (SC-R01).
Scaffold (SC-0): no alerts yet; SC-6 runs the P2-P9 pipeline on the rolling view.
"""

from __future__ import annotations

from typing import Any

from simply_clipping.loader import Config, load_config


class Provider:
    """Simply Clipping on the live pit wall."""

    def __init__(self, sim_cfg: Any, track: Any, cfg: Config | None = None) -> None:
        """``sim_cfg``: the pit wall's alert settings (unused: ours are in config.yaml)."""
        self.track = track
        self.cfg = cfg if cfg is not None else load_config()

    def update(self, view: Any) -> list[Any]:
        """Return the alerts active now."""
        return []


def create(cfg: Any, track: Any) -> Provider:
    """Return the provider; the pit wall calls this once (``external:simply_clipping``)."""
    return Provider(cfg, track)
