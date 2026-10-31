"""Push-to-talk speech-to-text for the team radio (hackathon H2), local and offline.

Hold the button (or the key) -> :class:`PushToTalk` records the microphone
(``sounddevice``) -> release -> a worker thread transcribes it with
faster-whisper (CPU, int8; the model is downloaded once into ``models/stt``) ->
the text goes into the same pipeline as typed radio. Nothing here runs on the UI
or race thread.

Optional: the ``[voice]`` extra (faster-whisper, sounddevice) and a microphone.
Without them :func:`status` says why and the UI disables the button; typing
stays the fallback.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)
WHISPER_RATE_HZ = 16000
PACKAGES = ("faster_whisper", "sounddevice")
RADIO_WORDS = (
    "Box box. Push. Harvest. Save energy. Overtake mode. Attack. Defend. Hold position. "
    "Lift and coast. Softs, mediums, hards, inters. Next lap. "
)
"""Prompt that steers the recogniser to team-radio words (plus the track's corners)."""

type Samples = npt.NDArray[np.float32]


class Transcriber(Protocol):
    """Speech (mono float32 at ``rate``) -> text."""

    def transcribe(self, samples: Samples, rate: int) -> str:
        """Return the words spoken."""
        ...


class Recorder(Protocol):
    """Records between :meth:`start` and :meth:`stop`."""

    def start(self) -> None:
        """Start recording."""
        ...

    def stop(self) -> tuple[Samples, int]:
        """Stop; return the samples and their rate."""
        ...


def missing_packages() -> list[str]:
    """Return the optional voice packages that are not installed."""
    return [p for p in PACKAGES if importlib.util.find_spec(p) is None]


def status() -> tuple[bool, str]:
    """Whether push-to-talk can work here, and why not (for the button tooltip)."""
    missing = missing_packages()
    if missing:
        return False, (f"Voice input needs {', '.join(missing)} "
                       '(pip install -e ".[voice]"); type instead')  # fmt: skip
    try:
        import sounddevice as sd  # noqa: PLC0415 (optional)

        device = sd.query_devices(kind="input")
    except Exception as exc:  # noqa: BLE001 (no PortAudio, no device)
        return False, f"No microphone ({type(exc).__name__}); type instead"
    if not device or int(device.get("max_input_channels", 0)) < 1:
        return False, "No microphone; type instead"
    return True, f"Hold to talk ({device.get('name', 'microphone')})"


def resample(samples: npt.NDArray[np.floating[Any]], rate: int,
             target: int = WHISPER_RATE_HZ) -> Samples:  # fmt: skip
    """Mono float32 at ``target`` Hz."""
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if rate == target or data.size == 0:
        return data.astype(np.float32)
    from math import gcd  # noqa: PLC0415

    from scipy.signal import resample_poly  # noqa: PLC0415

    k = gcd(int(rate), int(target))
    out = resample_poly(data, target // k, int(rate) // k)
    return np.asarray(out, dtype=np.float32)


class WhisperTranscriber:
    """faster-whisper on the CPU; the model loads on first use (or :meth:`load`)."""

    def __init__(self, model: str = "base.en", model_dir: Path | str = "models/stt",
                 compute_type: str = "int8", prompt: str = RADIO_WORDS) -> None:  # fmt: skip
        """Remember the settings; nothing is loaded yet."""
        self.model_name = model
        self.model_dir = Path(model_dir)
        self.compute_type = compute_type
        self.prompt = prompt
        self._model: Any = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load (and on first use download) the model."""
        with self._lock:
            if self._model is None:
                # The Hub's xet download stalled on the target machine; plain HTTPS works.
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
                from faster_whisper import WhisperModel  # noqa: PLC0415 (optional)

                self.model_dir.mkdir(parents=True, exist_ok=True)
                self._model = WhisperModel(self.model_name, device="cpu",
                                           compute_type=self.compute_type,
                                           download_root=str(self.model_dir))  # fmt: skip

    def transcribe(self, samples: Samples, rate: int) -> str:
        """Recognise English speech; "" for silence."""
        self.load()
        audio = resample(samples, rate)
        if audio.size < WHISPER_RATE_HZ // 4:  # under 0.25 s: a click, not a message
            return ""
        segments, _ = self._model.transcribe(audio, language="en", beam_size=1,
                                             initial_prompt=self.prompt,
                                             condition_on_previous_text=False,
                                             vad_filter=False)  # fmt: skip
        return " ".join(s.text.strip() for s in segments).strip()


class SoundDeviceRecorder:
    """Microphone input via ``sounddevice`` at the device's own rate, mono."""

    def __init__(self, max_s: float = 15.0) -> None:
        """Collect at most ``max_s`` seconds per recording."""
        self.max_s = max_s
        self._chunks: list[Samples] = []
        self._stream: Any = None
        self._rate = WHISPER_RATE_HZ
        self._frames = 0

    def start(self) -> None:
        """Open the default input and start collecting."""
        import sounddevice as sd  # noqa: PLC0415 (optional)

        self._chunks, self._frames = [], 0
        self._rate = int(sd.query_devices(kind="input")["default_samplerate"])

        def collect(data: Any, frames: int, _time: Any, _status: Any) -> None:
            if self._frames < self.max_s * self._rate:
                self._chunks.append(np.array(data[:, 0], dtype=np.float32))
                self._frames += frames

        self._stream = sd.InputStream(samplerate=self._rate, channels=1, dtype="float32",
                                      callback=collect)  # fmt: skip
        self._stream.start()

    def stop(self) -> tuple[Samples, int]:
        """Close the input; return the samples and their rate."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        data = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        return data, self._rate


class PushToTalk:
    """Hold to record, release to transcribe on a worker; ``on_text`` gets the words.

    ``on_text`` / ``on_error`` are called on the worker thread (a Qt caller hands
    them to the UI thread with a signal).
    """

    def __init__(self, transcriber: Transcriber, recorder: Recorder,
                 on_text: Callable[[str], None],
                 on_error: Callable[[str], None] | None = None) -> None:  # fmt: skip
        """Nothing records until :meth:`press`."""
        self.transcriber = transcriber
        self.recorder = recorder
        self.on_text = on_text
        self.on_error = on_error or (lambda message: logger.warning("voice: %s", message))
        self.recording = False
        self._threads: list[threading.Thread] = []

    def press(self) -> bool:
        """Start recording (ignored while already recording); return whether it started."""
        if self.recording:
            return False
        try:
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001 (no microphone after all)
            self.on_error(f"microphone failed ({type(exc).__name__})")
            return False
        self.recording = True
        return True

    def release(self) -> None:
        """Stop recording and transcribe in the background."""
        if not self.recording:
            return
        self.recording = False
        try:
            samples, rate = self.recorder.stop()
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"microphone failed ({type(exc).__name__})")
            return
        thread = threading.Thread(target=self._transcribe, args=(samples, rate), daemon=True,
                                  name="radio-stt")  # fmt: skip
        self._threads.append(thread)
        thread.start()

    def preload(self) -> None:
        """Load the speech model in the background so the first message is quick."""
        load = getattr(self.transcriber, "load", None)
        if callable(load):
            threading.Thread(target=self._safe(load), daemon=True, name="radio-stt-load").start()

    def wait(self, timeout_s: float = 30.0) -> None:
        """Wait for running transcriptions (tests)."""
        for thread in list(self._threads):
            thread.join(timeout_s)

    def _safe(self, fn: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                self.on_error(f"speech model failed to load ({type(exc).__name__})")

        return run

    def _transcribe(self, samples: Samples, rate: int) -> None:
        try:
            text = self.transcriber.transcribe(samples, rate).strip()
        except Exception as exc:  # noqa: BLE001 (voice is optional: typing stays)
            self.on_error(f"transcription failed ({type(exc).__name__})")
            return
        if text:
            self.on_text(text)
        else:
            self.on_error("nothing heard")
