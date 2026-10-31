"""Hackathon H3: team-radio filter (the speech engine itself is not run in tests)."""

from __future__ import annotations

import numpy as np

from pitwall_sim.radio.voice import DriverVoice, team_radio_filter

RATE = 22050


def _tone(hz: float) -> np.ndarray:
    t = np.arange(RATE) / RATE
    return 0.5 * np.sin(2 * np.pi * hz * t)


def _level(x: np.ndarray, hz: float) -> float:
    spectrum = np.abs(np.fft.rfft(x))
    return float(spectrum[int(hz)])  # 1 s of audio: bin k = k Hz


def test_band_pass_keeps_the_voice_band() -> None:
    mix = _tone(100.0) + _tone(1000.0) + _tone(8000.0)
    out = team_radio_filter(mix, RATE)
    assert out.size == mix.size and np.all(np.abs(out) <= 1.0)
    voice = _level(out, 1000.0)
    assert _level(out, 100.0) < 0.1 * voice and _level(out, 8000.0) < 0.1 * voice


def test_muted_by_default() -> None:
    voice = DriverVoice()
    assert not voice.enabled
    voice.say("Box box.")  # muted: nothing queued
    assert voice._lines.empty()
