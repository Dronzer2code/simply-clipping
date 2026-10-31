"""Hackathon H6: Our Car telemetry against lap distance with a previous-lap ghost."""

from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pytestqt.qtbot import QtBot  # noqa: E402

from pitwall_sim.ui.telemetry_plot import LapTelemetry, TelemetryPlot  # noqa: E402

LENGTH_M = 5807.0


def _drive(tel: LapTelemetry, laps: range, t0: float = 0.0, step_m: float = 40.0) -> float:
    t = t0
    for lap in laps:
        for s in np.arange(0.0, LENGTH_M, step_m):
            t += 0.5
            tel.add_sample(t, lap, float(s), 70.0 + lap, 1.0, 2.0 + 0.1 * lap)
    return t


def test_lap_change_makes_the_ghost() -> None:
    tel = LapTelemetry(LENGTH_M, capacity=512)
    tel.add_sample(0.1, -1, 5706.0, 0.0, 0.0, 4.0)  # grid to the line: not a ghost
    tel.add_sample(0.2, -1, 5750.0, 10.0, 1.0, 4.0)
    _drive(tel, range(0, 1), t0=1.0)
    assert not tel.has_ghost and tel.current.lap == 0
    _drive(tel, range(1, 2), t0=1000.0)
    assert tel.has_ghost and tel.ghost.lap == 0 and tel.current.lap == 1
    assert np.allclose(tel.ghost.y("speed"), 70.0 * 3.6)
    assert np.allclose(tel.ghost.y("throttle"), 100.0)
    assert np.allclose(tel.current.y("battery"), 2.1)


def test_repeated_frames_and_full_buffers_are_ignored() -> None:
    tel = LapTelemetry(LENGTH_M, capacity=8)
    for k in range(20):
        tel.add_sample(1.0 + k, 0, 10.0 * k, 50.0, 0.5, 3.0)
    tel.add_sample(5.0, 0, 999.0, 50.0, 0.5, 3.0)  # older than the last sample (paused)
    assert tel.current.n == 8
    arrays = {id(tel.current.s_m), id(tel.ghost.s_m)}
    _drive(tel, range(1, 3), t0=100.0)
    assert arrays == {id(tel.current.s_m), id(tel.ghost.s_m)}  # swapped, never reallocated


def test_widget_draws_current_and_ghost(qtbot: QtBot) -> None:
    plot = TelemetryPlot(LENGTH_M)
    qtbot.addWidget(plot)
    plot.show()
    _drive(plot.telemetry, range(0, 2))
    assert plot.redraw()
    assert not plot.redraw()  # unchanged: nothing to do
    x, y = plot.curves["speed"].getData()
    gx, gy = plot.ghosts["speed"].getData()
    assert x is not None and gx is not None and len(x) == len(gx) > 100
    assert np.allclose(gy, 70.0 * 3.6) and np.allclose(y, 71.0 * 3.6)
    assert plot.ghosts["speed"].opts["pen"].color().alphaF() < 0.5  # faint ghost
    assert "lap 2" in plot.title.text() and "lap 1 ghost" in plot.title.text()
