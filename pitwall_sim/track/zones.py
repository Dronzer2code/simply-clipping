"""Zone lookups along the centre line (track config ``zones``, TRD CONFIG SCHEMAS).

A zone with ``s_end_m < s_start_m`` crosses the timing line (s = 0). Masks are
evaluated on a distance grid, typically the built model's ``s_m``, so the
physics kernel reads one boolean per metre instead of searching zones.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.models import TrackConfig, Zone


def _in_zone(zone: Zone, s_m: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
    if zone.s_start_m <= zone.s_end_m:
        return (s_m >= zone.s_start_m) & (s_m < zone.s_end_m)
    return (s_m >= zone.s_start_m) | (s_m < zone.s_end_m)


def zone_ids_mask(
    track: TrackConfig, s_m: npt.ArrayLike, zone_ids: Iterable[str]
) -> npt.NDArray[np.bool_]:
    """Mark where ``s_m`` lies in any of the zones named ``zone_ids``."""
    wanted = set(zone_ids)
    s = np.asarray(s_m, dtype=np.float64)
    mask = np.zeros(s.shape, dtype=np.bool_)
    for zone in track.zones:
        if zone.zone_id in wanted:
            mask |= _in_zone(zone, s)
    return mask


def zone_mask(
    track: TrackConfig,
    s_m: npt.ArrayLike,
    *,
    tag: str | None = None,
    zone_type: str | None = None,
) -> npt.NDArray[np.bool_]:
    """Mark where ``s_m`` lies in any zone with ``tag`` and/or of ``zone_type``.

    Raises:
        ValueError: Neither ``tag`` nor ``zone_type`` is given.

    """
    if tag is None and zone_type is None:
        raise ValueError("give a tag, a zone_type, or both")
    s = np.asarray(s_m, dtype=np.float64)
    mask = np.zeros(s.shape, dtype=np.bool_)
    if tag == "acceleration_zone" and track.acceleration_zones_source == "derived":
        length = float(track.official_length_m)
        for start, end in track.derived_acceleration_zones:  # T-027
            mask |= (s - start) % length <= (end - start) % length
        return mask
    for zone in track.zones:
        if tag is not None and tag not in zone.tags:
            continue
        if zone_type is not None and zone.type != zone_type:
            continue
        mask |= _in_zone(zone, s)
    return mask
