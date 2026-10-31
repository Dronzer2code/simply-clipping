"""T-02D (a): corner curvature from a public circuit outline."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from pitwall_sim.calibration.compare import quali_fuel_kg
from pitwall_sim.calibration.corner_sources import implied_radius_m, write_corners
from pitwall_sim.car.dynamics import corner_speed_ms
from pitwall_sim.car.speed_profile import reference_params
from pitwall_sim.config.loader import (
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound, TrackBuilderConfig
from pitwall_sim.track import outline as O
from pitwall_sim.track.builder import TrackValidationError, build_centre_line

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
TRACKS_DIR = ROOT / "data" / "tracks"


@pytest.fixture(scope="module")
def cfg() -> TrackBuilderConfig:
    return load_app(CONFIG_DIR).track_builder


def _limacon(n: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    """Return a closed curve with no symmetry (rotation and mirror image are unique)."""
    t = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    r = 400.0 + 150.0 * np.cos(t) + 60.0 * np.sin(2 * t)
    return r * np.cos(t), r * np.sin(t)


def test_geojson_projects_to_metres(tmp_path: Path) -> None:
    lat0, radius = 34.84, 500.0
    t = np.linspace(0.0, 2 * np.pi, 721)
    lat = lat0 + np.degrees(radius * np.sin(t) / O.EARTH_RADIUS_M)
    lon = 136.54 + np.degrees(
        radius * np.cos(t) / (O.EARTH_RADIUS_M * math.cos(math.radians(lat0)))
    )
    coords = np.column_stack([lon, lat]).tolist()
    coords[-1] = coords[0]  # closed: the repeated point is dropped
    geometry = {"type": "LineString", "coordinates": coords}
    doc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geometry}]}
    path = tmp_path / "circle.geojson"
    path.write_text(json.dumps(doc), encoding="utf-8")
    x, y = O.read_geojson_xy(path)
    assert x.size == 720
    np.testing.assert_allclose(np.hypot(x - x.mean(), y - y.mean()), radius, rtol=2e-4)
    xd, yd = O.densify(x, y, 1.0)
    steps = np.hypot(np.diff(np.append(xd, xd[0])), np.diff(np.append(yd, yd[0])))
    assert steps.max() <= 1.0 + 1e-9
    assert steps.sum() == pytest.approx(2 * np.pi * radius, rel=1e-4)


def test_alignment_recovers_a_moved_mirrored_outline(cfg: TrackBuilderConfig) -> None:
    x, y = _limacon()
    model = build_centre_line(x, y, cfg, "test")
    a = math.radians(37.0)
    xm, ym = x, -y  # mirror image, then rotate, shift and start elsewhere, reversed
    xo = np.roll(math.cos(a) * xm - math.sin(a) * ym + 1234.0, 700)[::-1]
    yo = np.roll(math.sin(a) * xm + math.cos(a) * ym - 567.0, 700)[::-1]
    xa, ya, rms = O.align_to_model(xo, yo, model)
    assert rms < 0.5
    assert math.hypot(xa[0] - model.x_m[0], ya[0] - model.y_m[0]) < 2.0  # starts at the line
    heading = math.atan2(ya[3] - ya[0], xa[3] - xa[0])
    assert abs((heading - model.heading_rad[0] + math.pi) % (2 * math.pi) - math.pi) < 0.1
    k = O.outline_curvature(model, xa, ya, cfg)
    np.testing.assert_allclose(k, model.curvature_per_m, atol=2e-4)


def test_blend_weight_and_corner_blend(cfg: TrackBuilderConfig) -> None:
    x, y = _limacon()
    model = build_centre_line(x, y, cfg, "test")
    length = model.length_m
    w = O.blend_weight(model.s_m, length - 50.0, 70.0, 20.0, length)  # crosses s = 0
    assert w[np.searchsorted(model.s_m, 10.0)] == 1.0
    assert w[np.searchsorted(model.s_m, 100.0)] == 0.0
    assert w[np.searchsorted(model.s_m, length - 40.0)] == pytest.approx(0.5, abs=0.05)
    assert np.abs(np.diff(w)).max() < 0.1  # no step

    k_out = model.curvature_per_m + 0.01
    windows = {"A": (100.0, 260.0), "B": (900.0, 1000.0)}
    merged = O.blend_corners(model, k_out, windows, ["A"], cfg)
    core = (model.s_m >= 120.0) & (model.s_m <= 240.0)
    outside = (model.s_m < 100.0) | (model.s_m > 260.0)
    np.testing.assert_allclose(merged.curvature_per_m[core], k_out[core])
    np.testing.assert_array_equal(merged.curvature_per_m[outside], model.curvature_per_m[outside])
    np.testing.assert_array_equal(merged.x_m, model.x_m)  # position stays the OpenF1 line's
    with pytest.raises(TrackValidationError):
        O.blend_corners(model, k_out, windows, ["Z"], cfg)


def test_corner_windows_stop_half_way_to_the_neighbours() -> None:
    track = load_track("suzuka", CONFIG_DIR)
    windows = O.corner_windows(track, 5807.0, 80.0)
    assert windows["T16"] == (5377.0 - 80.0, 5377.0 + 35.0)  # T17 at 5447
    assert windows["T1"] == (695.0 - 80.0, 695.0 + 59.0)  # T2 at 813


def test_implied_radius_inverts_the_corner_speed() -> None:
    app, track = load_app(CONFIG_DIR), load_track("suzuka", CONFIG_DIR)
    team = load_team_performance(CONFIG_DIR).teams["mercedes"]
    p = reference_params(
        load_rule_set("2026_pre_miami", CONFIG_DIR), team, load_tyres(CONFIG_DIR),
        Compound.SOFT, app, track, quali_fuel_kg(track),
    )  # fmt: skip
    for radius in (20.0, 60.0, 90.0):
        v = corner_speed_ms(1.0 / radius, p.mu_lat, p.mass_kg, p.rho, p.aero.cla_corner,
                            p.n_ref_n, p.k_load)  # fmt: skip
        assert implied_radius_m(v, p) == pytest.approx(radius, rel=1e-6)


def test_suzuka_outline_is_recorded_and_licensed(tmp_path: Path) -> None:
    track = load_track("suzuka", CONFIG_DIR)
    outline = track.geometry_source.outline
    assert outline is not None and outline.licence == "MIT"
    assert (TRACKS_DIR / outline.file).is_file()
    notice = (TRACKS_DIR / "outlines" / "LICENSE-bacinger-f1-circuits.md").read_text("utf-8")
    assert "MIT License" in notice and outline.revision in notice
    meta = pq.read_schema(TRACKS_DIR / "suzuka.parquet").metadata
    source = json.loads(meta[b"source"])
    assert source.get("outline_corners", "") == ",".join(outline.corners)
    # --write rewrites only the corners list.
    yaml = tmp_path / "tracks" / "suzuka.yaml"
    yaml.parent.mkdir()
    shutil.copyfile(CONFIG_DIR / "tracks" / "suzuka.yaml", yaml)
    write_corners(yaml, ["T2", "T9"])
    before = (CONFIG_DIR / "tracks" / "suzuka.yaml").read_text("utf-8").splitlines()
    after = yaml.read_text("utf-8").splitlines()
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert changed == [(f"    corners: [{', '.join(outline.corners)}]", "    corners: [T2, T9]")]
