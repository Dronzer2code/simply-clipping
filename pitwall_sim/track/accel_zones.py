"""Acceleration zones derived from the speed profile (T-027; TRD OPEN ITEMS, Powertrain).

Post-Miami MGU-K zones (350 kW, 250 kW elsewhere) for tracks without
FIA-published zones: every stretch from a corner exit (a speed minimum) to the
next braking point (the following speed maximum) that is at least
``acceleration_zones.min_length_m`` long. Minima and maxima are the turning
points of the reference speed profile that differ from their neighbours by at
least ``min_speed_change_kmh`` (small dips on a straight do not split it). The
profile is built with 350 kW everywhere, so the zones do not depend on
themselves. FIA-published zones (``acceleration_zones_source: fia``) always win.

Usage::

    python -m pitwall_sim.track.accel_zones --track suzuka   # derived vs current tags
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from pitwall_sim.car.speed_profile import reference_params, speed_profile
from pitwall_sim.config.loader import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    load_app,
    load_rule_set,
    load_team_performance,
    load_track,
    load_tyres,
)
from pitwall_sim.config.models import AccelerationZonesConfig, Compound, TrackConfig
from pitwall_sim.track.builder import read_track_model
from pitwall_sim.track.zones import zone_mask

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]

EXIT_OK, EXIT_INVALID = 0, 1


@dataclass(frozen=True)
class DerivedZone:
    """One derived acceleration zone; ``end_m < start_m`` when it crosses s = 0."""

    start_m: float
    end_m: float
    length_m: float
    exit_kmh: float
    """Speed at the corner exit (the zone start)."""
    braking_kmh: float
    """Speed at the braking point (the zone end)."""


def turning_points(v: FloatArray, threshold: float) -> list[tuple[int, bool]]:
    """``(index, is_max)`` of a closed profile's turns of at least ``threshold``, in order.

    A zig-zag filter starting at the global maximum: a minimum counts once the
    speed has risen ``threshold`` above it, a maximum once it has fallen as much.
    """
    n = v.size
    start = int(np.argmax(v))
    turns = [(start, True)]
    rising, ext = False, start
    for step in range(1, n + 1):
        i = (start + step) % n
        if rising:
            if v[i] > v[ext]:
                ext = i
            elif v[ext] - v[i] >= threshold:
                turns.append((ext, True))
                rising, ext = False, i
        elif v[i] < v[ext]:
            ext = i
        elif v[i] - v[ext] >= threshold:
            turns.append((ext, False))
            rising, ext = True, i
    if turns[-1][0] == start:  # back at the start maximum
        turns.pop()
    return turns


def derive_zones(
    s_m: FloatArray, v_kmh: FloatArray, length_m: float, cfg: AccelerationZonesConfig
) -> list[DerivedZone]:
    """Corner exit -> next braking point stretches of at least ``min_length_m``."""
    turns = turning_points(v_kmh, cfg.min_speed_change_kmh)
    zones = []
    for (i, i_max), (j, j_max) in zip(turns, turns[1:] + turns[:1], strict=True):
        if i_max or not j_max:
            continue
        length = float((s_m[j] - s_m[i]) % length_m)
        if length >= cfg.min_length_m:
            zones.append(
                DerivedZone(float(s_m[i]), float(s_m[j]), length, float(v_kmh[i]), float(v_kmh[j]))
            )
    return sorted(zones, key=lambda z: z.start_m)


def reference_speed_kmh(
    track: TrackConfig, config_dir: Path = DEFAULT_CONFIG_DIR
) -> tuple[FloatArray, FloatArray, float]:
    """``(s_m, v_kmh, length_m)``: a neutral car's race-trim profile, 350 kW everywhere."""
    app = load_app(config_dir)
    model = read_track_model(Path(app.paths.tracks) / f"{track.track_id}.parquet")
    perf = load_team_performance(config_dir)
    team = perf.teams[sorted(perf.teams)[0]]
    fuel = track.fuel_start_kg if isinstance(track.fuel_start_kg, int | float) else 0.0
    p = reference_params(
        load_rule_set(app.acceleration_zones.reference_rule_set, config_dir), team,
        load_tyres(config_dir), Compound.MEDIUM, app, track, float(fuel),
    )  # fmt: skip
    straight = zone_mask(track, model.s_m, tag="straight_mode_allowed")
    everywhere = np.ones(model.s_m.size, dtype=np.bool_)
    prof = speed_profile(model.s_m, model.curvature_per_m, straight, everywhere, model.length_m, p)
    return model.s_m, prof.v_ref_ms * 3.6, model.length_m


def main(argv: Sequence[str] | None = None) -> int:
    """Print the derived zones next to the track's current acceleration-zone tags."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
        s, v, length = reference_speed_kmh(track, args.config_dir)
    except (ConfigError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return EXIT_INVALID
    if track.acceleration_zones_source == "fia":
        print(f"{track.track_id}: FIA-published acceleration zones; nothing derived")
        return EXIT_OK
    derived = derive_zones(s, v, length, app.acceleration_zones)
    current = [z for z in track.zones if "acceleration_zone" in z.tags]
    covered = float(np.count_nonzero(zone_mask(track, s, tag="acceleration_zone")))
    print(f"{track.track_id}: derived acceleration zones (source now "
          f"{track.acceleration_zones_source}):")  # fmt: skip
    for k, z in enumerate(derived, start=1):
        print(f"  AZ{k}: {z.start_m:6.0f} -> {z.end_m:6.0f} m  ({z.length_m:4.0f} m, "
              f"{z.exit_kmh:3.0f} -> {z.braking_kmh:3.0f} km/h)")  # fmt: skip
    print(f"  total {sum(z.length_m for z in derived):.0f} m of {length:.0f} m")
    print("current tags:")
    for tag in current:
        print(f"  {tag.zone_id}: {tag.s_start_m:6.0f} -> {tag.s_end_m:6.0f} m")
    print(f"  total {covered * length / s.size:.0f} m")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
