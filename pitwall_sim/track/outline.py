"""Corner curvature from a public circuit outline (T-02D, owner round 15).

A GeoJSON circuit outline (lon / lat polyline) is projected to metres,
resampled at ``track_builder.resample_m``, fitted with the builder's centre-line
spline, scaled to ``official_length_m`` and aligned with the OpenF1 centre line
(rigid: rotation, translation, mirror check). Its curvature, placed on the
OpenF1 model's distance ``s`` by projection, replaces the OpenF1 curvature at
the corners listed in ``geometry_source.outline.corners`` (chosen by
``python -m pitwall_sim.calibration.corner_sources``: per corner, the source
whose radius is closer to the one implied by real minimum speeds). Inside a
corner window (half-way to the neighbouring corners, at most
``outline_window_max_m`` each side) the outline's curvature is blended in with a
cosine taper of ``outline_blend_m`` at both ends. Position and heading stay the
OpenF1 line's.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.models import TrackBuilderConfig, TrackConfig
from pitwall_sim.track.builder import (
    TrackModel,
    TrackValidationError,
    _tag_straights,
    build_centre_line,
    project_path_to_s,
)

type FloatArray = npt.NDArray[np.float64]

#: Mean Earth radius (IUGG), m.
EARTH_RADIUS_M = 6371008.8

#: Coarse rotation search step before ICP, degrees.
_ROTATION_STEP_DEG = 2.0
_ICP_ITERATIONS = 50


def read_geojson_xy(path: Path) -> tuple[FloatArray, FloatArray]:
    """Return the first LineString of a GeoJSON file in local metres (east, north).

    Equirectangular projection about the outline's centroid: over a circuit's
    ~2 km the distortion is far below a metre. A closing point that repeats the
    first is dropped.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    feature = data["features"][0] if "features" in data else data
    geometry = feature["geometry"]
    coords = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        coords = coords[0]
    elif geometry["type"] != "LineString":
        raise TrackValidationError(f"{path}: unsupported geometry {geometry['type']}")
    c = np.asarray(coords, dtype=np.float64)
    lon0, lat0 = float(c[:, 0].mean()), float(c[:, 1].mean())
    x = np.radians(c[:, 0] - lon0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    y = np.radians(c[:, 1] - lat0) * EARTH_RADIUS_M
    if np.hypot(x[-1] - x[0], y[-1] - y[0]) < 1e-6:
        x, y = x[:-1], y[:-1]
    return x, y


def densify(x: FloatArray, y: FloatArray, step_m: float) -> tuple[FloatArray, FloatArray]:
    """Points every ``step_m`` (or closer) along the closed polyline."""
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    xs, ys = [], []
    for k in range(x.size):
        n = max(math.ceil(math.hypot(xn[k] - x[k], yn[k] - y[k]) / step_m), 1)
        t = np.arange(n) / n
        xs.append(x[k] + t * (xn[k] - x[k]))
        ys.append(y[k] + t * (yn[k] - y[k]))
    return np.concatenate(xs), np.concatenate(ys)


def align_to_model(
    x: FloatArray, y: FloatArray, model: TrackModel
) -> tuple[FloatArray, FloatArray, float]:
    """Place a closed outline on the model's centre line; return ``(x, y, rms_m)``.

    The outline is scaled to the model's length, then a coarse search over
    rotations (and a mirror image) and ICP (Kabsch) fit it rigidly. The result
    starts at the point nearest the timing line and runs in the driving
    direction; ``rms_m`` is the RMS distance to the model's line.
    """
    from scipy.spatial import cKDTree  # noqa: PLC0415  (building only)

    tree = cKDTree(np.column_stack([model.x_m, model.y_m]))
    length = float(np.sum(np.hypot(np.diff(np.append(x, x[0])), np.diff(np.append(y, y[0])))))
    centre = np.array([model.x_m.mean(), model.y_m.mean()])
    p0 = np.column_stack([x - x.mean(), y - y.mean()]) * (model.length_m / length)

    def rms(p: FloatArray) -> float:
        d, _ = tree.query(p)
        return float(np.sqrt(np.mean(d**2)))

    def rotation(angle: float) -> FloatArray:
        return np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])

    candidates = [
        (q @ rotation(a).T) + centre
        for q in (p0, p0 * np.array([1.0, -1.0]))
        for a in np.radians(np.arange(0.0, 360.0, _ROTATION_STEP_DEG))
    ]
    p = min(candidates, key=rms)
    for _ in range(_ICP_ITERATIONS):
        _, j = tree.query(p)
        target = np.column_stack([model.x_m[j], model.y_m[j]])
        pc, tc = p.mean(axis=0), target.mean(axis=0)
        u, _, vt = np.linalg.svd((p - pc).T @ (target - tc))
        d = np.diag([1.0, float(np.sign(np.linalg.det(vt.T @ u.T)))])
        p = (p - pc) @ (vt.T @ d @ u.T).T + tc

    start = int(np.argmin(np.hypot(p[:, 0] - model.x_m[0], p[:, 1] - model.y_m[0])))
    p = np.roll(p, -start, axis=0)
    ahead = min(5, p.shape[0] - 1)
    heading = math.atan2(p[ahead, 1] - p[0, 1], p[ahead, 0] - p[0, 0])
    if abs((heading - model.heading_rad[0] + math.pi) % (2 * math.pi) - math.pi) > math.pi / 2:
        p = np.concatenate([p[:1], p[1:][::-1]])
    return p[:, 0].copy(), p[:, 1].copy(), rms(p)


def outline_curvature(
    model: TrackModel, x: FloatArray, y: FloatArray, cfg: TrackBuilderConfig
) -> FloatArray:
    """Return the aligned outline's signed curvature at the model's ``s`` points."""
    line = build_centre_line(x, y, cfg, model.track_id, target_length_m=model.length_m)
    # project_path_to_s takes raw (unscaled) coordinates: undo the model's scaling.
    cx, cy = float(np.mean(model.x_m)), float(np.mean(model.y_m))
    s_on = (
        project_path_to_s(
            model,
            cx + (line.x_m - cx) / model.scale_factor,
            cy + (line.y_m - cy) / model.scale_factor,
        )
        % model.length_m
    )
    order = np.argsort(s_on)
    return np.interp(
        model.s_m, s_on[order], line.curvature_per_m[order], period=model.length_m
    ).astype(np.float64)


def corner_windows(
    track: TrackConfig, length_m: float, max_m: float
) -> dict[str, tuple[float, float]]:
    """Map corner_id to its window (start_m, end_m): half-way to the neighbours, <= ``max_m``."""
    corners = sorted(track.corners, key=lambda c: c.s_m)

    def ahead(a: float, b: float) -> float:
        return (a - b) % length_m

    out = {}
    for k, c in enumerate(corners):
        before = ahead(c.s_m, corners[k - 1].s_m) if len(corners) > 1 else 2 * max_m
        after = ahead(corners[(k + 1) % len(corners)].s_m, c.s_m) if len(corners) > 1 else 2 * max_m
        out[c.corner_id] = (c.s_m - min(0.5 * before, max_m), c.s_m + min(0.5 * after, max_m))
    return out


def blend_weight(
    s_m: FloatArray, start_m: float, end_m: float, taper_m: float, length_m: float
) -> FloatArray:
    """1 inside the window, cosine taper to 0 over ``taper_m`` at both ends, 0 outside."""
    d = (s_m - start_m) % length_m
    span = (end_m - start_m) % length_m  # a window may cross s = 0 either way
    inside = d <= span
    edge = np.minimum(d, span - d)
    w = np.where(
        edge >= taper_m, 1.0, 0.5 - 0.5 * np.cos(np.pi * np.clip(edge, 0.0, None) / taper_m)
    )
    return np.where(inside, w, 0.0)


def blend_corners(
    model: TrackModel,
    k_outline: FloatArray,
    windows: dict[str, tuple[float, float]],
    corners: list[str],
    cfg: TrackBuilderConfig,
) -> TrackModel:
    """Return the model with the outline's curvature at ``corners`` (straights re-tagged)."""
    unknown = sorted(set(corners) - set(windows))
    if unknown:
        raise TrackValidationError(f"{model.track_id}: outline corners not in the track: {unknown}")
    w = np.zeros_like(model.s_m)
    for corner in corners:
        start, end = windows[corner]
        w = np.maximum(w, blend_weight(model.s_m, start, end, cfg.outline_blend_m, model.length_m))
    curvature = (1.0 - w) * model.curvature_per_m + w * k_outline
    straight_id, straights = _tag_straights(curvature, model.length_m / model.s_m.size, cfg)
    return replace(model, curvature_per_m=curvature, straight_id=straight_id, straights=straights)


def outline_model(
    model: TrackModel, track: TrackConfig, cfg: TrackBuilderConfig, tracks_dir: Path
) -> tuple[FloatArray, float]:
    """Return the configured outline's curvature on ``model`` and the alignment RMS (m)."""
    outline = track.geometry_source.outline
    if outline is None:
        raise TrackValidationError(f"{track.track_id}: no geometry_source.outline")
    x, y = densify(*read_geojson_xy(tracks_dir / outline.file), cfg.resample_m)
    xa, ya, rms_m = align_to_model(x, y, model)
    return outline_curvature(model, xa, ya, cfg), rms_m


def apply_outline(
    model: TrackModel, track: TrackConfig, cfg: TrackBuilderConfig, tracks_dir: Path
) -> tuple[TrackModel, dict[str, str]]:
    """Blend the configured outline into ``model``; also return source metadata."""
    outline = track.geometry_source.outline
    assert outline is not None
    k_outline, rms_m = outline_model(model, track, cfg, tracks_dir)
    windows = corner_windows(track, model.length_m, cfg.outline_window_max_m)
    merged = blend_corners(model, k_outline, windows, outline.corners, cfg)
    info = {
        "outline_provider": outline.provider,
        "outline_revision": outline.revision,
        "outline_corners": ",".join(outline.corners),
        "outline_alignment_rms_m": f"{rms_m:.2f}",
    }
    return merged, info
