"""T-011 landmarks: projection onto a (scaled) centre line, corners, pit crossings."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app
from pitwall_sim.track.builder import TrackModel, build_centre_line, project_path_to_s
from pitwall_sim.track.landmarks import multiviewer_corners, pit_crossings, project_to_s
from tests.unit.test_track_builder import RADIUS_M, STADIUM_LENGTH_M, STRAIGHT_M, _stadium_xy

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(params=[None, 1.02], ids=["raw", "scaled"])
def stadium(request: pytest.FixtureRequest) -> TrackModel:
    """Stadium sampled from s = 0 at the start of the bottom straight."""
    cfg = load_app(CONFIG_DIR).track_builder
    target = None if request.param is None else request.param * STADIUM_LENGTH_M
    x, y = _stadium_xy(start_m=0.0, noise_m=0.0)
    return build_centre_line(x, y, cfg, "stadium", target_length_m=target)


def test_projection_maps_raw_points_through_the_scaling(stadium: TrackModel) -> None:
    # Raw point 200 m along the bottom straight (y = 0).
    s, offset = project_to_s(stadium, 200.0, 0.0)

    assert s == pytest.approx(200.0 * stadium.scale_factor, abs=2.0)
    assert offset < 1.5


def test_corners_project_to_their_arc_midpoints(stadium: TrackModel) -> None:
    circuit = {
        "corners": [  # 1/10 m, like MultiViewer
            {"number": 2, "trackPosition": {"x": -RADIUS_M * 10, "y": RADIUS_M * 10}},
            {"number": 1, "trackPosition": {"x": (STRAIGHT_M + RADIUS_M) * 10, "y": RADIUS_M * 10}},
        ]
    }

    corners = multiviewer_corners(stadium, circuit)

    assert [c[0] for c in corners] == [1, 2]  # sorted by number
    mid_arc_1 = STRAIGHT_M + math.pi * RADIUS_M / 2
    mid_arc_2 = 2 * STRAIGHT_M + 1.5 * math.pi * RADIUS_M
    assert corners[0][1] == pytest.approx(mid_arc_1 * stadium.scale_factor, abs=3.0)
    assert corners[1][1] == pytest.approx(mid_arc_2 * stadium.scale_factor, abs=3.0)


def test_pit_crossings_find_where_the_trace_leaves_and_rejoins(stadium: TrackModel) -> None:
    # Drive along the bottom straight, 15 m outside it (y = -15) from x = 100 to 300.
    x = np.concatenate([np.arange(0.0, 100.0, 10.0), np.arange(100.0, 300.0, 10.0), [300.0, 350.0]])
    y = np.concatenate([np.zeros(10), np.full(20, -15.0), [0.0, 0.0]])

    crossing = pit_crossings(stadium, list(x), list(y))

    assert crossing is not None
    entry, exit_ = crossing
    assert entry == pytest.approx(100.0 * stadium.scale_factor, abs=2.0)
    assert exit_ == pytest.approx(300.0 * stadium.scale_factor, abs=2.0)


def test_pit_crossings_need_both_ends_in_the_window(stadium: TrackModel) -> None:
    on_track = pit_crossings(stadium, [0.0, 50.0, 100.0], [0.0, 0.0, 0.0])
    starts_in_lane = pit_crossings(stadium, [0.0, 50.0, 100.0], [-15.0, 0.0, 0.0])

    assert on_track is None
    assert starts_in_lane is None


def test_path_projection_survives_a_crossover() -> None:
    """Suzuka is a figure-eight: nearest-point projection jumps branches at the bridge."""
    cfg = load_app(CONFIG_DIR).track_builder
    t = np.linspace(0.0, 2 * math.pi, 400, endpoint=False)
    scale = 800.0  # lemniscate x = sin t, y = sin t cos t crosses itself at the origin
    model = build_centre_line(scale * np.sin(t), scale * np.sin(t) * np.cos(t), cfg, "eight")

    # A car driving the lap, sampled every ~20 m. Mid-lap (t = pi) it crosses the
    # other branch; that sample carries 3 m of position noise toward the other
    # branch (direction (1, 1) there), as real GPS-like data does near Suzuka's bridge.
    tt = np.linspace(0.05, 2 * math.pi - 0.05, 251)
    xs, ys = list(scale * np.sin(tt)), list(scale * np.sin(tt) * np.cos(tt))
    mid = int(np.argmin(np.abs(tt - math.pi)))
    xs[mid], ys[mid] = 3.0 / math.sqrt(2.0), 3.0 / math.sqrt(2.0)
    s = project_path_to_s(model, xs, ys)
    nearest = np.array([project_to_s(model, x, y)[0] for x, y in zip(xs, ys, strict=True)])

    assert np.all(np.diff(s) > 0.0)  # always moving forward along the lap
    assert s[-1] - s[0] == pytest.approx(model.length_m * (1 - 0.1 / (2 * math.pi)), rel=0.03)
    # Plain nearest-point projection gets at least one sample at the crossing wrong.
    assert np.any(np.abs(np.diff(np.unwrap(nearest, period=model.length_m))) > 100.0)
