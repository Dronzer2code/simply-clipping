"""Driver voice (hackathon H3): offline text-to-speech with a team-radio filter.

Speech comes from the Windows speech engine (SAPI, ``System.Speech``, offline and
built in; ``models/tts`` holds no model). Each line is spoken to a WAV file, run
through :func:`team_radio_filter` (band-pass 300-3400 Hz like a radio channel, soft
clipping and a light crackle) and played asynchronously. Muted unless the pit wall
turns it on. Anywhere SAPI is missing, :func:`available` is False and the radio
stays text only.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy.signal import butter, sosfilt

logger = logging.getLogger(__name__)
BAND_HZ = (300.0, 3400.0)
"""Radio channel pass band."""
DRIVE = 2.5
"""Soft-clip drive (tanh): the slightly overdriven radio sound."""
CRACKLE = 0.012
"""Background hiss level and pops, relative to full scale."""
VOICE = "Microsoft David Desktop"
"""Preferred SAPI voice (any installed voice is used if missing)."""


def team_radio_filter(samples: npt.NDArray[np.float64], rate: int,
                      seed: int = 7) -> npt.NDArray[np.float64]:  # fmt: skip
    """Make clean speech (-1..1) sound like team radio."""
    sos = butter(4, BAND_HZ, btype="bandpass", fs=rate, output="sos")
    out = sosfilt(sos, samples)
    peak = float(np.max(np.abs(out))) or 1.0
    out = np.tanh(DRIVE * out / peak) / np.tanh(DRIVE)
    rng = np.random.default_rng(seed)  # audio only, not the race (HR-04 covers the simulation)
    out = out + CRACKLE * rng.standard_normal(out.size)
    pops = rng.random(out.size) < 4.0 / rate  # ~4 pops a second
    out[pops] += rng.choice([-1.0, 1.0], int(pops.sum())) * 8 * CRACKLE
    return np.asarray(np.clip(out * 0.9, -1.0, 1.0), dtype=np.float64)


def available() -> bool:
    """Whether the offline speech engine can be used here."""
    return sys.platform == "win32"


def _synthesise(text: str, path: Path) -> None:
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"try {{ $s.SelectVoice('{VOICE}') }} catch {{}}; $s.Rate = 1; "
        f"$s.SetOutputToWaveFile('{path}'); $s.Speak($input); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   input=text, text=True, capture_output=True, timeout=20, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # fmt: skip


def _read(path: Path) -> tuple[npt.NDArray[np.float64], int]:
    with wave.open(str(path), "rb") as w:
        rate, n = w.getframerate(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64) / 32768.0
        if w.getnchannels() > 1:
            raw = raw.reshape(-1, w.getnchannels()).mean(axis=1)
    return raw, rate


def _write(path: Path, samples: npt.NDArray[np.float64], rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())


class DriverVoice:
    """Speaks lines one after another on a background thread (never on the UI thread)."""

    def __init__(self) -> None:
        """Muted until :attr:`enabled` is set."""
        self.enabled = False
        self._lines: queue.Queue[str] = queue.Queue()
        self._dir = Path(tempfile.mkdtemp(prefix="pitwall_voice_"))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        """Queue a line (ignored while muted or without the speech engine)."""
        if self.enabled and available():
            self._lines.put(text)

    def _run(self) -> None:
        import winsound  # noqa: PLC0415 (Windows only)

        n = 0
        while True:
            text = self._lines.get()
            n += 1
            clean, radio = self._dir / f"line{n}.wav", self._dir / f"radio{n}.wav"
            try:
                _synthesise(text, clean)
                samples, rate = _read(clean)
                _write(radio, team_radio_filter(samples, rate), rate)
                winsound.PlaySound(str(radio), winsound.SND_FILENAME)  # waits: one at a time
            except Exception:  # noqa: BLE001 (the voice is optional: text stays)
                logger.exception("driver voice failed")
