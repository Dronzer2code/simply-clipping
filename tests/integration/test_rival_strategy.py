"""T-041: Rival Strategy AI in the race (MVP-10, HR-03)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.models import Compound
from pitwall_sim.driver.ai_driver import DriverInstructions
from pitwall_sim.observe.radar.energy import _ENERGY
from pitwall_sim.race import rival_strategy as RS
from pitwall_sim.race.engine import RaceEngine, RaceSetup

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
FULL_RACE_FUEL_KG = 110.0  # see test_race_engine.py (T-02B calibrates fuel)
MJ = 1e6


class _Recorder(RaceEngine):
    """Race engine that logs every Energy Mode change."""

    mode_changes: list[tuple[int, str, str]]
    start_compounds: list[Compound]

    def set_instructions(self, i: int, instructions: DriverInstructions) -> None:
        old = self.instructions[i].mode
        if instructions.mode != old:
            self.__dict__.setdefault("mode_changes", []).append((i, old, instructions.mode))
        super().set_instructions(i, instructions)


@pytest.fixture(scope="module")
def race() -> _Recorder:
    engine = _Recorder(RaceSetup(fuel_kg=FULL_RACE_FUEL_KG, our_driver_id="VER"), CONFIG_DIR)
    engine.start_compounds = list(engine.compounds)
    engine.run()
    return engine


def test_mvp10_rivals_pit_and_change_energy_mode_unaided(race: _Recorder) -> None:
    """MVP-10: with no Engineer Command, every Rival pits and changes Energy Mode."""
    assert not race.applied_commands
    book, start = race.rival_book, race.start_compounds
    our = race.driver_ids.index("VER")
    assert our not in book.index and len(book.index) == race.n - 1
    changed = {i for i, _, _ in race.mode_changes}
    for k, i in enumerate(book.index):
        assert book.stops_done[k] >= 1, race.driver_ids[i]
        assert race.compounds[i] == book.next_compound[k] != start[i], race.driver_ids[i]
        assert i in changed, race.driver_ids[i]
    # Our Car is the user's: the AI leaves it alone.
    assert our not in changed and race.compounds[our] == start[our]
    assert race.instructions[our] == DriverInstructions()


def _battle(engine: RaceEngine) -> tuple[int, int]:
    """Run until a Rival (row ``k``) chases car ``j`` whose Radar Estimate has confidence."""
    cfg, st = engine.app.rival_strategy, engine.st
    idx = engine.rival_book.index
    for _ in range(20000):
        engine.tick()
        if engine.steps % engine.decision_steps:
            continue
        engine._sync_radar()
        energy, confidence = engine.radar.energies(with_prior=False)  # what Rivals read
        ga, _, _, _ = RS.battle_inputs(
            idx, st.s_m, st.running & ~st.in_pit, st.ahead_idx, st.gap_ahead_m, st.v_ms,
            st.battery_j[idx] / MJ, energy, confidence,
        )  # fmt: skip
        for k in np.flatnonzero(ga <= cfg.battle_gap_s):
            j = int(st.ahead_idx[idx[k]])
            if confidence[j] > 0.0 and not st.in_pit[idx[k]]:
                return int(k), j
    raise AssertionError("no battle with a confident Radar Estimate")


def test_hr03_decisions_ignore_other_cars_ground_truth_battery() -> None:
    """Another car's true battery changes nothing; its Radar Estimate does."""
    engine = RaceEngine(RaceSetup(laps=8), CONFIG_DIR)
    k, j = _battle(engine)
    snap = engine.snapshot()
    base = RaceEngine.from_snapshot(snap)._rival_decisions()
    rows = engine.rival_book.index != j  # car j's own decision may use its own battery
    for battery_j in (0.0, 4.0 * MJ):
        fork = RaceEngine.from_snapshot(snap)
        fork.st.battery_j[j] = battery_j
        fork.timing.lap_battery_j[j] = battery_j
        for got, want in zip(fork._rival_decisions(), base, strict=True):
            np.testing.assert_array_equal(got[rows], want[rows])
    attack = []
    for offset_mj in (-3.0, 3.0):
        fork = RaceEngine.from_snapshot(snap)
        own_mj = float(fork.st.battery_j[engine.rival_book.index[k]]) / MJ
        fork.radar.state[j, _ENERGY] = (own_mj + offset_mj) * MJ
        _, att, _, hold, _ = fork._rival_decisions()
        attack.append((bool(att[k]), bool(hold[k])))
    assert attack == [(True, False), (False, True)]  # weak estimate: attack; strong: hold
