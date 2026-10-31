"""F01 track builder: FastF1 geometry to a 1 m resampled centre line (PF-01).

Pipeline: X/Y of the fastest N clean laps, one per driver, from FastF1 (or
OpenF1 when FastF1 has no live-timing data), averaged into one trace (T-029,
``track_builder.pool_laps``) -> periodic smoothing spline -> centre line
resampled at ``track_builder.resample_m`` -> heading and signed curvature ->
straights auto-tagged by a curvature threshold -> closed-loop and official-length
checks -> ``data/tracks/<track_id>.parquet``.

Usage::

    python -m pitwall_sim.track.builder --track suzuka
    python -m pitwall_sim.track.builder --track suzuka --source openf1
    python -m pitwall_sim.track.builder --track suzuka --laps 1     # no pooling
    python -m pitwall_sim.track.builder --track suzuka --cache-only
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
import pyarrow.parquet as pq

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, ConfigError, load_app, load_track
from pitwall_sim.config.models import AppConfig, TrackBuilderConfig, TrackConfig
from pitwall_sim.track.openf1 import OpenF1Client, OpenF1Error, load_laps_xy_openf1

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]

#: FastF1 position telemetry X/Y are in 1/10 m.
FASTF1_POS_UNIT_M = 0.1

#: Points per output metre used to measure arc length along the spline.
_DENSE_PER_M = 10

#: Lap distance wrapped onto both ends so the penalized fit closes smoothly.
_WRAP_M = 200.0

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNAVAILABLE = 2

_AUTH_HINT = (
    "the F1 live-timing archive needs a Formula 1 account login "
    "(`python -m fastf1 auth f1tv --authenticate`); without one use --source openf1"
)

#: ``--source`` choices. ``auto`` tries FastF1 and falls back to OpenF1.
SOURCES = ("auto", "fastf1", "openf1")


class TrackUnavailableError(Exception):
    """FastF1 has no usable geometry for the track (PF-01 status ``UNAVAILABLE``)."""


class TrackValidationError(Exception):
    """The built centre line fails a PF-01 check (closure, official length)."""


@dataclass(frozen=True)
class Straight:
    """An auto-tagged straight. ``s_end_m < s_start_m`` when it crosses s = 0."""

    straight_id: int
    s_start_m: float
    s_end_m: float
    length_m: float


@dataclass(frozen=True)
class TrackModel:
    """Built centre line, one row per ``resample_m`` of distance ``s`` from the timing line."""

    track_id: str
    length_m: float
    """Lap length of this model (equals ``official_length_m`` when normalized)."""
    measured_length_m: float
    """Length of the spline through the raw position samples, before any scaling."""
    scale_factor: float
    """``length_m / measured_length_m``; 1.0 when not normalized."""
    normalized: bool
    s_m: FloatArray
    x_m: FloatArray
    y_m: FloatArray
    heading_rad: FloatArray
    curvature_per_m: FloatArray
    """Signed: positive turns left (anticlockwise)."""
    straight_id: IntArray
    """Index into ``straights``, or -1 off any auto-tagged straight."""
    straights: tuple[Straight, ...]


# --------------------------------------------------------------------------- #
# Geometry (pure, no FastF1)
# --------------------------------------------------------------------------- #


def build_centre_line(
    x_m: npt.ArrayLike,
    y_m: npt.ArrayLike,
    cfg: TrackBuilderConfig,
    track_id: str,
    target_length_m: float | None = None,
) -> TrackModel:
    """Fit a closed centre line to one lap of position samples.

    A car's path cuts across corners, so it is a little shorter than the
    official (centre-line) lap length. With ``target_length_m`` the fitted
    curve is scaled uniformly about its centroid to exactly that length before
    resampling: shape and heading are kept, curvature scales by the inverse.

    Args:
        x_m: Lap X positions in metres, in driving order, starting at the timing line.
        y_m: Lap Y positions in metres.
        cfg: Builder parameters (``config/app.yaml: track_builder``).
        track_id: Track id stored on the model.
        target_length_m: Length to normalize to, or ``None`` to keep the measured one.

    Raises:
        TrackValidationError: Too few samples, or the lap does not close.

    """
    x, y = _drop_repeated_points(
        np.asarray(x_m, dtype=np.float64), np.asarray(y_m, dtype=np.float64)
    )
    if x.size < 20:
        raise TrackValidationError(f"{track_id}: only {x.size} distinct position samples")

    gap_m = float(np.hypot(x[-1] - x[0], y[-1] - y[0]))
    if gap_m > cfg.max_closure_gap_m:
        raise TrackValidationError(
            f"{track_id}: lap does not close: first/last samples {gap_m:.1f} m apart "
            f"(max {cfg.max_closure_gap_m} m)"
        )
    if gap_m < 1e-6:
        x, y = x[:-1], y[:-1]

    curve = (
        _penalized_curve(x, y, cfg.smoothing_lambda_m3)
        if cfg.centre_line_fit == "penalized"
        else _splprep_curve(x, y, cfg.smoothing_rms_m)
    )
    u_dense = np.linspace(curve.u_start, curve.u_end, int(curve.chord_m * _DENSE_PER_M) + 1)
    xd, yd = curve.eval(u_dense, 0)
    cum_m = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(xd), np.diff(yd)))))
    if cfg.centre_line_fit == "penalized":  # close the loop back to the start point
        cum_m = np.append(cum_m, cum_m[-1] + float(np.hypot(xd[0] - xd[-1], yd[0] - yd[-1])))
        u_dense = np.append(u_dense, curve.u_end + (cum_m[-1] - cum_m[-2]))
    measured_length_m = float(cum_m[-1])

    # Uniform scaling about the centroid keeps shape and heading; arc length
    # scales by the same factor and curvature by its inverse.
    scale = 1.0 if target_length_m is None else target_length_m / measured_length_m
    centre_x, centre_y = float(np.mean(xd)), float(np.mean(yd))
    length_m = measured_length_m * scale

    n = max(int(round(length_m / cfg.resample_m)), 3)
    s = np.arange(n, dtype=np.float64) * (length_m / n)
    u_s = np.interp(s / scale, cum_m, u_dense)
    x0, y0 = curve.eval(u_s, 0)
    xs = centre_x + scale * (x0 - centre_x)
    ys = centre_y + scale * (y0 - centre_y)
    dx, dy = curve.eval(u_s, 1)
    ddx, ddy = curve.eval(u_s, 2)
    dx, dy, ddx, ddy = scale * dx, scale * dy, scale * ddx, scale * ddy

    heading = np.arctan2(dy, dx)
    curvature = (dx * ddy - dy * ddx) / np.power(dx * dx + dy * dy, 1.5)
    straight_id, straights = _tag_straights(curvature, length_m / n, cfg)

    return TrackModel(
        track_id=track_id,
        length_m=length_m,
        measured_length_m=measured_length_m,
        scale_factor=scale,
        normalized=target_length_m is not None,
        s_m=s,
        x_m=xs,
        y_m=ys,
        heading_rad=heading,
        curvature_per_m=curvature,
        straight_id=straight_id,
        straights=straights,
    )


@dataclass(frozen=True)
class _Curve:
    """A closed parametric curve: ``eval(u, der)`` gives x, y or their derivatives."""

    eval: Callable[[FloatArray, int], tuple[FloatArray, FloatArray]]
    u_start: float
    u_end: float
    chord_m: float


def _splprep_curve(x: FloatArray, y: FloatArray, smoothing_rms_m: float) -> _Curve:
    """Periodic smoothing spline with adaptive knots (``splprep``, T-010)."""
    from scipy.interpolate import splev, splprep  # noqa: PLC0415  (building only)

    # splprep(per=1) treats the data as periodic and ignores the last point's
    # value, so repeat the first point to close the loop.
    xc, yc = np.append(x, x[0]), np.append(y, y[0])
    tck, u = splprep([xc, yc], s=xc.size * smoothing_rms_m**2, per=1)

    def evaluate(uu: FloatArray, der: int) -> tuple[FloatArray, FloatArray]:
        a, b = splev(uu, tck, der=der)
        return np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)

    chord = float(np.sum(np.hypot(np.diff(xc), np.diff(yc))))
    return _Curve(evaluate, float(u[0]), float(u[-1]), chord)


def _penalized_curve(x: FloatArray, y: FloatArray, lam: float) -> _Curve:
    """Penalized cubic smoothing splines x(u), y(u) over chord length u (T-02A).

    The same roughness penalty ``lam`` everywhere, unlike ``splprep``'s adaptive
    knots, which can cut a short sharp corner and sharpen another. Closed by
    wrapping ``_WRAP_M`` of the lap onto both ends before fitting.
    """
    from scipy.interpolate import make_smoothing_spline  # noqa: PLC0415  (building only)

    seg = np.hypot(np.diff(np.append(x, x[0])), np.diff(np.append(y, y[0])))
    u = np.concatenate(([0.0], np.cumsum(seg)[:-1]))
    perimeter = float(seg.sum())
    wrap = min(_WRAP_M, 0.25 * perimeter)
    head, tail = u <= wrap, u >= perimeter - wrap
    uu = np.concatenate((u[tail] - perimeter, u, u[head] + perimeter))
    bx = make_smoothing_spline(uu, np.concatenate((x[tail], x, x[head])), lam=lam)
    by = make_smoothing_spline(uu, np.concatenate((y[tail], y, y[head])), lam=lam)

    def evaluate(uq: FloatArray, der: int) -> tuple[FloatArray, FloatArray]:
        return np.asarray(bx(uq, der), dtype=np.float64), np.asarray(by(uq, der), dtype=np.float64)

    return _Curve(evaluate, 0.0, float(u[-1]), perimeter)


def _drop_repeated_points(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Remove consecutive samples at the same position (car stationary or duplicated)."""
    keep = np.concatenate(([True], np.hypot(np.diff(x), np.diff(y)) > 1e-6))
    return x[keep], y[keep]


def _tag_straights(
    curvature: FloatArray, spacing_m: float, cfg: TrackBuilderConfig
) -> tuple[IntArray, tuple[Straight, ...]]:
    """Tag runs with |curvature| below the threshold and at least the minimum length.

    A run that crosses the timing line (s = 0) is one straight, not two.
    """
    n = curvature.size
    flat = np.abs(curvature) < cfg.straight_max_curvature_per_m
    straight_id = np.full(n, -1, dtype=np.int64)
    if not flat.any():
        return straight_id, ()
    if flat.all():
        straight_id[:] = 0
        return straight_id, (Straight(0, 0.0, 0.0, n * spacing_m),)

    # Walk the loop starting just after a curved point, so no run is split at s = 0.
    first = int(np.argmin(flat))
    order = np.roll(np.arange(n), -first)
    runs: list[npt.NDArray[np.int64]] = []
    i = 0
    while i < n:
        if not flat[order[i]]:
            i += 1
            continue
        j = i
        while j < n and flat[order[j]]:
            j += 1
        if (j - i) * spacing_m >= cfg.straight_min_length_m:
            runs.append(order[i:j])
        i = j

    runs.sort(key=lambda idx: int(idx[0]))
    straights: list[Straight] = []
    for k, idx in enumerate(runs):
        straight_id[idx] = k
        straights.append(
            Straight(
                straight_id=k,
                s_start_m=float(idx[0]) * spacing_m,
                s_end_m=float((idx[-1] + 1) % n) * spacing_m,
                length_m=idx.size * spacing_m,
            )
        )
    return straight_id, tuple(straights)


def project_path_to_s(
    model: TrackModel,
    x_m: Sequence[float] | FloatArray,
    y_m: Sequence[float] | FloatArray,
    max_back_m: float = 20.0,
    max_ahead_m: float = 400.0,
) -> npt.NDArray[np.float64]:
    """Distances along the lap for a time-ordered trace, unwrapped (monotonic over a lap).

    Nearest-point projection is ambiguous where the track crosses itself
    (Suzuka is a figure-eight: the back straight passes over the section after
    Degner), so after the first sample each point is only matched within
    ``[-max_back_m, +max_ahead_m]`` of the previous one along the lap.
    """
    n = model.s_m.size
    ds = model.length_m / n
    cx, cy = float(np.mean(model.x_m)), float(np.mean(model.y_m))
    out = np.empty(len(x_m), dtype=np.float64)
    prev = -1
    for k, (x, y) in enumerate(zip(x_m, y_m, strict=True)):
        qx = cx + model.scale_factor * (x - cx)
        qy = cy + model.scale_factor * (y - cy)
        if prev < 0:
            i = int(np.argmin(np.hypot(model.x_m - qx, model.y_m - qy)))
            out[k] = model.s_m[i]
        else:
            window = (prev + np.arange(-int(max_back_m / ds), int(max_ahead_m / ds) + 1)) % n
            j = int(np.argmin(np.hypot(model.x_m[window] - qx, model.y_m[window] - qy)))
            i = int(window[j])
            step = (i - prev + n // 2) % n - n // 2  # signed index step, wrap-aware
            out[k] = out[k - 1] + step * ds
        prev = i
    return out


def validate_length(model: TrackModel, official_length_m: float, tolerance: float) -> float:
    """Check the measured (raw, pre-scaling) length against the official one.

    Runs on the raw length even when the model is normalized, so it still
    catches bad data. Returns the relative error.

    Raises:
        TrackValidationError: The relative error exceeds ``tolerance``.

    """
    error = (model.measured_length_m - official_length_m) / official_length_m
    if abs(error) > tolerance:
        raise TrackValidationError(
            f"{model.track_id}: measured length {model.measured_length_m:.0f} m is "
            f"{error:+.2%} from official {official_length_m:.0f} m (max {tolerance:.0%})"
        )
    return error


# --------------------------------------------------------------------------- #
# Parquet I/O
# --------------------------------------------------------------------------- #


def write_track_model(
    model: TrackModel, out_dir: Path, source: dict[str, str] | None = None
) -> Path:
    """Write ``<out_dir>/<track_id>.parquet``; scalars go in the file metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{model.track_id}.parquet"
    table = pl.DataFrame(
        {
            "s_m": model.s_m,
            "x_m": model.x_m,
            "y_m": model.y_m,
            "heading_rad": model.heading_rad,
            "curvature_per_m": model.curvature_per_m,
            "straight_id": model.straight_id,
        }
    ).to_arrow()
    meta = {
        "track_id": model.track_id,
        "length_m": repr(model.length_m),
        "measured_length_m": repr(model.measured_length_m),
        "scale_factor": repr(model.scale_factor),
        "normalized": json.dumps(model.normalized),
        "straights": json.dumps([s.__dict__ for s in model.straights]),
        "source": json.dumps(source or {}),
    }
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def read_track_model(path: Path) -> TrackModel:
    """Read a model written by :func:`write_track_model`."""
    # ParquetFile, not read_table: read_table imports pyarrow.dataset (and pandas),
    # ~1 s at every race start (NFR-02).
    table = pq.ParquetFile(path).read()
    meta = {k.decode(): v.decode() for k, v in (table.schema.metadata or {}).items()}
    df = pl.from_arrow(table)
    assert isinstance(df, pl.DataFrame)
    return TrackModel(
        track_id=meta["track_id"],
        length_m=float(meta["length_m"]),
        measured_length_m=float(meta["measured_length_m"]),
        scale_factor=float(meta["scale_factor"]),
        normalized=bool(json.loads(meta["normalized"])),
        s_m=df["s_m"].to_numpy(),
        x_m=df["x_m"].to_numpy(),
        y_m=df["y_m"].to_numpy(),
        heading_rad=df["heading_rad"].to_numpy(),
        curvature_per_m=df["curvature_per_m"].to_numpy(),
        straight_id=df["straight_id"].to_numpy().astype(np.int64),
        straights=tuple(Straight(**s) for s in json.loads(meta["straights"])),
    )


# --------------------------------------------------------------------------- #
# FastF1
# --------------------------------------------------------------------------- #


def load_laps_xy_fastf1(
    track: TrackConfig, cache_dir: Path, n_laps: int = 1
) -> tuple[list[tuple[FloatArray, FloatArray]], dict[str, str]]:
    """Load X/Y in metres for the ``n_laps`` fastest laps, one per driver (T-029).

    With a named ``geometry_source.driver`` only that driver's fastest lap.

    Returns:
        The laps (fastest first) and a source description for the parquet metadata.

    Raises:
        TrackUnavailableError: FastF1 has no session, laps or position data.

    """
    import fastf1  # heavy import, only needed for a real build
    from fastf1.exceptions import DataNotLoadedError, InvalidSessionError, NoLapDataError

    src = track.geometry_source
    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    try:
        session = fastf1.get_session(src.year, track.fastf1_event, src.session)
        session.load(laps=True, telemetry=True, weather=False, messages=False)
        laps = session.laps
    except (DataNotLoadedError, InvalidSessionError, NoLapDataError, ValueError) as exc:
        raise TrackUnavailableError(
            f"{track.track_id}: no {src.year} {track.fastf1_event} {src.session} lap data "
            f"({exc.__class__.__name__}); {_AUTH_HINT}"
        ) from exc

    if src.driver != "fastest":
        laps = laps.pick_drivers(src.driver)
        n_laps = 1
    fastest = []
    for driver in laps["Driver"].unique():
        lap = laps.pick_drivers(driver).pick_fastest()
        if lap is not None:
            fastest.append(lap)
    fastest.sort(key=lambda lap: lap["LapTime"])
    if not fastest:
        raise TrackUnavailableError(f"{track.track_id}: no timed lap in the session")
    xy: list[tuple[FloatArray, FloatArray]] = []
    for lap in fastest[:n_laps]:
        try:
            pos = lap.get_pos_data()
        except (DataNotLoadedError, ValueError, KeyError) as exc:
            raise TrackUnavailableError(
                f"{track.track_id}: no position data; {_AUTH_HINT}"
            ) from exc
        if pos is None or pos.empty:
            raise TrackUnavailableError(f"{track.track_id}: no position data; {_AUTH_HINT}")
        xy.append(
            (
                pos["X"].to_numpy(dtype=np.float64) * FASTF1_POS_UNIT_M,
                pos["Y"].to_numpy(dtype=np.float64) * FASTF1_POS_UNIT_M,
            )
        )
    lap = fastest[0]
    source = {
        "provider": "fastf1",
        "year": str(src.year),
        "event": track.fastf1_event,
        "session": src.session,
        "driver": str(lap["Driver"]),
        "lap_time_s": f"{lap['LapTime'].total_seconds():.3f}",
        "fastf1": fastf1.__version__,
        "pooled_laps": ";".join(
            f"{lap_['Driver']}:{lap_['LapTime'].total_seconds():.3f}" for lap_ in fastest[:n_laps]
        ),
    }
    return xy, source


def load_laps_xy(
    track: TrackConfig, app: AppConfig, source: str = "auto", n_laps: int = 1
) -> tuple[list[tuple[FloatArray, FloatArray]], dict[str, str]]:
    """Load laps from ``source``: ``fastf1``, ``openf1``, or ``auto`` (FastF1, then OpenF1).

    Raises:
        TrackUnavailableError: No selected provider has the laps.

    """
    if source in ("auto", "fastf1"):
        try:
            return load_laps_xy_fastf1(track, Path(app.paths.fastf1_cache), n_laps)
        except TrackUnavailableError as exc:
            if source == "fastf1":
                raise
            logger.warning("FastF1 has no data (%s); falling back to OpenF1", exc)
    client = OpenF1Client(app.openf1, Path(app.paths.openf1_cache))
    try:
        return load_laps_xy_openf1(track, client, n_laps)
    except OpenF1Error as exc:
        raise TrackUnavailableError(f"{track.track_id}: OpenF1: {exc}") from exc


def pool_laps(
    laps: Sequence[tuple[FloatArray, FloatArray]], cfg: TrackBuilderConfig
) -> tuple[FloatArray, FloatArray]:
    """Average several laps' position samples into one trace (T-029).

    The first lap (the fastest) gives a reference centre line; every lap's
    samples are placed along it with the path-continuous projection (safe at
    crossovers) and the raw X/Y are averaged in bins of ``cfg.pool_bin_m``.
    The result starts at the timing line and runs in driving order.
    """
    if len(laps) == 1:
        return laps[0]
    reference = build_centre_line(*laps[0], cfg, "pool-reference")
    s = np.concatenate([project_path_to_s(reference, x, y) % reference.length_m for x, y in laps])
    x = np.concatenate([lap[0] for lap in laps])
    y = np.concatenate([lap[1] for lap in laps])
    bins = np.floor(s / cfg.pool_bin_m).astype(np.int64)
    keys, inverse, counts = np.unique(bins, return_inverse=True, return_counts=True)
    x_mean = np.bincount(inverse, weights=x) / counts
    y_mean = np.bincount(inverse, weights=y) / counts
    logger.info(
        "pooled %d laps: %d samples into %d bins of %.0f m", len(laps), s.size, keys.size,
        cfg.pool_bin_m,
    )  # fmt: skip
    return x_mean, y_mean


def build_from_laps(
    laps: list[tuple[FloatArray, FloatArray]], track: TrackConfig, cfg: TrackBuilderConfig
) -> tuple[TrackModel, float]:
    """Pool the laps and fit the centre line; return it and its raw length error.

    Raises:
        TrackValidationError: The laps do not give a valid closed line of the official length.

    """
    official_m = track.official_length_m
    assert not isinstance(official_m, str)
    x, y = pool_laps(laps, cfg)
    model = build_centre_line(
        x, y, cfg, track.track_id, official_m if cfg.normalize_length else None
    )
    return model, validate_length(model, official_m, cfg.length_tolerance)


def record_geometry_source(track_yaml: Path, provider: str) -> None:
    """Set ``geometry_source.source`` in a track YAML, keeping its comments and layout."""
    text = track_yaml.read_text(encoding="utf-8")
    line = f"  source: {provider} # written by track/builder.py: provider of the last build"
    block = re.search(r"^geometry_source:\n((?:[ \t]+.*\n)*)", text, flags=re.MULTILINE)
    if block is None:
        raise ConfigError(f"{track_yaml}: no geometry_source block")
    body = block.group(1)
    if re.search(r"^[ \t]+source:.*$", body, flags=re.MULTILINE):
        body = re.sub(r"^[ \t]+source:.*$", line, body, count=1, flags=re.MULTILINE)
    else:
        body += line + "\n"
    new_text = text[: block.start(1)] + body + text[block.end(1) :]
    track_yaml.write_text(new_text, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    """Build one track model. Exit 0 OK, 1 invalid, 2 ``UNAVAILABLE`` (PF-01)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True, help="track_id, e.g. suzuka")
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default="auto",
        help="geometry provider; auto tries FastF1, then OpenF1 (default: auto)",
    )
    parser.add_argument(
        "--cache-only", action="store_true", help="download into the data cache and stop"
    )
    parser.add_argument("--laps", type=int, help="laps to pool (default: track_builder.pool_laps)")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
    except ConfigError as exc:
        logger.error("%s", exc)
        return EXIT_INVALID
    official_m = track.official_length_m
    if isinstance(official_m, str):
        logger.error("%s: official_length_m is %s; cannot validate", track.track_id, official_m)
        return EXIT_INVALID

    cfg = app.track_builder
    n_laps = args.laps if args.laps is not None else cfg.pool_laps
    try:
        laps, source = load_laps_xy(track, app, args.source, n_laps)
    except TrackUnavailableError as exc:
        logger.error("UNAVAILABLE: %s", exc)
        return EXIT_UNAVAILABLE
    if args.cache_only:
        logger.info(
            "%s: %s data cached (%d laps, %d position samples)",
            track.track_id,
            source["provider"],
            len(laps),
            sum(lap[0].size for lap in laps),
        )
        return EXIT_OK

    try:
        model, error = build_from_laps(laps, track, cfg)
        outline = track.geometry_source.outline
        if outline is not None and outline.corners:
            from pitwall_sim.track.outline import apply_outline  # noqa: PLC0415  (imports us)

            model, info = apply_outline(model, track, cfg, Path(app.paths.tracks))
            source = {**source, **info}
            logger.info(
                "%s: outline curvature at %s (alignment RMS %s m)",
                track.track_id, info["outline_corners"], info["outline_alignment_rms_m"],
            )  # fmt: skip
    except TrackValidationError as exc:
        logger.error("%s", exc)
        return EXIT_INVALID

    path = write_track_model(model, Path(app.paths.tracks), source)
    record_geometry_source(
        args.config_dir / "tracks" / f"{track.track_id}.yaml", source["provider"]
    )
    logger.info(
        "%s: measured %.0f m (%+.2f%% vs official %.0f m), scaled x%.4f to %.0f m, "
        "%d straights, %s lap %s s, source %s -> %s",
        track.track_id,
        model.measured_length_m,
        error * 100,
        official_m,
        model.scale_factor,
        model.length_m,
        len(model.straights),
        source.get("driver") or f"car {source.get('driver_number')}",
        source["lap_time_s"],
        source["provider"],
        path,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
