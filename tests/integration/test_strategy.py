"""Hackathon H5: strategy panel plans and the background worker."""

from __future__ import annotations

import time
from pathlib import Path

from pitwall_sim.config.models import Compound
from pitwall_sim.live.session import LiveSession, LiveSetup
from pitwall_sim.live.strategy import PublicInfo, StrategyWorker, plans_for
from pitwall_sim.observe.engineer_view import EngineerViewBuilder
from pitwall_sim.race.engine import RaceEngine, RaceSetup

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_plans_and_worker() -> None:
    engine = RaceEngine(RaceSetup(laps=15, our_driver_id="GAS"), CONFIG_DIR)
    while engine.t < 150.0:
        engine.tick()
    plans = plans_for(engine)
    assert plans[0] == ("STAY_OUT", None)
    assert {p for p, _ in plans[1:]} == {"BOX_NOW", "BOX_+1", "BOX_+2", "BOX_+3"}
    assert {c for _, c in plans[1:]} <= {Compound.SOFT, Compound.MEDIUM, Compound.HARD}
    info = PublicInfo.from_view(EngineerViewBuilder(engine, "GAS").build())
    worker = StrategyWorker(workers=2, forks=1)
    worker.start()
    try:
        some = [plans[0], plans[1]]
        assert worker.submit(engine.snapshot(), "GAS", info, some, 2)
        assert not worker.submit(engine.snapshot(), "GAS", info, some, 2)  # one at a time
        start = time.perf_counter()
        while not worker.poll():
            assert time.perf_counter() - start < 180.0
            time.sleep(0.2)
    finally:
        worker.close()
    result = worker.result
    assert result is not None and worker.result_lap == 2 and len(result) == 2
    stay, box = result
    assert stay.plan == "STAY_OUT" and stay.gain_vs_ahead_s is None
    assert box.plan == "BOX_NOW" and box.gain_vs_ahead_s is not None
    assert 1.0 <= stay.expected_position <= 22.0 and box.n_forks == 1


class _FakeWorker:
    """Records submitted laps instead of forking (no processes)."""

    def __init__(self) -> None:
        self.busy = False
        self.laps: list[int] = []

    def poll(self) -> bool:
        return False

    def submit(self, *args: object) -> bool:
        self.laps.append(int(args[-1]))  # type: ignore[call-overload]
        return True

    def close(self) -> None:
        pass


def test_no_strategy_refresh_after_the_chequered_flag() -> None:
    """Live run seed 42 / VER / 15 laps: a "lap 16" plan was forked after the flag."""
    session = LiveSession(LiveSetup(our_driver_id="VER", laps=2), CONFIG_DIR)
    fake = _FakeWorker()
    session._strategy = fake  # type: ignore[assignment]
    while session.advance(10.0):
        pass
    assert fake.laps and max(fake.laps) <= 2
    assert not session.refresh_strategy()  # the Refresh button too
    reveal = session.reveal()
    assert reveal is not None
    # Reveal axis: 1.0 = the start of lap 1, so a 2-lap race ends at 3.0 (no cool-down)
    assert all(float(r.lap.max()) <= 3.0 for r in reveal.rivals)
