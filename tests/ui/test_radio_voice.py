"""Hackathon H2: push-to-talk button and key, and the "understood by" indicator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from pytestqt.qtbot import QtBot  # noqa: E402

from pitwall_sim.live.session import LiveSession, LiveSetup  # noqa: E402
from pitwall_sim.radio import stt  # noqa: E402
from pitwall_sim.ui.pitwall_lite import PitWallWindow  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _window(qtbot: QtBot) -> tuple[PitWallWindow, LiveSession]:
    session = LiveSession(LiveSetup(our_driver_id="GAS"), CONFIG_DIR)
    window = PitWallWindow(session, start_speed="PAUSE")
    qtbot.addWidget(window)
    window.show()
    return window, session


def test_talk_button_off_without_voice_packages(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt, "status", lambda: (False, "Voice input needs faster_whisper"))
    window, _ = _window(qtbot)
    assert not window.talk_button.isEnabled() and window.ptt is None
    assert "faster_whisper" in window.talk_button.toolTip()
    qtbot.keyClicks(window.radio_input, "`")  # the key just types: nothing breaks
    window.close()


class _Recorder:
    def start(self) -> None: ...

    def stop(self) -> tuple[Any, int]:
        return np.zeros(16000, np.float32), 16000


class _Transcriber:
    def transcribe(self, samples: Any, rate: int) -> str:
        return "push"


def test_hold_the_key_to_talk(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt, "status", lambda: (True, "Hold to talk (fake mic)"))
    monkeypatch.setattr(stt, "WhisperTranscriber", lambda *a, **k: _Transcriber())
    monkeypatch.setattr(stt, "SoundDeviceRecorder", lambda *a, **k: _Recorder())
    window, session = _window(qtbot)
    assert window.talk_button.isEnabled() and window.ptt is not None
    qtbot.keyPress(window.radio_input, "`")
    assert window.ptt.recording and window.radio_input.text() == ""  # not typed
    qtbot.keyRelease(window.radio_input, "`")
    qtbot.waitUntil(lambda: len(session.call_log) == 1, timeout=5000)
    assert session.call_log[0].option_label == "radio: SET_ENERGY_MODE"
    window.on_frame(session.frame())
    assert window.radio_via.text() == "Understood by: VOICE > KEYWORD"
    qtbot.keyClicks(window.radio_input, "harvest")
    qtbot.keyClick(window.radio_input, Qt.Key.Key_Return)
    window.on_frame(session.frame())
    assert window.radio_via.text() == "Understood by: KEYWORD"
    window.close()
