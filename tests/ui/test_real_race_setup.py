"""E3 real race moment on the setup screen: pick the lap; laps and preset come from it."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pytestqt.qtbot import QtBot  # noqa: E402

from pitwall_sim.ui.setup_screen import SetupScreen  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_setup_screen_real_race_moment(qtbot: QtBot) -> None:
    screen = SetupScreen(CONFIG_DIR)
    qtbot.addWidget(screen)
    assert screen.choice().real_lap is None  # a normal race unless chosen
    assert not screen.real_lap.isEnabled()
    screen.real_race.setChecked(True)
    assert screen.real_lap.value() == 30  # "you are on the pit wall at lap 30"
    assert screen.real_lap.isEnabled()
    assert not screen.laps.isEnabled() and not screen.preset.isEnabled()
    screen.real_lap.setValue(40)
    assert screen.choice().real_lap == 40
    screen.real_race.setChecked(False)
    assert screen.choice().real_lap is None and screen.laps.isEnabled()
