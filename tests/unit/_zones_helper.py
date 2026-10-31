"""Test helper: zone lengths from the track config, so tests survive track rebuilds."""

from __future__ import annotations


def zone_length_m(track: object, zone_id: str, length_m: float = 5807.0) -> float:
    """Length of a track zone in metres, wrapping across s = 0."""
    zone = next(z for z in track.zones if z.zone_id == zone_id)  # type: ignore[attr-defined]
    span = zone.s_end_m - zone.s_start_m
    return span if span >= 0 else span + length_m
