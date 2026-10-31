"""T-010: track builder geometry, checks, parquet round-trip, CLI and source fallback.

FastF1 is not called here: the geometry is synthetic, with known length and
curvature, plus seeded position noise like FastF1's ~4 Hz position samples.
"""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import pytest
import yaml

from pitwall_sim.config.loader import load_app, load_track
from pitwall_sim.config.models import TrackBuilderConfig
from pitwall_sim.track import builder
from pitwall_sim.track.builder import (
    EXIT_INVALID,
    EXIT_OK,
    EXIT_UNAVAILABLE,
    TrackUnavailableError,
    TrackValidationError,
    build_centre_line,
    pool_laps,
    read_track_model,
    record_geometry_source,
    validate_length,
    write_track_model,
)
from pitwall_sim.track.openf1 import OpenF1Error

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

STRAIGHT_M = 400.0
RADIUS_M = 100.0
STADIUM_LENGTH_M = 2 * STRAIGHT_M + 2 * math.pi * RADIUS_M


@pytest.fixture
def cfg() -> TrackBuilderConfig:
    return load_app(CONFIG_DIR).track_builder


def _stadium_xy(
    spacing_m: float = 14.0, noise_m: float = 0.5, start_m: float = 200.0, seed: int = 42
) -> tuple[np.ndarray, np.ndarray]:
    """Two 400 m straights joined by R100 semicircles, anticlockwise.

    Sampling starts ``start_m`` along the path (default: mid-straight, so a
    straight crosses s = 0) and stops one sample short of closing the loop.
    """
    s = (start_m + np.arange(0.0, STADIUM_LENGTH_M, spacing_m)) % STADIUM_LENGTH_M
    arc = math.pi * RADIUS_M
    x = np.empty_like(s)
    y = np.empty_like(s)
    for i, d in enumerate(s):
        if d < STRAIGHT_M:  # bottom straight, heading +x
            x[i], y[i] = d, 0.0
        elif d < STRAIGHT_M + arc:  # right semicircle
            a = (d - STRAIGHT_M) / RADIUS_M
            x[i], y[i] = STRAIGHT_M + RADIUS_M * math.sin(a), RADIUS_M - RADIUS_M * math.cos(a)
        elif d < 2 * STRAIGHT_M + arc:  # top straight, heading -x
            x[i], y[i] = STRAIGHT_M - (d - STRAIGHT_M - arc), 2 * RADIUS_M
        else:  # left semicircle
            a = (d - 2 * STRAIGHT_M - arc) / RADIUS_M
            x[i], y[i] = -RADIUS_M * math.sin(a), RADIUS_M + RADIUS_M * math.cos(a)
    rng = np.random.default_rng(seed)
    return x + rng.normal(0.0, noise_m, s.size), y + rng.normal(0.0, noise_m, s.size)


def test_stadium_length_spacing_and_closure(cfg: TrackBuilderConfig) -> None:
    model = build_centre_line(*_stadium_xy(), cfg, "stadium")

    assert model.length_m == pytest.approx(STADIUM_LENGTH_M, rel=0.005)
    # 1 m resampling, evenly spaced from the timing line.
    assert np.allclose(np.diff(model.s_m), cfg.resample_m, rtol=0.01)
    assert model.s_m[0] == 0.0
    # Closed loop: the last point is one step from the first.
    gap = math.hypot(model.x_m[-1] - model.x_m[0], model.y_m[-1] - model.y_m[0])
    assert gap == pytest.approx(cfg.resample_m, rel=0.05)


def test_stadium_curvature_and_straights(cfg: TrackBuilderConfig) -> None:
    model = build_centre_line(*_stadium_xy(), cfg, "stadium")

    # Anticlockwise semicircles: curvature ~ +1/R through the corners. The
    # smoothing spline overshoots briefly at the straight/arc joins, so check
    # the median over the corners rather than the peak.
    corners = model.curvature_per_m[model.curvature_per_m > 0.5 / RADIUS_M]
    assert np.median(corners) == pytest.approx(1 / RADIUS_M, rel=0.02)
    assert model.curvature_per_m.min() > -cfg.straight_max_curvature_per_m

    assert len(model.straights) == 2
    for straight in model.straights:
        assert straight.length_m == pytest.approx(STRAIGHT_M, abs=40.0)
    # Sampling started mid-straight, so one straight crosses the timing line
    # and is tagged as a single run, not split in two.
    assert sum(s.s_end_m < s.s_start_m for s in model.straights) == 1
    assert set(np.unique(model.straight_id)) == {-1, 0, 1}


def test_circle_has_no_straights(cfg: TrackBuilderConfig) -> None:
    radius = 300.0
    a = np.arange(0.0, 2 * math.pi, 14.0 / radius)
    model = build_centre_line(radius * np.cos(a), radius * np.sin(a), cfg, "circle")

    assert model.length_m == pytest.approx(2 * math.pi * radius, rel=0.002)
    assert np.median(model.curvature_per_m) == pytest.approx(1 / radius, rel=0.02)
    assert model.straights == ()
    assert (model.straight_id == -1).all()


def test_open_lap_is_rejected(cfg: TrackBuilderConfig) -> None:
    x, y = _stadium_xy()
    with pytest.raises(TrackValidationError, match="does not close"):
        build_centre_line(x[: x.size * 3 // 4], y[: y.size * 3 // 4], cfg, "stadium")


def test_length_check_against_official(cfg: TrackBuilderConfig) -> None:
    model = build_centre_line(*_stadium_xy(), cfg, "stadium")

    assert abs(validate_length(model, STADIUM_LENGTH_M, cfg.length_tolerance)) < 0.005
    with pytest.raises(TrackValidationError, match="official"):
        validate_length(model, STADIUM_LENGTH_M * 1.05, cfg.length_tolerance)


def test_normalize_scales_to_the_target_length_exactly(cfg: TrackBuilderConfig) -> None:
    """Owner decision round 6: uniform scale about the centroid to official length."""
    raw = build_centre_line(*_stadium_xy(), cfg, "stadium")
    target_m = 1.02 * STADIUM_LENGTH_M
    model = build_centre_line(*_stadium_xy(), cfg, "stadium", target_length_m=target_m)

    assert model.normalized
    assert model.length_m == pytest.approx(target_m, rel=1e-9)
    assert model.measured_length_m == pytest.approx(raw.length_m, rel=1e-12)
    assert model.scale_factor == pytest.approx(target_m / raw.length_m, rel=1e-12)
    # Resampled again at 1 m over the new length, still a closed loop.
    assert model.s_m.size == round(target_m / cfg.resample_m)
    assert np.allclose(np.diff(model.s_m), target_m / model.s_m.size)
    gap = math.hypot(model.x_m[-1] - model.x_m[0], model.y_m[-1] - model.y_m[0])
    assert gap == pytest.approx(cfg.resample_m, rel=0.05)
    # Shape kept: same heading profile, curvature divided by the scale factor.
    corners = model.curvature_per_m[model.curvature_per_m > 0.5 / RADIUS_M]
    assert np.median(corners) == pytest.approx(1 / (RADIUS_M * model.scale_factor), rel=0.02)
    # Scaled about the centroid, so the centroid does not move.
    assert np.mean(model.x_m) == pytest.approx(np.mean(raw.x_m), abs=0.5)
    assert np.mean(model.y_m) == pytest.approx(np.mean(raw.y_m), abs=0.5)


def test_without_target_the_model_is_not_scaled(cfg: TrackBuilderConfig) -> None:
    model = build_centre_line(*_stadium_xy(), cfg, "stadium")

    assert not model.normalized
    assert model.scale_factor == 1.0
    assert model.length_m == model.measured_length_m


def test_length_check_uses_the_raw_length(cfg: TrackBuilderConfig) -> None:
    """Normalizing to a far-off official length must not hide bad data."""
    official_m = 1.05 * STADIUM_LENGTH_M
    model = build_centre_line(*_stadium_xy(), cfg, "stadium", target_length_m=official_m)

    assert model.length_m == pytest.approx(official_m)
    with pytest.raises(TrackValidationError, match="measured length"):
        validate_length(model, official_m, cfg.length_tolerance)


def test_parquet_round_trip(cfg: TrackBuilderConfig, tmp_path: Path) -> None:
    model = build_centre_line(*_stadium_xy(), cfg, "stadium")
    path = write_track_model(model, tmp_path, {"driver": "TST"})
    loaded = read_track_model(path)

    assert path == tmp_path / "stadium.parquet"
    assert loaded.track_id == "stadium"
    assert loaded.length_m == model.length_m
    assert loaded.straights == model.straights
    for name in ("s_m", "x_m", "y_m", "heading_rad", "curvature_per_m", "straight_id"):
        assert np.array_equal(getattr(loaded, name), getattr(model, name)), name


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@pytest.fixture
def stadium_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy config/ plus a stadium track, with CWD at tmp_path for data/ paths."""
    config_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, config_dir)
    track = yaml.safe_load((CONFIG_DIR / "tracks" / "suzuka.yaml").read_text(encoding="utf-8"))
    track.update(track_id="stadium", official_length_m=STADIUM_LENGTH_M)
    track["geometry_source"].pop("source", None)
    track["geometry_source"].pop("outline", None)  # Suzuka's outline is not the stadium's
    (config_dir / "tracks" / "stadium.yaml").write_text(yaml.safe_dump(track), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return config_dir


def _provider(name: str, scale: float = 1.0) -> Callable[..., Any]:
    """Fake laps loader: three noisy stadium laps, tagged with provider ``name``."""
    laps = [_stadium_xy(seed=seed) for seed in (42, 43, 44)]

    def load(*_args: object) -> tuple[list[tuple[np.ndarray, np.ndarray]], dict[str, str]]:
        source = {"provider": name, "driver": "TST", "lap_time_s": "60.000"}
        return [(scale * x, scale * y) for x, y in laps], source

    return load


def _no_data(*_args: object) -> None:
    raise TrackUnavailableError("no data")


def _openf1_no_data(*_args: object) -> None:
    raise OpenF1Error("no data")


def _must_not_run(*_args: object) -> None:
    raise AssertionError("this provider must not be called")


def _run(config_dir: Path, *extra: str) -> int:
    return builder.main(["--track", "stadium", "--config-dir", str(config_dir), *extra])


def test_cli_builds_from_fastf1(stadium_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "load_laps_xy_fastf1", _provider("fastf1"))
    monkeypatch.setattr(builder, "load_laps_xy_openf1", _must_not_run)

    assert _run(stadium_config) == EXIT_OK
    model = read_track_model(Path("data/tracks/stadium.parquet"))
    assert model.track_id == "stadium"
    assert load_track("stadium", stadium_config).geometry_source.source == "fastf1"
    # normalize_length is on by default: length equals official_length_m exactly.
    assert model.normalized
    assert model.length_m == pytest.approx(STADIUM_LENGTH_M, rel=1e-9)
    meta = pq.read_schema("data/tracks/stadium.parquet").metadata
    assert {b"measured_length_m", b"scale_factor", b"normalized"} <= set(meta)


def test_cli_falls_back_to_openf1(stadium_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "load_laps_xy_fastf1", _no_data)
    monkeypatch.setattr(builder, "load_laps_xy_openf1", _provider("openf1"))

    assert _run(stadium_config) == EXIT_OK

    meta = pq.read_schema("data/tracks/stadium.parquet").metadata
    assert json.loads(meta[b"source"])["provider"] == "openf1"
    assert load_track("stadium", stadium_config).geometry_source.source == "openf1"


def test_cli_source_openf1_skips_fastf1(
    stadium_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "load_laps_xy_fastf1", _must_not_run)
    monkeypatch.setattr(builder, "load_laps_xy_openf1", _provider("openf1"))

    assert _run(stadium_config, "--source", "openf1") == EXIT_OK


def test_cli_source_fastf1_does_not_fall_back(
    stadium_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "load_laps_xy_fastf1", _no_data)
    monkeypatch.setattr(builder, "load_laps_xy_openf1", _must_not_run)

    assert _run(stadium_config, "--source", "fastf1") == EXIT_UNAVAILABLE


def test_cli_reports_unavailable_when_both_fail(
    stadium_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "load_laps_xy_fastf1", _no_data)
    monkeypatch.setattr(builder, "load_laps_xy_openf1", _openf1_no_data)

    assert _run(stadium_config) == EXIT_UNAVAILABLE
    assert not Path("data/tracks/stadium.parquet").exists()
    assert load_track("stadium", stadium_config).geometry_source.source is None


def test_cli_rejects_wrong_length(stadium_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "load_laps_xy_fastf1", _provider("fastf1", scale=2.0))

    assert _run(stadium_config) == EXIT_INVALID


def test_record_geometry_source_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "tracks" / "suzuka.yaml"
    path.parent.mkdir()
    shutil.copy(CONFIG_DIR / "tracks" / "suzuka.yaml", path)
    original = path.read_text(encoding="utf-8")

    record_geometry_source(path, "openf1")
    record_geometry_source(path, "fastf1")
    text = path.read_text(encoding="utf-8")

    assert text.count("  source: ") == 1
    assert load_track("suzuka", tmp_path).geometry_source.source == "fastf1"
    # Every original comment line survives.
    for line in original.splitlines():
        if line.lstrip().startswith("#"):
            assert line in text


# --------------------------------------------------------------------------- #
# T-029: pooled laps
# --------------------------------------------------------------------------- #


def _distance_to_true_stadium(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Distance of each point to the exact stadium path (the one _stadium_xy samples)."""
    px, py = _stadium_xy(spacing_m=0.25, noise_m=0.0, start_m=0.0)
    d2 = (x[:, None] - px[None, :]) ** 2 + (y[:, None] - py[None, :]) ** 2
    return np.sqrt(d2.min(axis=1))


def test_pooling_averages_laps_into_one_trace(cfg: TrackBuilderConfig) -> None:
    """Pooled points sit closer to the true path than one lap's samples."""
    laps = [_stadium_xy(spacing_m=17.0, noise_m=1.0, start_m=200.0 + 3.4 * k, seed=k)
            for k in range(5)]  # fmt: skip

    def rms_error(x: np.ndarray, y: np.ndarray) -> float:
        return float(np.sqrt(np.mean(_distance_to_true_stadium(x, y) ** 2)))

    single_err = rms_error(*laps[0])
    # ~3 samples per 10 m bin: averaging cancels much of the noise.
    assert rms_error(*pool_laps(laps, cfg.model_copy(update={"pool_bin_m": 10.0}))) < (
        0.75 * single_err
    )
    # Default 5 m bins (~1.5 samples each): mostly a denser trace, a little less noise.
    x, y = pool_laps(laps, cfg)
    assert rms_error(x, y) < single_err
    assert x.size > 2 * laps[0][0].size
    model = build_centre_line(x, y, cfg, "stadium")
    assert model.length_m == pytest.approx(STADIUM_LENGTH_M, rel=0.01)
    # Driving order from the first lap's start; the loop closes.
    assert math.hypot(x[-1] - x[0], y[-1] - y[0]) < cfg.max_closure_gap_m
    assert math.hypot(x[0] - laps[0][0][0], y[0] - laps[0][1][0]) < 10.0


def test_one_lap_is_not_pooled(cfg: TrackBuilderConfig) -> None:
    x, y = _stadium_xy()
    px, py = pool_laps([(x, y)], cfg)

    assert px is x and py is y


def test_cli_pools_the_configured_number_of_laps(
    stadium_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def load(track: object, cache_dir: object, n_laps: int) -> Any:
        calls.append(n_laps)
        return _provider("fastf1")(track, cache_dir)

    monkeypatch.setattr(builder, "load_laps_xy_fastf1", load)

    assert _run(stadium_config) == EXIT_OK
    assert _run(stadium_config, "--laps", "1") == EXIT_OK
    assert calls == [load_app(stadium_config).track_builder.pool_laps, 1]


# --------------------------------------------------------------------------- #
# T-02A: penalized centre-line fit (owner round 13 curvature check)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fit", ["splprep", "penalized"])
def test_both_fits_recover_the_stadium(cfg: TrackBuilderConfig, fit: str) -> None:
    model = build_centre_line(
        *_stadium_xy(spacing_m=5.0), cfg.model_copy(update={"centre_line_fit": fit}), "stadium"
    )
    assert model.length_m == pytest.approx(STADIUM_LENGTH_M, rel=0.005)
    bend = np.abs(model.curvature_per_m) > 0.5 / RADIUS_M
    assert np.median(1.0 / np.abs(model.curvature_per_m[bend])) == pytest.approx(RADIUS_M, rel=0.05)
    # Closed: the line ends where it starts, with the same heading.
    step = np.hypot(model.x_m[0] - model.x_m[-1], model.y_m[0] - model.y_m[-1])
    assert step == pytest.approx(model.length_m / model.s_m.size, rel=0.05)


def test_penalized_fit_keeps_a_short_sharp_corner(cfg: TrackBuilderConfig) -> None:
    """A 40 m-radius kink in a long straight: the penalized fit keeps its radius."""
    s = np.arange(0.0, 3000.0, 5.0)
    heading = np.where((s > 1000) & (s < 1000 + 40 * math.pi / 3), (s - 1000) / 40.0, 0.0)
    heading = np.where(s >= 1000 + 40 * math.pi / 3, math.pi / 3, heading)
    x, y = np.cumsum(5.0 * np.cos(heading)), np.cumsum(5.0 * np.sin(heading))
    # Close the loop with a large arc back to the start.
    back = np.linspace(0.0, 1.0, 400)[1:-1]
    cx = x[-1] + (x[0] - x[-1]) * back + 600.0 * np.sin(np.pi * back)
    cy = y[-1] + (y[0] - y[-1]) * back - 600.0 * np.sin(np.pi * back)
    xs, ys = np.concatenate((x, cx)), np.concatenate((y, cy))
    rng = np.random.default_rng(42)
    xs, ys = xs + rng.normal(0, 0.3, xs.size), ys + rng.normal(0, 0.3, ys.size)
    pen = build_centre_line(xs, ys, cfg.model_copy(update={"centre_line_fit": "penalized"}), "kink")
    kink = (pen.s_m > 950) & (pen.s_m < 1100)
    assert 1.0 / np.abs(pen.curvature_per_m[kink]).max() == pytest.approx(40.0, rel=0.25)
