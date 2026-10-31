"""F09 Snapshot, RNG streams and determinism (T-040).

HR-04: every random draw in the simulation comes from one of the named streams
below, all derived from the race seed. Each stream is independent, so adding
draws to one (e.g. more overtakes) never shifts another (e.g. weather).

A :class:`Snapshot` (TRD SNAPSHOT AND DETERMINISM) holds the race at one moment:
the public ``RaceState``, every RNG stream's state, the command log, and the
engine's internal state (kernel arrays, timing, pit, overtakes, drivers). Config,
the track model and the drivers' plans are shared, never copied: they do not
change during a race. ``restore`` gives an engine that continues exactly as the
original would have; ``fork`` does the same with extra commands queued
(Strategy Predictor, debrief). The engine takes one automatically each time the
leader crosses the timing line (PF-04).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from pitwall_sim.engineer.commands import EngineerCommand
from pitwall_sim.race.state import RaceState

if TYPE_CHECKING:
    from pitwall_sim.race.engine import RaceEngine

#: The named RNG streams (HR-04), in a fixed order: the order fixes each seed.
RNG_STREAMS = (
    "overtake",
    "mistakes",
    "events",
    "weather",
    "pit",
    "feed_noise",
    "rival_strategy",
    "predictor",
)


def make_rngs(seed: int) -> dict[str, np.random.Generator]:
    """One independent ``numpy`` Generator per named stream, from the race seed."""
    children = np.random.SeedSequence(seed).spawn(len(RNG_STREAMS))
    return {
        name: np.random.Generator(np.random.PCG64(child))
        for name, child in zip(RNG_STREAMS, children, strict=True)
    }


def rng_states(rngs: dict[str, np.random.Generator]) -> dict[str, bytes]:
    """Each stream's bit-generator state, pickled (TRD ``rng_states``)."""
    return {name: pickle.dumps(gen.bit_generator.state) for name, gen in rngs.items()}


@dataclass(frozen=True)
class Snapshot:
    """The race at time ``t`` (TRD SNAPSHOT AND DETERMINISM)."""

    t: float
    race_state: RaceState
    rng_states: dict[str, bytes]
    command_log: list[EngineerCommand]
    """Commands applied so far, then the ones still queued."""
    engine_state: dict[str, Any] = field(repr=False)
    """Internal engine state (private to ``RaceEngine``)."""
    shared: dict[str, Any] = field(repr=False)
    """Config, track and plan objects shared with the source engine."""


def save(engine: RaceEngine) -> Snapshot:
    """Snapshot ``engine`` now."""
    return engine.snapshot()


def restore(snapshot: Snapshot) -> RaceEngine:
    """Build a new engine in the snapshot's state; the snapshot stays reusable."""
    from pitwall_sim.race.engine import RaceEngine  # noqa: PLC0415  (engine imports this module)

    return RaceEngine.from_snapshot(snapshot)


def fork(snapshot: Snapshot, commands: list[EngineerCommand]) -> RaceEngine:
    """Restore the snapshot and queue ``commands`` on top of its own."""
    engine = restore(snapshot)
    for command in commands:
        engine.submit(command)
    return engine
