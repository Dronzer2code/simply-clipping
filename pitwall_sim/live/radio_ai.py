"""Background worker for the hosted radio LLM (hackathon H2 / H3).

LLM requests never run on the race thread or the UI thread: the session hands
:class:`RadioAI` a job (read a message, write a driver line) and returns at once.
Jobs run one at a time, in order, on a daemon thread; each LLM call inside a job
is bounded by ``radio_llm.timeout_s`` and falls back (keyword parser, template).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from pitwall_sim.config.models import RadioLlmConfig
from pitwall_sim.radio.hosted_llm import LLMProvider

logger = logging.getLogger(__name__)


class RadioAI:
    """The radio's LLM (or none) and the thread its jobs run on."""

    def __init__(self, provider: LLMProvider | None, cfg: RadioLlmConfig | None = None) -> None:
        """Use ``provider`` (None = off: keyword parser and templates only)."""
        cfg = cfg or RadioLlmConfig()
        self.provider = provider
        self.timeout_s = float(cfg.timeout_s)
        self.driver_replies = cfg.driver_replies
        self.max_words = cfg.max_reply_words
        self._jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def on(self) -> bool:
        """An LLM reads engineer messages."""
        return self.provider is not None

    @property
    def replies_on(self) -> bool:
        """An LLM writes the driver's unprompted lines."""
        return self.provider is not None and self.driver_replies

    @property
    def name(self) -> str:
        """Provider name for the radio panel ("" when off)."""
        return self.provider.name if self.provider is not None else ""

    def submit(self, job: Callable[[], None]) -> None:
        """Run ``job`` on the worker thread, after the jobs already queued."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="radio-ai")
            self._thread.start()
        self._jobs.put(job)

    def wait_idle(self, timeout_s: float = 10.0) -> bool:
        """Wait until every queued job has run (tests); return whether it did in time."""
        deadline = time.monotonic() + timeout_s
        while self._jobs.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        """Stop the worker after the queued jobs."""
        if self._thread is not None:
            self._jobs.put(None)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job is None:
                    return
                job()
            except Exception:  # noqa: BLE001 (a radio job must not kill the worker)
                logger.exception("radio LLM job failed")
            finally:
                self._jobs.task_done()
