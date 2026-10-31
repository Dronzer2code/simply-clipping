"""T-040 / MVP-06: RNG streams, Snapshot save / restore / fork, state hash.

Short Suzuka races with a pit stop, so the overtake and pit RNG streams are
both drawn from. Coefficients come from config at test time.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

from pitwall_sim.config.models import Compound
from pitwall_sim.engineer.commands import CommandType, EngineerCommand
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.snapshot import fork, restore, save

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
LAPS = 3
FUEL_KG = 60.0
BOX_DRIVER = "HAM"


def _engine(seed: int = 42) -> RaceEngine:
    return RaceEngine(RaceSetup(laps=LAPS, seed=seed, fuel_kg=FUEL_KG), CONFIG_DIR)


def _run(engine: RaceEngine, until_s: float | None = None) -> RaceEngine:
    """Run with the same 'command': box one car on its first lap."""
    i = engine.driver_ids.index(BOX_DRIVER)
    while not engine.finished and (until_s is None or engine.t < until_s):
        if (
            engine.st.lap[i] == 1
            and engine.pit.phase[i].value == "RUNNING"
            and not engine.pit.events
        ):
            engine.box(i, Compound.HARD)
        engine.tick()
    return engine


def _lap_hashes(engine: RaceEngine) -> list[str]:
    return [snap.race_state.hash() for snap in engine.auto_snapshots]


# --------------------------------------------------------------------------- #
# Acceptance (MVP-06): test_determinism, test_snapshot_roundtrip
# --------------------------------------------------------------------------- #


def test_determinism() -> None:
    first, second = _run(_engine()), _run(_engine())
    assert first.finished and second.finished
    assert len(first.auto_snapshots) == LAPS  # one each time the leader completes a lap
    assert _lap_hashes(first) == _lap_hashes(second)  # identical at every lap
    assert first.race_state().hash() == second.race_state().hash()
    assert any(e.phase.value == "STATIONARY" for e in first.pit.events)
    other = _run(_engine(seed=43))
    assert other.race_state().hash() != first.race_state().hash()


def test_snapshot_roundtrip() -> None:
    original = _run(_engine(), until_s=150.0)
    snapshot = save(original)
    _run(original)
    resumed = _run(restore(snapshot))
    assert resumed.finished
    assert resumed.race_state().hash() == original.race_state().hash()
    assert resumed.result() == original.result()
    # The snapshot is reusable: a second restore ends the same way.
    again = _run(restore(snapshot))
    assert again.race_state().hash() == original.race_state().hash()
    # Lap snapshots taken after the save match too.
    after = [
        h
        for s, h in zip(original.auto_snapshots, _lap_hashes(original), strict=True)
        if s.t > snapshot.t
    ]
    assert _lap_hashes(resumed) == after


# --------------------------------------------------------------------------- #
# Snapshot contents and fork
# --------------------------------------------------------------------------- #


def test_snapshot_holds_rng_states_commands_and_shares_plans() -> None:
    engine = _engine()
    command = EngineerCommand("c1", 0.0, "UI", CommandType.PUSH_LAP, {}, 500.0)
    engine.submit(command)
    _run(engine, until_s=60.0)
    snap = save(engine)
    assert set(snap.rng_states) == set(engine.rngs)
    state = pickle.loads(snap.rng_states["overtake"])
    assert state == engine.rngs["overtake"].bit_generator.state
    assert snap.command_log == [command]
    assert snap.t == engine.t and snap.race_state.t_s == engine.t
    # Plans are shared, kernel state is copied.
    assert snap.engine_state["car_plans"][0] is engine.car_plans[0]
    assert snap.engine_state["st"].s_m is not engine.st.s_m
    assert np.array_equal(snap.engine_state["st"].s_m, engine.st.s_m)


def test_fork_queues_extra_commands_and_leaves_the_original_alone() -> None:
    engine = _run(_engine(), until_s=60.0)
    snap = save(engine)
    extra = EngineerCommand("c2", snap.t, "RADIO", CommandType.MANAGE_TYRES, {}, snap.t + 5.0)
    branch = fork(snap, [extra])
    assert branch.pending_commands == [extra]
    assert engine.pending_commands == []
    applied: list[str] = []
    branch.command_handler = lambda eng, cmd: applied.append(cmd.command_id)
    while branch.t < snap.t + 6.0:
        branch.tick()
    assert applied == ["c2"]
    assert engine.t == snap.t  # the source engine did not move
