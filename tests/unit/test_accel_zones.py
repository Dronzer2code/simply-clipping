"""T-027: acceleration zones derived from the speed profile."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app, load_track
from pitwall_sim.config.models import AccelerationZonesConfig
from pitwall_sim.track import accel_zones as AZ

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def cfg() -> AccelerationZonesConfig:
    return load_app(CONFIG_DIR).acceleration_zones


def _profile() -> tuple[np.ndarray, np.ndarray, float]:
    """1 km lap: corners at 0 m (80 km/h) and 600 m (150 km/h), a 5 km/h dip at 300 m."""
    s = np.arange(1000.0)
    v = np.empty(1000)
    v[:400] = 80.0 + s[:400] * 0.5  # exit of the 0 m corner, up to 280 at 400 m
    v[280:320] -= 5.0 * np.sin(np.linspace(0.0, np.pi, 40))  # small dip: no split
    v[400:600] = np.linspace(279.0, 151.0, 200)  # braking into the 600 m corner
    v[600:700] = np.linspace(150.0, 200.0, 100)  # short exit: 100 m
    v[700:] = np.linspace(200.0, 80.0, 300, endpoint=False)  # braking back to the 0 m corner
    return s, v, 1000.0


def test_turning_points_ignore_small_dips(cfg: AccelerationZonesConfig) -> None:
    s, v, _ = _profile()
    turns = AZ.turning_points(v, cfg.min_speed_change_kmh)
    assert sorted((int(s[i]), m) for i, m in turns) == [
        (0, False), (399, True), (600, False), (699, True),
    ]  # fmt: skip


def test_zones_run_from_corner_exit_to_braking_point(cfg: AccelerationZonesConfig) -> None:
    s, v, length = _profile()
    zones = AZ.derive_zones(s, v, length, cfg)
    assert [(z.start_m, z.end_m) for z in zones] == [(0.0, 399.0)]  # the 100 m exit is too short
    assert zones[0].exit_kmh == 80.0 and zones[0].length_m == 399.0
    shifted = AZ.derive_zones(s, np.roll(v, 900), length, cfg)  # the zone now crosses s = 0
    assert [(z.start_m, z.end_m, z.length_m) for z in shifted] == [(900.0, 299.0, 399.0)]


def test_suzuka_derived_zones_cover_the_manual_straights(cfg: AccelerationZonesConfig) -> None:
    track = load_track("suzuka", CONFIG_DIR)
    s, v, length = AZ.reference_speed_kmh(track, CONFIG_DIR)
    zones = AZ.derive_zones(s, v, length, cfg)
    assert all(z.length_m >= cfg.min_length_m for z in zones)

    def covered(start: float, end: float) -> np.ndarray:
        d = (s - start) % length
        return d <= (end - start) % length

    derived = np.zeros(s.size, dtype=bool)
    for z in zones:
        derived |= covered(z.start_m, z.end_m)
    for manual in (z for z in track.zones if "acceleration_zone" in z.tags):
        share = derived[covered(manual.s_start_m, manual.s_end_m)].mean()
        assert share > 0.6, manual.zone_id  # each manual straight is mostly a derived zone
