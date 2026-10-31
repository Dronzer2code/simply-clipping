"""T-011 acceptance: Suzuka zones, corners, detection points and pit positions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app, load_track
from pitwall_sim.config.models import TrackConfig
from pitwall_sim.track.builder import TrackModel, read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def track() -> TrackConfig:
    return load_track("suzuka", CONFIG_DIR)


@pytest.fixture(scope="module")
def model() -> TrackModel:
    tracks_dir = ROOT / load_app(CONFIG_DIR).paths.tracks
    return read_track_model(tracks_dir / "suzuka.parquet")


def test_model_length_is_the_official_length(track: TrackConfig, model: TrackModel) -> None:
    assert model.normalized
    assert model.length_m == pytest.approx(track.official_length_m)


def test_zone_ids_are_unique(track: TrackConfig) -> None:
    ids = [zone.zone_id for zone in track.zones]
    assert len(ids) == len(set(ids))


def test_every_position_is_inside_the_track(track: TrackConfig, model: TrackModel) -> None:
    positions = [p for zone in track.zones for p in (zone.s_start_m, zone.s_end_m)]
    positions += track.detection_points_m
    positions += [corner.s_m for corner in track.corners]
    positions += [track.pit.entry_s_m, track.pit.exit_s_m]
    assert all(0.0 <= s < model.length_m for s in positions)


def test_corners_are_in_driving_order(track: TrackConfig) -> None:
    numbers = [int(corner.corner_id.removeprefix("T")) for corner in track.corners]
    s_values = [corner.s_m for corner in track.corners]

    assert numbers == list(range(1, 19))  # Formula1.com: 18 turns
    assert s_values == sorted(s_values)


def test_straight_mode_zones_sit_on_auto_tagged_straights(
    track: TrackConfig, model: TrackModel
) -> None:
    """Formula1.com: two Straight Mode zones, main straight and T14 -> T15."""
    sm_zones = [z for z in track.zones if "straight_mode_allowed" in z.tags]
    straights = {(round(s.s_start_m), round(s.s_end_m)) for s in model.straights}

    assert len(sm_zones) == 2
    for zone in sm_zones:
        assert (round(zone.s_start_m), round(zone.s_end_m)) in straights, zone.zone_id


def test_detection_point_is_turn_17(track: TrackConfig) -> None:
    t17 = next(c for c in track.corners if c.corner_id == "T17")
    assert track.detection_points_m == [t17.s_m]


def test_overtaking_zone_has_a_difficulty_entry(track: TrackConfig) -> None:
    overtaking = [z.zone_id for z in track.zones if z.type == "overtaking"]
    assert overtaking == ["OT1"]
    assert set(overtaking) <= set(track.zone_difficulty)


def test_pit_lane_runs_from_before_t18_to_before_t1(track: TrackConfig) -> None:
    s = {c.corner_id: c.s_m for c in track.corners}
    assert s["T17"] < track.pit.entry_s_m < s["T18"]
    assert track.pit.exit_s_m < s["T1"]


def test_acceleration_zones_are_the_three_owner_approved_straights(
    track: TrackConfig, model: TrackModel
) -> None:
    """Owner decision before T-021: the three auto-tagged straights (ASSUMED).

    The T-029 pooled model also tags a fourth straight (T9 -> T11), left for
    T-027; every tagged zone must still sit on an auto-tagged straight.
    """
    tagged = {
        (round(z.s_start_m), round(z.s_end_m)) for z in track.zones if "acceleration_zone" in z.tags
    }
    straights = {(round(s.s_start_m), round(s.s_end_m)) for s in model.straights}

    assert track.acceleration_zones_source == "manual"
    assert len(tagged) == 3
    # Two sit on auto-tagged straights; since the T-02A geometry the 130R -> T16
    # run (ST3) is a near-straight (tightest radius >= 150 m), kept by the owner's
    # decision until T-027.
    assert len(tagged & straights) == 2
    for start, end in tagged - straights:
        sel = (model.s_m >= start) & (model.s_m < end)
        assert 1.0 / np.abs(model.curvature_per_m[sel]).max() >= 150.0
