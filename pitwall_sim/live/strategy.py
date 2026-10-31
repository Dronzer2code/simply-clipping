"""Strategy panel (hackathon H5, light PF-15): pit plans forked from public knowledge only.

Plans: STAY_OUT, BOX_NOW, BOX_+1 .. BOX_+3 laps, each box plan with every
available dry compound. Each plan runs ``N_FORKS`` paired forks (overtake,
mistakes, pit, rival_strategy and events streams reseeded identically per fork
index across plans) for ``HORIZON_LAPS`` of Our Car; the result is Our Car's mean
position at the horizon and its undercut (> 0) / overcut (< 0) gain on the car
ahead against STAY_OUT, in seconds.

Information barrier (HR-03): the forks never start from the true race. Before any
fork, :func:`public_snapshot` replaces every Rival's hidden state with what the pit
wall can know: battery = its Radar Estimate; tyre wear = its public tyre age x
Our Car's own wear rate scaled by the compound (tyres.yaml); fuel = Our Car's;
Energy Mode BALANCED, no ATTACK / DEFEND / HOLD; plan = the public prior (one stop
at ``stop_fraction["BALANCED"]`` of the race unless the public timing shows the
stop made). Our Car keeps its own exact state.

The work runs in a separate low-priority process (:class:`StrategyWorker`), so the
race and the UI never wait for it (the Numba kernel holds the GIL in-process).
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from pitwall_sim.config.models import Compound, EnergyMode
from pitwall_sim.engineer.records import PitPlan, StrategyResult
from pitwall_sim.observe.engineer_view import EngineerView
from pitwall_sim.race.engine import RaceEngine
from pitwall_sim.race.snapshot import Snapshot

logger = logging.getLogger(__name__)
N_FORKS = 4
HORIZON_LAPS = 6  # the scope's fallback (8 laps: ~30 s per refresh on the 8 GB laptop)
BOX_PLANS: tuple[tuple[PitPlan, int], ...] = (("BOX_NOW", 0), ("BOX_+1", 1), ("BOX_+2", 2),
                                              ("BOX_+3", 3))  # fmt: skip
DRY = (Compound.SOFT, Compound.MEDIUM, Compound.HARD)
WET_SET = (Compound.MEDIUM, Compound.INTERMEDIATE, Compound.WET)
"""Compounds the panel tries on a wet track (E1)."""
WET_TRACK = 0.1
"""Track wetness from which the panel offers the wet compounds (STRUCTURAL, E1)."""
MJ = 1e6
RESEEDED = ("overtake", "mistakes", "pit", "rival_strategy", "events")


@dataclass(frozen=True)
class PublicInfo:
    """What the pit wall knows about the Rivals (from the EngineerView)."""

    radar_mj: dict[str, float]
    tyre_age_laps: dict[str, int]
    pit_stops: dict[str, int]

    @classmethod
    def from_view(cls, view: EngineerView) -> PublicInfo:
        """Radar Estimates and public tyre / stop data."""
        return cls({d: e.energy_mj for d, e in view.radar.items()},
                   dict(view.timing.tyre_age_laps), dict(view.timing.pit_stops))  # fmt: skip


def public_snapshot(snap: Snapshot, our: str, info: PublicInfo) -> Snapshot:
    """Return the race as the pit wall knows it: every Rival's hidden state replaced (HR-03)."""
    engine = RaceEngine.from_snapshot(snap)
    st, book = engine.st, engine.rival_book
    o = engine.driver_ids.index(our)
    our_age = max(int(engine.tyre_laps[o]), 1)
    our_rate = float(st.tyre_wear[o]) / our_age  # wear per lap, Our Car's own tyre model
    k_wear = {c: float(engine.tyres.compounds[c].k_wear) for c in engine.tyres.compounds}
    our_k = k_wear.get(engine.compounds[o], 1.0) or 1.0
    fraction = engine.app.rival_strategy.stop_fraction["BALANCED"]
    prior_stop = max(1, round(fraction * engine.laps))
    for i, d in enumerate(engine.driver_ids):
        if d == our or not st.running[i]:
            continue
        st.battery_j[i] = info.radar_mj.get(d, 2.0) * MJ
        engine.timing.lap_battery_j[i] = st.battery_j[i]
        st.harvest_lap_j[i] = 0.0
        st.deploy_lap_j[i] = 0.0
        age = info.tyre_age_laps.get(d, 0)
        compound = engine.compounds[i]
        st.tyre_wear[i] = min(our_rate * age * k_wear.get(compound, 1.0) / our_k, 0.95)
        st.fuel_kg[i] = st.fuel_kg[o]
        engine.set_instructions(i, replace(
            engine.instructions[i], mode=EnergyMode.BALANCED, attack=False, defend=False,
            hold_position=False,
        ))  # fmt: skip
    for k, i in enumerate(book.index.tolist()):
        stops = info.pit_stops.get(engine.driver_ids[i], 0)
        book.stops_done[k] = stops
        book.stop_lap[k] = prior_stop
        book.harvesting[k] = False
        book.wet_delay_laps[k] = 0  # public prior: boxes at the wet crossover (E1, HR-03)
        book.wet_due_lap[k] = -1
    for i, d in enumerate(engine.driver_ids):
        if d != our and st.running[i]:
            engine._set_plan(i, engine._plan_car(i))
    return engine.snapshot()


def plans_for(engine: RaceEngine) -> list[tuple[PitPlan, Compound | None]]:
    """STAY_OUT, then every box timing with every available dry compound.

    On a wet track (rain falling or the track not yet dry: public, E1) the
    compounds are MEDIUM, INTERMEDIATE and WET instead, so the panel stays at 13 plans.
    """
    ctx = engine.command_context()
    wet = engine.weather.condition != "DRY" or engine.weather.track_wetness >= WET_TRACK
    compounds = [c for c in (WET_SET if wet else DRY) if c in ctx.compounds]
    out: list[tuple[PitPlan, Compound | None]] = [("STAY_OUT", None)]
    return out + [(plan, c) for plan, _ in BOX_PLANS for c in compounds]


def _run(public: Snapshot, our: str, plan: PitPlan, compound: Compound | None, k: int,
         seed_key: int) -> tuple[int, float, float, str | None, float]:  # fmt: skip
    """One fork: (position, our progress m, car-ahead progress m, car ahead, our speed m/s).

    The speed is measured over the fork itself, so it is right for a race picked up
    mid-way too (E3: progress counts the real laps, race time starts at 0).
    """
    fork = RaceEngine.from_snapshot(public)
    for n, name in enumerate(RESEEDED):  # paired across plans (analysis fork only)
        fork.rngs[name] = np.random.default_rng([seed_key, k, n])
    fork.overtake.rng = fork.rngs["overtake"]
    i = fork.driver_ids.index(our)
    order = [fork.driver_ids[int(j)] for j in fork._classification]
    k_our = order.index(our)
    ahead = order[k_our - 1] if k_our > 0 else None
    a = fork.driver_ids.index(ahead) if ahead else None
    start_lap = int(fork.st.lap[i])
    t0 = fork.t
    m0 = float(fork._progress_m()[i])
    box_at = None if plan == "STAY_OUT" else start_lap + dict(BOX_PLANS)[plan]
    end_lap = min(start_lap + HORIZON_LAPS, fork.laps)
    while not fork.finished and int(fork.st.lap[i]) < end_lap and fork.status[i] != "DNF":
        if box_at is not None and int(fork.st.lap[i]) >= box_at and compound is not None:
            fork.box(i, compound)
            box_at = None
        fork.tick()
    length = fork.trk.length_m
    prog = fork._progress_m() if hasattr(fork, "_progress_m") else None
    our_m = float(prog[i]) if prog is not None else float(fork.st.lap[i]) * length
    ahead_m = float(prog[a]) if (prog is not None and a is not None) else float("nan")
    rank = [fork.driver_ids[int(j)] for j in fork._classification].index(our) + 1
    speed = (our_m - m0) / max(fork.t - t0, 1.0)
    return rank, our_m, ahead_m, ahead, speed


Runs = dict[tuple[PitPlan, Compound | None], list[tuple[int, float, float, str | None, float]]]


def run_plan(public: Snapshot, our: str, plan: PitPlan, compound: Compound | None,
             forks: int) -> list[tuple[int, float, float, str | None, float]]:  # fmt: skip
    """All forks of one plan (paired with every other plan by fork index)."""
    seed_key = int(public.race_state.hash()[:8], 16)
    return [_run(public, our, plan, compound, k, seed_key) for k in range(forks)]


def summarise(runs: Runs, race_t_s: float, forks: int) -> tuple[StrategyResult, ...]:
    """Mean position per plan and the gain on the car ahead against STAY_OUT, seconds."""
    stay = runs[("STAY_OUT", None)]
    speed = max(float(np.mean([r[4] for r in stay])), 1.0)  # our m per race s in the forks
    out = []
    for (plan, compound), rows in runs.items():
        gaps = [(r[1] - r[2]) - (s[1] - s[2]) for r, s in zip(rows, stay, strict=True)
                if np.isfinite(r[2]) and np.isfinite(s[2])]  # fmt: skip
        gain = float(np.mean(gaps)) / speed if gaps and plan != "STAY_OUT" else None
        position = float(np.mean([r[0] for r in rows]))
        tyre = compound.value if compound else None
        out.append(StrategyResult(plan, tyre, position, gain, rows[0][3], forks))
    return tuple(out)


def evaluate(
    snap: Snapshot,
    our: str,
    info: PublicInfo,
    plans: list[tuple[PitPlan, Compound | None]],
    forks: int = N_FORKS,
) -> tuple[StrategyResult, ...]:
    """Every plan from the public race (synchronous; the worker does the same in parallel)."""
    public = public_snapshot(snap, our, info)
    runs = {(p, c): run_plan(public, our, p, c, forks) for p, c in plans}
    return summarise(runs, public.t, forks)


def _low_priority() -> None:
    """Worker process: below-normal priority, so the race keeps the CPU."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    else:  # pragma: no cover
        import os

        os.nice(10)
    logging.disable(logging.WARNING)


def _warm() -> None:
    """Worker process: import the simulator once (its first refresh is then quicker)."""
    from pitwall_sim.race import engine  # noqa: F401, PLC0415


class StrategyWorker:
    """Background processes (``workers``); one refresh at a time; the latest result is kept.

    A refresh: one process makes the public snapshot (:func:`public_snapshot`, the
    barrier), then the plans run in parallel; :meth:`poll` collects them.
    """

    def __init__(self, workers: int = 3, forks: int = N_FORKS) -> None:
        """Start the pool lazily (the first refresh)."""
        self.workers, self.forks = workers, forks
        self._pool: ProcessPoolExecutor | None = None
        self._public: Future[Snapshot] | None = None
        self._plans: dict[tuple[PitPlan, Compound | None], Future[list[Any]]] = {}
        self._job: tuple[str, list[tuple[PitPlan, Compound | None]], int, float] | None = None
        self.result: tuple[StrategyResult, ...] | None = None
        self.result_lap: int | None = None

    @property
    def busy(self) -> bool:
        """A refresh is running."""
        return self._job is not None

    def submit(self, snap: Snapshot, our: str, info: PublicInfo,
               plans: list[tuple[PitPlan, Compound | None]], lap: int) -> bool:  # fmt: skip
        """Start a refresh unless one is running; return whether it started."""
        if self.busy:
            return False
        try:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self.workers, initializer=_low_priority
                )
            self._public = self._pool.submit(public_snapshot, snap, our, info)
        except Exception:  # noqa: BLE001 (a broken pool never stops the race)
            logger.exception("strategy worker unavailable")
            self.close()
            return False
        self._job = (our, plans, lap, snap.t)
        return True

    def poll(self) -> bool:
        """Advance the refresh; return whether a new result arrived."""
        if self._job is None or self._pool is None:
            return False
        our, plans, lap, race_t = self._job
        try:
            if self._public is not None:
                if not self._public.done():
                    return False
                public = self._public.result()
                self._public = None
                self._plans = {(p, c): self._pool.submit(run_plan, public, our, p, c, self.forks)
                               for p, c in plans}  # fmt: skip
                return False
            if not all(f.done() for f in self._plans.values()):
                return False
            runs = {key: f.result() for key, f in self._plans.items()}
        except Exception:  # noqa: BLE001 (the panel keeps the last good result)
            logger.exception("strategy refresh failed")
            self._reset()
            self.close()  # a fresh pool for the next refresh
            return False
        self._reset()
        self.result = summarise(runs, race_t, self.forks)
        self.result_lap = lap
        return True

    def start(self) -> None:
        """Start the processes now (and load the simulator in them), before the race runs.

        Started lazily, the pool would spawn its processes inside the first refresh,
        on the race thread.
        """
        try:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self.workers, initializer=_low_priority
                )
            for _ in range(self.workers):
                self._pool.submit(_warm)
        except Exception:  # noqa: BLE001 (a broken pool never stops the race)
            logger.exception("strategy worker unavailable")
            self.close()

    def _reset(self) -> None:
        self._job = None
        self._public = None
        self._plans = {}

    def close(self) -> None:
        """Stop the processes."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
