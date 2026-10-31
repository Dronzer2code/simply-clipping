"""Record a headless race for the replay viewer (sprint S-2).

Runs one race and stores, every feed interval (4 Hz), each car's lap distance,
lap, speed, true battery, Radar Estimate and confidence, race position, gap to
the leader, tyre, pit and status flags and Energy Mode, plus the track centre
line, in ``<run>/replay.npz`` and ``<run>/meta.json``. A replay is a post-race
view: it holds Ground Truth next to the Radar Estimates, which the live pit wall
never shows outside Test mode.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR
from pitwall_sim.config.models import Compound, EnergyMode
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.pit import PitPhase

logger = logging.getLogger(__name__)

MJ = 1e6
COMPOUNDS = tuple(Compound)
MODES = tuple(EnergyMode)
STATUS = ("RUNNING", "PIT", "FINISHED", "DNF")
REPLAY_FILE, META_FILE = "replay.npz", "meta.json"


@dataclass
class Replay:
    """A recorded race: arrays are (ticks, cars) in grid order unless noted."""

    meta: dict[str, Any]
    t_s: npt.NDArray[np.float64]
    """(ticks,) sim time."""
    leader_lap: npt.NDArray[np.int16]
    """(ticks,) the leader's current lap (1-based)."""
    s_m: npt.NDArray[np.float32]
    lap: npt.NDArray[np.int16]
    v_kmh: npt.NDArray[np.float32]
    battery_mj: npt.NDArray[np.float32]
    radar_mj: npt.NDArray[np.float32]
    radar_conf: npt.NDArray[np.float32]
    position: npt.NDArray[np.int8]
    """1-based race position."""
    gap_s: npt.NDArray[np.float32]
    compound: npt.NDArray[np.int8]
    """Index into :data:`COMPOUNDS`."""
    in_pit: npt.NDArray[np.bool_]
    status: npt.NDArray[np.int8]
    """Index into :data:`STATUS`."""
    mode: npt.NDArray[np.int8]
    """Index into :data:`MODES`."""
    track_x: npt.NDArray[np.float64]
    """(points,) centre line."""
    track_y: npt.NDArray[np.float64]

    @property
    def n_cars(self) -> int:
        """Return the number of cars."""
        return int(self.s_m.shape[1])

    def xy(self, k: int) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Every car's map position at tick ``k``."""
        n = self.track_x.size
        idx = (self.s_m[k] / self.meta["length_m"] * n).astype(np.int64) % n
        return self.track_x[idx], self.track_y[idx]

    def save(self, run_dir: Path) -> None:
        """Write ``replay.npz`` and ``meta.json`` into ``run_dir``."""
        run_dir.mkdir(parents=True, exist_ok=True)
        arrays = {k: v for k, v in self.__dict__.items() if k != "meta"}
        np.savez_compressed(run_dir / REPLAY_FILE, **arrays)
        (run_dir / META_FILE).write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, run_dir: Path) -> Replay:
        """Read a recorded run."""
        meta = json.loads((run_dir / META_FILE).read_text(encoding="utf-8"))
        with np.load(run_dir / REPLAY_FILE) as data:
            arrays = {k: data[k] for k in data.files}
        return cls(meta=meta, **arrays)


def record(setup: RaceSetup, config_dir: Path = DEFAULT_CONFIG_DIR) -> Replay:
    """Run one race headless and record it."""
    engine = RaceEngine(setup, config_dir)
    n = engine.n
    rows: dict[str, list[npt.NDArray[Any]]] = {k: [] for k in (
        "s_m", "lap", "v_kmh", "battery_mj", "radar_mj", "radar_conf", "position", "gap_s",
        "compound", "in_pit", "status", "mode",
    )}  # fmt: skip
    times: list[float] = []
    leader: list[int] = []
    comp_index = {c: k for k, c in enumerate(COMPOUNDS)}
    mode_index = {m: k for k, m in enumerate(MODES)}
    status_index = {s: k for k, s in enumerate(STATUS)}
    start = time.perf_counter()
    while not engine.finished:
        engine.tick()
        st = engine.st
        energy, confidence = engine.radar.energies()
        position = np.empty(n, dtype=np.int8)
        position[engine._classification] = np.arange(1, n + 1)
        times.append(engine.t)
        leader.append(int(st.lap.max()) + 1)
        rows["s_m"].append(st.s_m.astype(np.float32))
        rows["lap"].append(st.lap.astype(np.int16))
        rows["v_kmh"].append((st.v_ms * 3.6).astype(np.float32))
        rows["battery_mj"].append((st.battery_j / MJ).astype(np.float32))
        rows["radar_mj"].append(np.where(confidence > 0.0, energy, np.nan).astype(np.float32))
        rows["radar_conf"].append(confidence.astype(np.float32))
        rows["position"].append(position)
        rows["gap_s"].append(engine.timing.gap_s.astype(np.float32))
        rows["compound"].append(np.array([comp_index[c] for c in engine.compounds], np.int8))
        rows["in_pit"].append(np.array([engine.pit.phase[i] != PitPhase.RUNNING
                                        for i in range(n)], dtype=np.bool_))  # fmt: skip
        rows["status"].append(np.array([status_index[s] for s in engine.status], np.int8))
        rows["mode"].append(np.array([mode_index[x.mode] for x in engine.instructions], np.int8))
    logger.info("recorded %d ticks in %.1f s", len(times), time.perf_counter() - start)
    grid = {d.driver_id: (t, d) for t in engine.grid.teams for d in t.drivers}
    meta = {
        "track_id": engine.track.track_id,
        "rule_set_id": engine.rules.rule_set_id,
        "seed": setup.seed,
        "laps": engine.laps,
        "length_m": engine.model.length_m,
        "drivers": [
            {"driver_id": d, "code": grid[d][1].code, "number": grid[d][1].number,
             "team_id": grid[d][0].team_id, "team": grid[d][0].display_name,
             "color": grid[d][0].color_hex if not str(grid[d][0].color_hex).startswith("UN")
             else "#8C8C8C"}
            for d in engine.driver_ids
        ],
        "compounds": [c.value for c in COMPOUNDS],
        "modes": [m.value for m in MODES],
        "status": list(STATUS),
        "retired": {engine.driver_ids[i]: why for i, why in engine.retired.items()},
    }  # fmt: skip
    return Replay(
        meta=meta,
        t_s=np.asarray(times),
        leader_lap=np.asarray(leader, dtype=np.int16),
        **{k: np.stack(v) for k, v in rows.items()},
        track_x=engine.model.x_m,
        track_y=engine.model.y_m,
    )
