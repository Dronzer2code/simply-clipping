"""Export scenarios aimed at Simply Clipping's weak spots (sprint S-1, SPRINT.md Part 5).

Sprint texts: docs/planning/SPRINT.md.

Starting conditions, Rival Strategy settings and Energy Modes only, no physics
changes. A scenario names the car it scripts (it takes Our Car's slot, so the
Rival Strategy AI leaves its instructions alone) and the target it is built to
produce; the export checks the target in the Ground Truth and reports it.

- ``normal``: a plain race.
- ``battles``: the grid in reverse order of pace (slowest first), so faster cars
  start behind slower ones: packs and fights from the start.
- ``repass`` (Norris / Hamilton): NOR starts right behind HAM; for the first
  ``REPASS_RELEASE_LAPS`` laps both are scripted (out of the Rival Strategy AI):
  NOR in PUSH with ATTACK spends its battery on the pass, HAM in BALANCED with
  ATTACK keeps its energy and goes for the re-pass. Then both race on under the
  Rival Strategy AI (pit stops included).
- ``closing_speed`` (Bearman / Colapinto): BEA starts P14 in PUSH on a full
  battery right behind COL, which starts empty (the Rival Strategy runs it in
  HARVEST: it super-clips on the straights while BEA deploys behind it).
- ``taper``: the Rival Strategy pushes the whole race (``push_final_laps`` =
  race laps), so cars spend long stretches deploying at 290-355 km/h where the
  MGU-K is limited by the speed taper.
- ``cda_trap``: every fourth car starts empty and the Rival Strategy never
  switches to HARVEST (``low_battery_mj`` 0): those cars run BALANCED near empty
  and start many straights with no energy (the CdA fit assumes full deployment
  in the first seconds of a straight).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from pitwall_sim.config.models import EnergyMode
from pitwall_sim.live import presets
from pitwall_sim.race import rival_strategy as RS
from pitwall_sim.race.engine import RaceEngine

Scenario = Literal["normal", "battles", "repass", "closing_speed", "taper", "cda_trap"]
SCENARIOS: tuple[Scenario, ...] = (
    "normal", "battles", "repass", "closing_speed", "taper", "cda_trap",
)  # fmt: skip
REPASS_PAIR = ("NOR", "HAM")
"""(car that passes, car that re-passes): the 2026 Japanese GP case."""
CLOSING_PAIR = ("BEA", "COL")
"""(car closing, car ahead): the 2026 Japanese GP lap-22 case."""
CDA_TRAP_EVERY = 4
REPASS_RELEASE_LAPS = 4
"""The repass pair is scripted for this many laps, then the Rival Strategy AI takes over."""


@dataclass(frozen=True)
class ScenarioSetup:
    """How a scenario changes the race before it starts."""

    scenario: Scenario
    grid_order: tuple[str, ...] | None = None
    scripted: str | None = None
    """The car the scenario drives (Our Car's slot: no Rival Strategy AI)."""
    pov: str | None = None
    """The car whose built-in alerts the export keeps (None: the default car)."""
    held: tuple[str, ...] = ()
    """Cars taken out of the Rival Strategy AI for the opening laps."""
    pair: tuple[str, str] | None = None
    """(car_a, car_b) of the target event."""
    trap_cars: tuple[str, ...] = ()
    rival_strategy: dict[str, float] = field(default_factory=dict)
    """Rival Strategy settings to override (``app.yaml: rival_strategy``)."""
    target: str = ""


def plan(
    scenario: Scenario, default_order: tuple[str, ...], pace_s: dict[str, float], laps: int
) -> ScenarioSetup:
    """Return the scenario's setup for a grid (``pace_s``: reference lap time per car)."""
    if scenario == "normal":
        return ScenarioSetup(scenario, target="none (plain race)")
    if scenario == "battles":
        order = tuple(sorted(default_order, key=lambda d: -pace_s[d]))
        return ScenarioSetup(scenario, grid_order=order,
                             target="cars within 1.0 s of the car ahead (battle time)")  # fmt: skip
    if scenario == "repass":
        a, b = REPASS_PAIR
        cars = [d for d in default_order if d not in (a, b)]
        k = presets.OUR_SLOT["repass"]
        cars[k - 1 : k - 1] = [b, a]
        return ScenarioSetup(
            scenario, grid_order=tuple(cars), pov=a, held=(a, b), pair=(a, b),
            target=f"{a} passes {b} with < 1.0 MJ before a > 600 m straight; {b} re-passes"
            " within 1 lap",
        )  # fmt: skip
    if scenario == "closing_speed":
        a, b = CLOSING_PAIR
        cars = [d for d in default_order if d not in (a, b)]
        k = presets.OUR_SLOT["closing_speed"]
        cars[k - 1 : k - 1] = [b, a]
        return ScenarioSetup(
            scenario, grid_order=tuple(cars), scripted=a, pov=a, pair=(a, b),
            target=f"{a} closes > 40 km/h on {b} within 200 m while {b} clips or lifts",
        )  # fmt: skip
    if scenario == "taper":
        return ScenarioSetup(
            scenario, rival_strategy={"push_final_laps": float(laps)},
            target="deploying while the MGU-K is limited by the 290-355 km/h taper",
        )  # fmt: skip
    trap = tuple(d for k, d in enumerate(default_order) if k % CDA_TRAP_EVERY == 1)
    return ScenarioSetup(
        scenario, trap_cars=trap, rival_strategy={"low_battery_mj": 0.0},
        target=f"{', '.join(trap)} start straights with an empty battery",
    )  # fmt: skip


def apply(setup: ScenarioSetup, engine: RaceEngine) -> None:
    """Set the scenario's starting conditions on a freshly built engine."""
    if setup.rival_strategy:
        rs = engine.app.rival_strategy.model_copy(update=setup.rival_strategy)
        engine.app = engine.app.model_copy(update={"rival_strategy": rs})
    if setup.held:
        _hold(engine, setup.held)
    if setup.scenario == "repass":
        a, b = setup.held
        for driver, mode in ((a, EnergyMode.PUSH), (b, EnergyMode.BALANCED)):
            i = engine.driver_ids.index(driver)
            engine.set_instructions(i, replace(engine.instructions[i], mode=mode, attack=True))
    elif setup.scenario == "closing_speed":
        assert setup.pair is not None
        a, b = setup.pair
        presets._battery(engine, engine.driver_ids.index(b), 0.0)  # HARVEST: super-clips
        i = engine.driver_ids.index(a)
        engine.set_instructions(i, replace(engine.instructions[i], mode=EnergyMode.PUSH))
    for driver in setup.trap_cars:
        presets._battery(engine, engine.driver_ids.index(driver), 0.0)


def _hold(engine: RaceEngine, cars: tuple[str, ...]) -> None:
    """Take ``cars`` out of the Rival Strategy AI (their plans wait in ``held_plans``)."""
    engine.held_plans = {d: engine.rival_plans.pop(d) for d in cars}  # type: ignore[attr-defined]
    engine.rival_book = RS.RivalBook.from_plans(engine.rival_plans, engine.driver_ids)


def on_tick(setup: ScenarioSetup, engine: RaceEngine) -> None:
    """After the opening laps, give held cars back to the Rival Strategy AI."""
    held: dict[str, RS.RivalPlan] = getattr(engine, "held_plans", {})
    if not held:
        return
    lead = max(int(engine.st.lap[engine.driver_ids.index(d)]) for d in held)
    if lead < REPASS_RELEASE_LAPS:
        return
    book = engine.rival_book
    plans = {d: book.plan(d) for d in book.driver_ids}  # their state so far
    for driver, plan in held.items():
        plans[driver] = plan
        engine.rival_plans[driver] = plan
        i = engine.driver_ids.index(driver)
        engine.set_instructions(i, replace(engine.instructions[i], attack=False))
    engine.rival_book = RS.RivalBook.from_plans(plans, engine.driver_ids)
    engine.held_plans = {}  # type: ignore[attr-defined]
