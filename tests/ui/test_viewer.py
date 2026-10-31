"""Sprint S-2: replay viewer records a race and plays it at >= 10 fps at 16x."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pitwall_sim.race.engine import RaceSetup  # noqa: E402
from pitwall_sim.viewer.app import ReplayWindow  # noqa: E402
from pitwall_sim.viewer.record import Replay, record  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def replay(tmp_path_factory: pytest.TempPathFactory) -> Replay:
    run = tmp_path_factory.mktemp("run")
    record(RaceSetup(laps=3, seed=42), CONFIG_DIR).save(run)
    return Replay.load(run)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def test_recording_round_trips(replay: Replay) -> None:
    n = len(replay.meta["drivers"])
    assert n == 22 and replay.s_m.shape == (replay.t_s.size, n)
    assert np.all(np.diff(replay.t_s) > 0)
    assert replay.leader_lap.max() >= 3
    assert set(np.unique(replay.position[-1])) == set(range(1, n + 1))
    assert (replay.battery_mj >= 0).all() and (replay.battery_mj <= 4.01).all()
    assert all(d["code"] and d["color"].startswith("#") for d in replay.meta["drivers"])


def test_viewer_plays_at_16x_fast_enough(replay: Replay, app: QApplication) -> None:
    window = ReplayWindow(replay)
    window.show()
    window.select(3)
    window.seek_lap(2)
    assert replay.leader_lap[window.k] == 2
    window.set_speed(16)
    window.toggle_play()
    window.frames = 0
    start = time.perf_counter()
    t0 = window.t
    while time.perf_counter() - start < 3.0:
        app.processEvents()
        time.sleep(0.005)
    fps = window.frames / (time.perf_counter() - start)
    assert fps >= 10.0, fps
    assert window.t - t0 == pytest.approx(16 * 3.0, rel=0.25)  # 16x real time
    window.truth_box.setChecked(False)
    assert not window.truth_curve.isVisible()
    window.close()
