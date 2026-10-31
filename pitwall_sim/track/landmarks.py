"""Track landmarks for ``config/tracks/<track_id>.yaml`` (T-011, T-401).

Places corners and pit entry/exit on a built track model (``s`` along the
centre line), so the manual track config starts from reproducible numbers:

- corners: MultiViewer circuit data (the source FastF1's ``get_circuit_info``
  uses), projected onto the centre line;
- pit entry/exit: where real cars on their pit-stop laps leave and rejoin the
  centre line, from OpenF1 race ``/pit`` + ``/location`` (median over stops);
- timing sector boundaries (T-033): where the fastest qualifying laps are at
  the end of their official sector 1 and sector 2 times, from OpenF1 ``/laps``
  (``duration_sector_*``) + ``/location`` (median over laps).

Positions in both sources share the F1 live-timing frame (1/10 m). The built
model may be scaled to ``official_length_m`` about its centroid, so points are
mapped through the same scaling before projection.

Usage::

    python -m pitwall_sim.track.landmarks --track suzuka

Prints a YAML fragment with sources; it does not edit the config.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, ConfigError, load_app, load_track
from pitwall_sim.track.builder import TrackModel, project_path_to_s, read_track_model
from pitwall_sim.track.openf1 import (
    OPENF1_POS_UNIT_M,
    OpenF1Client,
    OpenF1Error,
    find_session,
    lap_samples,
    openf1_time,
)

logger = logging.getLogger(__name__)

#: A position sample farther than this from the centre line is off the track.
PIT_OFFSET_M = 8.0

#: Location window around an OpenF1 ``/pit`` timestamp that covers entry and exit.
PIT_WINDOW_S = 45.0


class LandmarkError(Exception):
    """A landmark source has no usable data."""


def project_to_s(model: TrackModel, x_m: float, y_m: float) -> tuple[float, float]:
    """Nearest centre-line ``s`` for a raw (unscaled) point; returns ``(s_m, offset_m)``."""
    cx, cy = float(np.mean(model.x_m)), float(np.mean(model.y_m))
    qx = cx + model.scale_factor * (x_m - cx)
    qy = cy + model.scale_factor * (y_m - cy)
    dist = np.hypot(model.x_m - qx, model.y_m - qy)
    i = int(np.argmin(dist))
    return float(model.s_m[i]), float(dist[i])


def pit_crossings(
    model: TrackModel, x_m: Sequence[float], y_m: Sequence[float]
) -> tuple[float, float] | None:
    """``(entry_s, exit_s)`` where one time-ordered trace leaves and rejoins the track."""
    offsets = []
    s_values = []
    for x, y in zip(x_m, y_m, strict=True):
        s, offset = project_to_s(model, x, y)
        s_values.append(s)
        offsets.append(offset)
    off_track = np.flatnonzero(np.asarray(offsets) > PIT_OFFSET_M)
    if off_track.size == 0 or off_track[0] == 0 or off_track[-1] == len(offsets) - 1:
        return None  # never left the track, or the window misses the entry or exit
    return s_values[off_track[0]], s_values[off_track[-1] + 1]


def _get_json(url: str, cache_path: Path, timeout_s: float) -> Any:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    logger.info("GET %s", url)
    request = urllib.request.Request(url, headers={"User-Agent": "pitwall_sim track landmarks"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LandmarkError(f"request failed for {url}: {exc}") from exc
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def multiviewer_corners(
    model: TrackModel, circuit: dict[str, Any]
) -> list[tuple[int, float, float]]:
    """Project each corner of a MultiViewer circuit document: ``(number, s_m, offset_m)``."""
    corners = []
    for corner in circuit.get("corners", []):
        pos = corner["trackPosition"]
        s, offset = project_to_s(model, pos["x"] * OPENF1_POS_UNIT_M, pos["y"] * OPENF1_POS_UNIT_M)
        corners.append((int(corner["number"]), s, offset))
    return sorted(corners, key=lambda c: c[0])


def pit_entry_exit(
    model: TrackModel, client: OpenF1Client, race_session_key: str, max_stops: int = 6
) -> tuple[float, float, int]:
    """Median pit entry and exit ``s`` over up to ``max_stops`` race pit stops."""
    stops = client.get("pit", [("session_key=", race_session_key)])
    entries, exits = [], []
    for stop in stops[:max_stops]:
        t = datetime.fromisoformat(str(stop["date"]))
        rows = client.get(
            "location",
            [
                ("session_key=", race_session_key),
                ("driver_number=", str(stop["driver_number"])),
                ("date>=", openf1_time(t - timedelta(seconds=PIT_WINDOW_S))),
                ("date<=", openf1_time(t + timedelta(seconds=PIT_WINDOW_S))),
            ],
        )
        rows.sort(key=lambda row: str(row["date"]))
        crossing = pit_crossings(
            model,
            [row["x"] * OPENF1_POS_UNIT_M for row in rows],
            [row["y"] * OPENF1_POS_UNIT_M for row in rows],
        )
        if crossing is not None:
            entries.append(crossing[0])
            exits.append(crossing[1])
    if not entries:
        raise LandmarkError(f"no usable pit-stop traces in OpenF1 session {race_session_key}")
    return float(np.median(entries)), float(np.median(exits)), len(entries)


def sector_boundaries(
    model: TrackModel, client: OpenF1Client, session_key: str, max_laps: int = 5
) -> tuple[float, float, int]:
    """Median ``s`` of the sector 1 / 2 ends over the fastest laps (one per driver).

    Each lap's location samples are placed on the centre line with the
    path-continuous projection and read at ``date_start + duration_sector_1``
    and ``+ duration_sector_2``.
    """
    best: dict[int, dict[str, Any]] = {}
    for lap in client.get("laps", [("session_key=", session_key)]):
        timed = lap.get("lap_duration") and lap.get("date_start") and not lap.get("is_pit_out_lap")
        if not (timed and lap.get("duration_sector_1") and lap.get("duration_sector_2")):
            continue
        number = int(lap["driver_number"])
        if number not in best or float(lap["lap_duration"]) < float(best[number]["lap_duration"]):
            best[number] = lap
    ends: list[tuple[float, float]] = []
    for lap in sorted(best.values(), key=lambda lap: float(lap["lap_duration"]))[:max_laps]:
        rows = lap_samples(client, session_key, lap, "location")
        if len(rows) < 2:
            continue
        start = datetime.fromisoformat(str(lap["date_start"])).timestamp()
        t = np.array([datetime.fromisoformat(str(r["date"])).timestamp() - start for r in rows])
        s = project_path_to_s(
            model,
            [r["x"] * OPENF1_POS_UNIT_M for r in rows],
            [r["y"] * OPENF1_POS_UNIT_M for r in rows],
        )
        # Unwrap so s rises through the lap; samples just before the line sit near L.
        s = np.unwrap(s, period=model.length_m)
        if s[0] > 0.5 * model.length_m:
            s -= model.length_m
        d1 = float(lap["duration_sector_1"])
        d2 = d1 + float(lap["duration_sector_2"])
        ends.append(
            (
                float(np.interp(d1, t, s)) % model.length_m,
                float(np.interp(d2, t, s)) % model.length_m,
            )
        )
    if not ends:
        raise LandmarkError(f"no laps with sector times in OpenF1 session {session_key}")
    arr = np.array(ends)
    return float(np.median(arr[:, 0])), float(np.median(arr[:, 1])), len(ends)


def main(argv: Sequence[str] | None = None) -> int:
    """Print corner and pit landmarks for one built track as a YAML fragment."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", required=True, help="track_id, e.g. suzuka")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        app = load_app(args.config_dir)
        track = load_track(args.track, args.config_dir)
        model = read_track_model(Path(app.paths.tracks) / f"{track.track_id}.parquet")
    except (ConfigError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return 1

    client = OpenF1Client(app.openf1, Path(app.paths.openf1_cache))
    race_track = track.model_copy(
        update={"geometry_source": track.geometry_source.model_copy(update={"session": "R"})}
    )
    try:
        race = find_session(race_track, client)
        circuit = _get_json(
            f"{app.multiviewer.base_url}/circuits/{race['circuit_key']}/{race['year']}",
            Path(app.paths.multiviewer_cache)
            / f"circuit_{race['circuit_key']}_{race['year']}.json",
            app.openf1.timeout_s,
        )
        corners = multiviewer_corners(model, circuit)
        entry_s, exit_s, n_stops = pit_entry_exit(model, client, str(race["session_key"]))
        quali = find_session(track, client)
        sector1_s, sector2_s, n_laps = sector_boundaries(model, client, str(quali["session_key"]))
    except (OpenF1Error, LandmarkError) as exc:
        logger.error("%s", exc)
        return 2

    print(
        f"# corners: MultiViewer circuit {race['circuit_key']} (layout year "
        f"{circuit.get('year')}), projected onto data/tracks/{track.track_id}.parquet"
    )
    print("corners:")
    for number, s, offset in corners:
        print(
            f'  - {{corner_id: "T{number}", s_m: {s:.0f}, name: "Turn {number}"}}'
            f"  # {offset:.1f} m off centre line"
        )
    print(
        f"# pit: median over {n_stops} OpenF1 race pit stops (session {race['session_key']}),"
        f" off track = > {PIT_OFFSET_M:.0f} m from the centre line"
    )
    print(f"pit: {{entry_s_m: {entry_s:.0f}, exit_s_m: {exit_s:.0f}}}")
    print(
        f"# sectors: median over the {n_laps} fastest laps (one per driver) of OpenF1 session"
        f" {quali['session_key']}, official sector times on the centre line"
    )
    print(f"sector_ends_m: [{sector1_s:.0f}, {sector2_s:.0f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
