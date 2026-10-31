"""T-052 / MVP-08: EngineerView builder and the information barrier (HR-02, HR-03, PF-06).

The whole object graph of a mid-race EngineerView is walked: Rival Ground Truth
fields may appear only under ``our_car`` (Our Car's own Ground Truth), and no
engine, kernel state or RaceState object may be reachable.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall_sim.observe.engineer_view import EngineerView, EngineerViewBuilder
from pitwall_sim.race import step_kernel as K
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.state import CarState, RaceState

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
OUR_CAR = "LEC"
#: Rival Ground Truth (HR-03) and the kernel's names for it.
FORBIDDEN = {
    "battery_mj", "energy_mode", "tyre_wear", "fuel_kg", "harvest_mj_lap", "deploy_mj_lap",
    "battery_j", "harvest_lap_j", "deploy_lap_j", "plans", "instructions", "rival_plan",
}  # fmt: skip
ENGINE_TYPES = (RaceEngine, RaceState, K.KernelState, K.KernelCars, K.KernelControls)


def _walk(obj: Any, path: str, out: list[tuple[str, Any]], seen: set[int]) -> None:
    if id(obj) in seen:
        return
    seen.add(id(obj))
    out.append((path, obj))
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            _walk(getattr(obj, f.name), f"{path}.{f.name}", out, seen)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk(v, f"{path}[{k!r}]", out, seen)
    elif isinstance(obj, (list, tuple)):
        for k, v in enumerate(obj):
            _walk(v, f"{path}[{k}]", out, seen)


@pytest.fixture(scope="module")
def view_and_engine() -> tuple[EngineerView, RaceEngine]:
    engine = RaceEngine(RaceSetup(laps=2, fuel_kg=40.0, our_driver_id=OUR_CAR), CONFIG_DIR)
    builder = EngineerViewBuilder(engine, OUR_CAR)
    view = builder.build()
    while engine.t < 150.0:
        engine.tick()
        if engine.steps % 20 == 0:  # the UI builds views as the race runs
            view = builder.build()
    view = builder.build()
    return view, engine


def test_info_barrier(view_and_engine) -> None:  # type: ignore[no-untyped-def]
    view, engine = view_and_engine
    nodes: list[tuple[str, Any]] = []
    _walk(view, "view", nodes, set())
    car_states = [(p, o) for p, o in nodes if isinstance(o, CarState)]
    assert car_states == [("view.our_car", view.our_car)]
    assert view.our_car.driver_id == OUR_CAR
    for path, obj in nodes:
        assert not isinstance(obj, ENGINE_TYPES), path
        assert not isinstance(obj, np.ndarray), path  # plain values only
        if dataclasses.is_dataclass(obj) and not path.startswith("view.our_car"):
            names = {f.name for f in dataclasses.fields(obj)}
            assert not names & FORBIDDEN, (path, names & FORBIDDEN)
    # The Radar estimates come from the feed, not from Ground Truth.
    truth = {d: engine.st.battery_j[i] / 1e6 for i, d in enumerate(engine.driver_ids)}
    estimates = {d: e.energy_mj for d, e in view.radar.items()}
    assert OUR_CAR not in estimates and len(estimates) == engine.n - 1
    assert sum(abs(estimates[d] - truth[d]) < 1e-6 for d in estimates) < len(estimates) / 2


def test_view_contents(view_and_engine) -> None:  # type: ignore[no-untyped-def]
    view, engine = view_and_engine
    assert view.t_s == engine.t
    assert view.our_car.battery_mj == pytest.approx(
        engine.st.battery_j[engine.driver_ids.index(OUR_CAR)] / 1e6
    )
    assert set(view.rival_feed) == set(engine.driver_ids) - {OUR_CAR}
    frames = view.rival_feed["VER"]
    assert frames and all(view.t_s - 30.0 < f.t_s <= view.t_s for f in frames)
    assert view.timing.order and set(view.timing.order) == set(engine.driver_ids)
    assert view.flag == "GREEN" and view.weather_public.condition == "DRY"
    assert view.radio_log == [] and view.predictor is None
    assert view.track_status.status == "GREEN" and view.strategy is None
    assert all(0.0 <= e.confidence <= 1.0 for e in view.radar.values())


def test_ui_cannot_import_race_state() -> None:
    text = (ROOT / ".importlinter").read_text(encoding="utf-8")
    block = text.split("[importlinter:contract:ui-info-barrier]", 1)[1].split("[importlinter", 1)[0]
    # Sprint S-5: the UI may not import any race module itself (race.state included);
    # EngineerView and the live session reach the race only indirectly.
    assert "pitwall_sim.ui" in block and "\n    pitwall_sim.race\n" in block
    assert "type = forbidden" in block
    for source in (ROOT / "pitwall_sim" / "ui").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "from pitwall_sim.race" not in text and "import pitwall_sim.race" not in text, source


def test_info_barrier_covers_hackathon_fields() -> None:
    """Track status, strategy plans and radio events carry no Rival Ground Truth."""
    from pitwall_sim.engineer.records import CallCost, CallRecord, RadioEvent, StrategyResult
    from pitwall_sim.race.state import TrackStatus

    engine = RaceEngine(RaceSetup(laps=2, fuel_kg=40.0, our_driver_id=OUR_CAR), CONFIG_DIR)
    builder = EngineerViewBuilder(engine, OUR_CAR)
    for _ in range(200):
        engine.tick()
    engine.track_status = TrackStatus("SC", sc_laps_remaining=3)
    builder.strategy = (
        StrategyResult("BOX_+1", "HARD", 7.4, 1.2, car_ahead="VER", n_forks=4),
        StrategyResult("STAY_OUT", None, 8.0, None),
    )
    builder.radio_log.append(RadioEvent(engine.t, "DRIVER", "Safety car, safety car.", "TEMPLATE"))
    view = builder.build()
    assert view.track_status.status == "SC" and view.track_status.sc_laps_remaining == 3
    assert view.strategy is not None and view.strategy[0].plan == "BOX_+1"
    assert view.radio_log[-1].source == "TEMPLATE"
    nodes: list[tuple[str, Any]] = []
    _walk(view, "view", nodes, set())
    for path, obj in nodes:
        if dataclasses.is_dataclass(obj) and not path.startswith("view.our_car"):
            names = {f.name for f in dataclasses.fields(obj)}
            assert not names & FORBIDDEN, (path, names & FORBIDDEN)
    for contract in (RadioEvent, CallRecord, CallCost, StrategyResult, TrackStatus):
        assert not {f.name for f in dataclasses.fields(contract)} & FORBIDDEN, contract
    assert engine.race_state().track_status.status == "SC"  # in RaceState (and its hash)


def test_strategy_panel_sees_no_rival_truth() -> None:
    """H5: strategy forks start from public data only; Rival truth cannot change them."""
    from dataclasses import replace as dc_replace

    from pitwall_sim.config.models import EnergyMode
    from pitwall_sim.live.strategy import PublicInfo, evaluate, public_snapshot
    from pitwall_sim.race.snapshot import restore

    engine = RaceEngine(RaceSetup(laps=6, fuel_kg=60.0, our_driver_id=OUR_CAR), CONFIG_DIR)
    builder = EngineerViewBuilder(engine, OUR_CAR)
    while engine.t < 150.0:
        engine.tick()
    info = PublicInfo.from_view(builder.build())
    snap = engine.snapshot()
    # The same race with every Rival's hidden state changed (battery, wear, fuel, mode, plan).
    other = restore(snap)
    for i, d in enumerate(other.driver_ids):
        if d == OUR_CAR:
            continue
        other.st.battery_j[i] = 4e6 - other.st.battery_j[i]
        other.st.tyre_wear[i] = 0.5
        other.st.fuel_kg[i] = 10.0
        other.set_instructions(i, dc_replace(other.instructions[i], mode=EnergyMode.PUSH))
    other.rival_book.stop_lap[:] = 2
    changed = other.snapshot()
    a, b = public_snapshot(snap, OUR_CAR, info), public_snapshot(changed, OUR_CAR, info)
    for pub in (a, b):
        cars = {c.driver_id: c for c in pub.race_state.cars}
        for d, est in info.radar_mj.items():
            assert cars[d].battery_mj == pytest.approx(est)  # the Radar Estimate, not truth
            assert cars[d].energy_mode == "BALANCED"
    assert [c for c in a.race_state.cars if c.driver_id != OUR_CAR] == [
        c for c in b.race_state.cars if c.driver_id != OUR_CAR
    ]
    plans = [("STAY_OUT", None), ("BOX_NOW", engine.compounds[0])]
    assert evaluate(snap, OUR_CAR, info, plans, forks=1) == evaluate(  # type: ignore[arg-type]
        changed,
        OUR_CAR,
        info,
        plans,
        forks=1,  # type: ignore[arg-type]
    )
