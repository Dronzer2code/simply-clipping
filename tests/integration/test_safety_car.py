"""Hackathon H4 (simplified T-038): Safety Car and VSC triggers, effects, rivals, radio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.models import Compound
from pitwall_sim.live.session import TRACK_STATUS_LINES, LiveSession, LiveSetup
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.snapshot import restore

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
OUR = "GAS"


def _engine(**setup: object) -> RaceEngine:
    return RaceEngine(RaceSetup(our_driver_id=OUR, **{"laps": 8, **setup}), CONFIG_DIR)  # type: ignore[arg-type]


def _run_until(engine: RaceEngine, done: object, limit_s: float = 4000.0) -> None:
    while not done() and engine.t < limit_s and not engine.finished:  # type: ignore[operator]
        engine.tick()


def _progress(engine: RaceEngine, i: int) -> float:
    return float(engine.st.lap[i]) * engine.trk.length_m + float(engine.st.s_m[i])


def _spread(engine: RaceEngine) -> float:
    on = np.flatnonzero(engine.st.running & ~engine.st.in_pit)
    prog = engine.st.lap[on] * engine.trk.length_m + engine.st.s_m[on]
    return float(prog.max() - prog.min())


def test_crash_on_line_is_sc_off_line_is_vsc() -> None:
    e = _engine()
    _run_until(e, lambda: e.t > 60.0)
    e.incident(3, on_line=False)
    assert e.track_status.status == "VSC" and e.flag == "VSC"
    assert e.track_status.vsc_end_time_s == pytest.approx(e.t + e.app.race_events.vsc_duration_s)
    e.incident(4, on_line=True)  # a car on the line during a VSC: upgraded to SC
    assert e.track_status.status == "SC" and e.flag == "SC"
    assert e.track_status.sc_laps_remaining == e.app.race_events.sc_laps
    crash = _engine()
    _run_until(crash, lambda: crash.t > 60.0)
    crash._mistake(5, 0, "CRASH")  # a crash retires the car and raises SC or VSC
    assert crash.status[5] == "DNF" and crash.track_status.status in ("SC", "VSC")
    assert crash.track_events[-1][2].startswith(crash.driver_ids[5])


def test_vsc_caps_speed_and_ends() -> None:
    e = _engine(laps=20)  # planned stops far off: most Rivals stay out under the VSC
    _run_until(e, lambda: e.t > 100.0)
    snap = e.snapshot()
    green, vsc = restore(snap), restore(snap)
    vsc.deploy("VSC", "test")
    start = np.array([_progress(green, i) for i in range(green.n)])
    pitted = np.zeros(green.n, dtype=bool)  # the VSC pit branch boxes some Rivals: leave them out
    while green.t < snap.t + 60.0:
        for engine in (green, vsc):
            engine.tick()
            pitted |= engine.st.in_pit
    on = np.flatnonzero(green.st.running & vsc.st.running & ~pitted)
    assert on.size >= 3
    ratio = np.median(
        [(_progress(vsc, i) - start[i]) / (_progress(green, i) - start[i]) for i in on]
    )
    assert 0.65 < ratio < 0.85, ratio  # race pace / 1.35 = 0.74, plus the slow-down
    _run_until(vsc, lambda: vsc.track_status.status == "GREEN")
    assert vsc.t >= snap.t + vsc.app.race_events.vsc_duration_s
    assert np.all(vsc.ctl.speed_scale == 1.0) and vsc.flag == "GREEN"


def test_sc_no_overtakes_bunches_and_restarts() -> None:
    e = _engine(scripted_sc_lap=3)
    _run_until(e, lambda: e.track_status.status == "SC")
    assert e.track_events[0][1:] == ("SC", "scripted (demo)")
    deployed_lap = int(e.st.lap[e.st.running].max())
    spread_at_deploy = _spread(e)
    overtakes = len(e.overtake.events)
    seen = {e.track_status.status}
    while e.track_status.status != "GREEN":
        e.tick()
        seen.add(e.track_status.status)
        if e.track_status.status != "GREEN":
            assert len(e.overtake.events) == overtakes  # no overtakes under the SC
    assert seen >= {"SC", "SC_IN_THIS_LAP"}
    assert int(e.st.lap[e.st.running].max()) == deployed_lap + e.app.race_events.sc_laps
    assert _spread(e) < 0.6 * spread_at_deploy  # the field bunched up
    assert np.all(e.ctl.speed_scale == 1.0) and e.flag == "GREEN"


def _pit_loss_m(sc: bool) -> float:
    """Distance Our Car loses by boxing now: paired forks (box / no box), 200 s later."""
    base = _engine(laps=10)
    i = base.driver_ids.index(OUR)
    _run_until(base, lambda: base.st.lap[i] >= 2 and base.st.s_m[i] > 1500.0)
    snap = base.snapshot()
    end = []
    for box in (True, False):
        fork = restore(snap)
        if sc:
            fork.deploy("SC", "test")
        if box:
            assert fork.box(i, Compound.HARD)
        _run_until(fork, lambda fork=fork: fork.t >= snap.t + 200.0)
        end.append(_progress(fork, i))
    return end[1] - end[0]


def test_pit_stop_cheaper_under_sc() -> None:
    """MVP-13: a stop under the Safety Car costs measurably less than under green.

    While the car is in the pit lane the field drives at SC pace, so it loses less
    ground (rehearsal: 1520 m under green, 1060 m under SC, 200 s after the call).
    """
    green, sc = _pit_loss_m(False), _pit_loss_m(True)
    assert green > 500.0, green
    assert sc < 0.8 * green, (sc, green)


def test_rivals_split_under_sc() -> None:
    e = _engine(laps=15, scripted_sc_lap=6)
    _run_until(e, lambda: e.track_status.status == "SC")
    rivals = [d for i, d in enumerate(e.driver_ids) if d != OUR and e.st.running[i]]
    boxed = set(e.sc_rivals_boxed)
    assert boxed and len(boxed) < len(rivals)  # some box, some stay out
    _run_until(e, lambda: e.track_status.status == "GREEN")
    stops = {d: e.pit_stops(e.driver_ids.index(d)) for d in rivals}
    assert all(stops[d] >= 1 for d in boxed)


def test_snapshot_under_sc_is_deterministic() -> None:
    e = _engine(scripted_sc_lap=2)
    _run_until(e, lambda: e.track_status.status == "SC")
    for _ in range(40):
        e.tick()
    snap = e.snapshot()
    a, b = restore(snap), restore(snap)
    for _ in range(200):
        a.tick()
        b.tick()
    assert a.race_state().hash() == b.race_state().hash()
    assert a.track_status == b.track_status


def test_driver_radios_the_safety_car() -> None:
    s = LiveSession(LiveSetup(our_driver_id=OUR, laps=4, scripted_sc_lap=2), CONFIG_DIR)
    while s.frame().view.track_status.status == "GREEN" and s.advance(10.0):
        pass
    assert s.frame().view.track_status.status == "SC"
    driver = [e for e in s.frame().view.radio_log if e.sender == "DRIVER"]
    assert driver and driver[-1].text == TRACK_STATUS_LINES["SC"]
