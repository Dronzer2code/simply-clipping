"""Choose the curvature source per corner: OpenF1 line or public outline (T-02D).

For each corner of the track, the radius implied by the real minimum speed
(median over the calibration reference laps, each with its team's calibrated
grip, downforce and tyre load sensitivity: ``m v² = μ(N) N R``, ``N = m g +
½ ρ ClA v²``) is compared with the tightest radius of the OpenF1 centre line and
of the aligned outline inside the corner window. The source with the smaller
``|log(R_source / R_implied)|`` wins (owner round 15). A corner whose real
minimum is not grip-limited (taken flat, or set by the exit of the corner
before) only gives an upper bound on the radius it needs; both sources then
usually lie above it and the choice changes little.

Usage::

    python -m pitwall_sim.calibration.corner_sources --track suzuka          # table
    python -m pitwall_sim.calibration.corner_sources --track suzuka --write  # + yaml

``--write`` sets ``geometry_source.outline.corners`` in the track YAML; rebuild
the track model afterwards (``python -m pitwall_sim.track.builder``).
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pitwall_sim.calibration.compare import (
    ReferenceLap,
    load_team_references,
    quali_fuel_kg,
    rule_set_for_date,
)
from pitwall_sim.car.dynamics import load_factor
from pitwall_sim.car.speed_profile import ProfileParams, reference_params
from pitwall_sim.config.loader import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    load_app,
    load_grid,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import Compound
from pitwall_sim.track.builder import (
    TrackModel,
    TrackUnavailableError,
    TrackValidationError,
    build_from_laps,
    load_laps_xy,
)
from pitwall_sim.track.openf1 import OpenF1Client
from pitwall_sim.track.outline import corner_windows, outline_model

logger = logging.getLogger(__name__)

G_MS2 = 9.80665
EXIT_OK, EXIT_INVALID, EXIT_UNAVAILABLE = 0, 1, 2


@dataclass(frozen=True)
class CornerSource:
    """One corner's radii and the chosen curvature source."""

    corner_id: str
    v_real_kmh: float
    r_implied_m: float
    r_openf1_m: float
    r_outline_m: float

    @property
    def log_error_openf1(self) -> float:
        """``log(R_openf1 / R_implied)``."""
        return math.log(self.r_openf1_m / self.r_implied_m)

    @property
    def log_error_outline(self) -> float:
        """``log(R_outline / R_implied)``."""
        return math.log(self.r_outline_m / self.r_implied_m)

    @property
    def source(self) -> str:
        """``outline`` when its radius is closer to the implied one, else ``openf1``."""
        return "outline" if abs(self.log_error_outline) < abs(self.log_error_openf1) else "openf1"


def implied_radius_m(v_ms: float, p: ProfileParams) -> float:
    """Radius at which ``v_ms`` is the grip limit (corner downforce, load sensitivity)."""
    normal = p.mass_kg * G_MS2 + 0.5 * p.rho * p.aero.cla_corner * v_ms * v_ms
    mu = p.mu_lat * load_factor(normal, p.n_ref_n, p.k_load)
    return p.mass_kg * v_ms * v_ms / (mu * normal)


def choose_sources(
    model: TrackModel,
    k_outline: np.ndarray,
    windows: dict[str, tuple[float, float]],
    refs: dict[str, ReferenceLap],
    params: dict[str, ProfileParams],
) -> list[CornerSource]:
    """Per corner (track order): real minimum speed, implied and model radii."""
    length = model.length_m
    out = []
    for corner, (start, end) in sorted(windows.items(), key=lambda kv: kv[1][0] % length):
        in_model = (model.s_m - start) % length <= end - start
        implied, speeds = [], []
        for team, ref in refs.items():
            sel = (ref.s_m - start) % length <= end - start
            if sel.sum() < 2:
                continue
            v = float(ref.speed_kmh[sel].min()) / 3.6
            implied.append(implied_radius_m(v, params[team]))
            speeds.append(v * 3.6)
        if not implied:
            continue
        out.append(
            CornerSource(
                corner,
                float(np.median(speeds)),
                float(np.median(implied)),
                float(1.0 / np.abs(model.curvature_per_m[in_model]).max()),
                float(1.0 / np.abs(k_outline[in_model]).max()),
            )
        )
    return out


def write_corners(track_yaml: Path, corners: list[str]) -> None:
    """Set ``geometry_source.outline.corners`` in a track YAML, keeping its layout."""
    text = track_yaml.read_text(encoding="utf-8")
    new, n = re.subn(
        r"^(  outline:\n(?:    .*\n|  #.*\n)*?    corners:).*$",
        lambda m: f"{m.group(1)} [{', '.join(corners)}]",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise ConfigError(f"{track_yaml}: no geometry_source.outline.corners line")
    track_yaml.write_text(new, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Print the per-corner table; with ``--write`` record the outline corners."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True)
    parser.add_argument("--write", action="store_true", help="write the corners to the YAML")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
        cfg = app.track_builder
        provider = track.geometry_source.source or "auto"
        laps, _ = load_laps_xy(track, app, provider, cfg.pool_laps)
        model, _ = build_from_laps(laps, track, cfg)  # the OpenF1 line alone
        k_outline, rms_m = outline_model(model, track, cfg, Path(app.paths.tracks))
        client = OpenF1Client(app.openf1, Path(app.paths.openf1_cache))
        refs = load_team_references(
            track, model, client, load_grid("real_2026", args.config_dir),
            app.calibration.min_section_coverage, app.calibration.coverage_section_m,
        )  # fmt: skip
        rules = rule_set_for_date(next(iter(refs.values())).session_date, args.config_dir)
        perf, tyres = load_team_performance(args.config_dir), load_tyres(args.config_dir)
        params = {
            team: reference_params(
                rules, perf.teams[team], tyres, Compound.SOFT, app, track, quali_fuel_kg(track)
            )
            for team in refs
        }
    except (ConfigError, TrackValidationError) as exc:
        logger.error("%s", exc)
        return EXIT_INVALID
    except TrackUnavailableError as exc:
        logger.error("UNAVAILABLE: %s", exc)
        return EXIT_UNAVAILABLE

    windows = corner_windows(track, model.length_m, cfg.outline_window_max_m)
    rows = choose_sources(model, k_outline, windows, refs, params)
    print(f"{track.track_id}: outline alignment RMS {rms_m:.2f} m; {len(refs)} reference laps")
    print("corner  v_real km/h  R_implied  R_openf1  R_outline  log err openf1 / outline  source")
    for r in rows:
        print(
            f"{r.corner_id:6s} {r.v_real_kmh:11.0f} {r.r_implied_m:9.0f} {r.r_openf1_m:9.0f} "
            f"{r.r_outline_m:10.0f}   {r.log_error_openf1:+15.2f} / {r.log_error_outline:+.2f}"
            f"   {r.source}"
        )
    chosen = [r.corner_id for r in rows if r.source == "outline"]
    print(f"outline corners: {chosen}")
    if args.write:
        write_corners(args.config_dir / "tracks" / f"{track.track_id}.yaml", chosen)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
