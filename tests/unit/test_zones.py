"""Zone masks along the centre line, including zones that cross s = 0."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_track
from pitwall_sim.track.zones import zone_mask
from tests.unit._zones_helper import zone_length_m

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_zone_crossing_the_timing_line() -> None:
    track = load_track("suzuka", CONFIG_DIR)
    sm1 = next(z for z in track.zones if z.zone_id == "SM1")
    assert sm1.s_end_m < sm1.s_start_m  # SM1 crosses the timing line
    a, b = sm1.s_start_m, sm1.s_end_m
    s = np.array([0.0, b - 1.0, b, a - 1.0, a, 5806.0])

    mask = zone_mask(track, s, tag="straight_mode_allowed")

    assert list(mask) == [True, True, False, False, True, True]


def test_filter_by_type_and_tag() -> None:
    track = load_track("suzuka", CONFIG_DIR)
    s = np.arange(0.0, 5807.0, 1.0)

    overtaking = zone_mask(track, s, zone_type="overtaking")
    straight_mode = zone_mask(track, s, tag="straight_mode_allowed")
    acceleration = zone_mask(track, s, tag="acceleration_zone")

    assert overtaking.sum() == zone_length_m(track, "OT1")  # OT1 wraps
    assert straight_mode.sum() == zone_length_m(track, "SM1") + zone_length_m(track, "SM2")
    assert acceleration.sum() == straight_mode.sum() + zone_length_m(track, "ST3")
    assert not zone_mask(track, s, tag="straight_mode_allowed", zone_type="overtaking").any()


def test_needs_a_filter() -> None:
    track = load_track("suzuka", CONFIG_DIR)
    with pytest.raises(ValueError, match="tag"):
        zone_mask(track, [0.0])
