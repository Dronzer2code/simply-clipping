"""Quick-start presets for testing alert types on demand (sprint day 4).

Starting conditions and Rival Strategy behaviour only (no physics changes):

- ``repass``: Our Car starts P10 right behind a rival that starts with an empty
  battery (so the Rival Strategy runs it in HARVEST and it is slow early); Our
  Car starts on ``REPASS_OUR_MJ`` in PUSH with ATTACK. Passing it early leaves
  Our Car below 1 MJ before a long straight: RE-PASS RISK.
- ``closing_speed``: Our Car starts P14 in PUSH with a full battery;
  ``CLOSING_TRAIN`` rivals ``CLOSING_GAP`` places ahead (P7-P9) start on empty
  batteries (the Rival Strategy runs them in HARVEST: they clip on the
  straights while Our Car deploys). By the time Our Car reaches them (lap 1-2)
  their first clips have anchored their Radar Estimates, which an alert needs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from pitwall_sim.config.models import EnergyMode
from pitwall_sim.race.engine import RaceEngine

Preset = Literal["none", "repass", "closing_speed"]
PRESETS: dict[Preset, str] = {
    "none": "Normal race",
    "repass": "Re-pass scenario (RE-PASS RISK in the first laps)",
    "closing_speed": "Closing-speed scenario (CLOSING-SPEED RISK in the first laps)",
}
OUR_SLOT = {"repass": 9, "closing_speed": 13}  # P10 / P14
REPASS_OUR_MJ = 2.0
REPASS_RIVAL_WEAR = 0.65
"""The car ahead starts on worn tyres (below the tyre cliff and the Rivals' 0.85 critical
wear): with the harder passing of hackathon H7 an energy advantage alone rarely completes
the pass (worn: GAS and HAM re-pass at ~79 s; fresh: no pass in 900 s)."""
CLOSING_TRAIN = 3
CLOSING_GAP = 4
MJ = 1e6


def grid_order(preset: Preset, our: str, default: tuple[str, ...]) -> tuple[str, ...] | None:
    """Return the starting order for the preset (None: the grid's own)."""
    if preset == "none":
        return None
    order = [d for d in default if d != our]
    order.insert(OUR_SLOT[preset], our)
    return tuple(order)


def rival_ahead(engine: RaceEngine, our: str) -> str:
    """Return the car starting right ahead of Our Car."""
    order = [engine.driver_ids[int(i)] for i in engine._classification]
    return order[order.index(our) - 1]


def apply(preset: Preset, engine: RaceEngine, our: str) -> str | None:
    """Set the preset's starting conditions; return the rival it targets."""
    if preset == "none":
        return None
    order = [engine.driver_ids[int(k)] for k in engine._classification]
    k = order.index(our)
    i = engine.driver_ids.index(our)
    if preset == "repass":
        train = order[k - 1 : k]
    else:
        train = order[k - CLOSING_GAP - CLOSING_TRAIN : k - CLOSING_GAP]
    for rival in train:  # empty: the Rival Strategy puts them in HARVEST
        _battery(engine, engine.driver_ids.index(rival), 0.0)
    if preset == "repass":
        _battery(engine, i, REPASS_OUR_MJ * MJ)
        ahead = engine.driver_ids.index(train[-1])
        engine.st.tyre_wear[ahead] = REPASS_RIVAL_WEAR
        engine._set_plan(ahead, engine._plan_car(ahead))
        # Our Car starts on the attack (the rival defends): the pass comes early.
        engine.set_instructions(
            i, replace(engine.instructions[i], mode=EnergyMode.PUSH, attack=True, follow_close=True)
        )
    else:
        engine.set_instructions(i, replace(engine.instructions[i], mode=EnergyMode.PUSH))
    return train[-1]


def _battery(engine: RaceEngine, i: int, joules: float) -> None:
    engine.st.battery_j[i] = joules
    engine.timing.lap_battery_j[i] = joules  # the battery "at the line" at the start
    engine._set_plan(i, engine._plan_car(i))  # plan the first lap on this battery
