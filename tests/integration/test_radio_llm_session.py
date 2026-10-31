"""Hackathon H2/H3 in the live session: LLM -> keyword parser -> "Say again?", LLM driver lines."""

from __future__ import annotations

import time
from pathlib import Path

from pitwall_sim.config.models import RadioLlmConfig
from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.live.radio_ai import RadioAI
from pitwall_sim.live.session import LiveSession, LiveSetup
from pitwall_sim.radio import stt
from pitwall_sim.radio.hosted_llm import LLMError, LLMReply, Tool, ToolCall

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
FAST = RadioLlmConfig(timeout_s=0.3)


class _FakeProvider:
    name = "fake"

    def __init__(self, *replies: LLMReply | Exception, delay_s: float = 0.0) -> None:
        self.replies = list(replies)
        self.delay_s = delay_s
        self.prompts: list[str] = []

    def complete(self, system: str, user: str, tools: tuple[Tool, ...] = (),
                 timeout_s: float = 2.0) -> LLMReply:  # fmt: skip
        self.prompts.append(user)
        time.sleep(self.delay_s)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _session(provider: _FakeProvider | None) -> LiveSession:
    s = LiveSession(LiveSetup(our_driver_id="HAM", laps=4), CONFIG_DIR)
    s.advance(20.0)
    s.radio_ai = RadioAI(provider, FAST)
    return s


def _driver(s: LiveSession) -> list[str]:
    return [e.text for e in s.frame().view.radio_log if e.sender == "DRIVER"]


def test_llm_tool_calls_become_validated_commands() -> None:
    llm = _FakeProvider(LLMReply("", (ToolCall("DEFEND", {"corner_id": "T11"}),
                                     ToolCall("ATTACK", {"when": "next_lap"}))))  # fmt: skip
    s = _session(llm)
    s.radio_send("hold him off till the hairpin then go for it into 130R")
    assert s.radio_ai.wait_idle()
    sent = s.engine.pending_commands + s.engine.applied_commands
    assert [(c.type, c.params) for c in sent] == [(CommandType.DEFEND, {"corner_id": "T11"})]
    assert [r.option_label for r in s.call_log] == ["radio: DEFEND", "radio: ATTACK (next lap)"]
    assert s.radio_path == "LLM"
    prompt = llm.prompts[0]
    assert "hold him off" in prompt and "T11 = Turn 11 (hairpin, the hairpin)" in prompt
    assert "battery" in prompt and "130R" in prompt
    s.advance(3.0)
    assert _driver(s)[-1] == "Copy, defending T11, attacking next lap."


def test_invalid_llm_command_is_rejected_by_validation() -> None:
    s = _session(_FakeProvider(LLMReply("", (ToolCall("BOX", {"lap": 3, "compound": "PURPLE"}),))))
    s.radio_send("box for the purple ones")
    assert s.radio_ai.wait_idle()
    assert s.call_log == [] and not s.engine.pending_commands
    assert any(line.rejected and "compound must be one of" in line.text for line in s.radio)


def test_llm_timeout_or_error_falls_back_to_the_keyword_parser() -> None:
    slow = _FakeProvider(LLMReply("", (ToolCall("ATTACK", {}),)), delay_s=1.0)
    s = _session(slow)
    started = time.monotonic()
    s.radio_send("push")
    assert time.monotonic() - started < 0.2  # the caller never waits for the LLM
    assert s.radio_path == "LLM ..."
    assert s.radio_ai.wait_idle()
    assert [r.option_label for r in s.call_log] == ["radio: SET_ENERGY_MODE"]  # keyword parser
    assert s.radio_path == "KEYWORD"
    s.radio_ai = RadioAI(_FakeProvider(LLMError("HTTP 500")), FAST)
    s.radio_send("harvest", source="VOICE")
    assert s.radio_ai.wait_idle()
    assert s.radio_path == "VOICE > KEYWORD" and len(s.call_log) == 2


def test_nothing_understood_says_again() -> None:
    s = _session(_FakeProvider(LLMReply("No idea.")))
    s.radio_send("banana smoothie")
    assert s.radio_ai.wait_idle()
    s.advance(3.0)
    assert s.radio_path == "SAY AGAIN" and s.call_log == []
    assert _driver(s)[-1] == "Say again?"


def test_llm_off_is_the_keyword_parser_now() -> None:
    s = _session(None)
    s.radio_send("push")
    assert [r.option_label for r in s.call_log] == ["radio: SET_ENERGY_MODE"]  # synchronous
    assert s.radio_path == "KEYWORD"


def test_driver_lines_llm_written_when_true_else_template() -> None:
    s = _session(_FakeProvider(LLMReply("Up we go, P3 now!"), LLMReply("Up to P9, brilliant.")))
    view = s.frame().view
    s._driver_line("Up to P3.", view)
    s._driver_line("Up to P3.", view)  # the LLM says P9: wrong number -> template
    assert s.radio_ai.wait_idle()
    s.advance(0.1)  # the next view carries the new radio events
    events = [e for e in s.frame().view.radio_log if e.sender == "DRIVER"][-2:]
    assert [(e.text, e.source, e.is_fallback) for e in events] == [
        ("Up we go, P3 now!", "LLM", False), ("Up to P3.", "TEMPLATE", True)]  # fmt: skip


def test_fake_transcriber_feeds_the_radio_pipeline() -> None:
    s = _session(None)

    class Recorder:
        def start(self) -> None: ...

        def stop(self) -> tuple[stt.Samples, int]:
            import numpy as np

            return np.zeros(16000, np.float32), 16000

    class Transcriber:
        def transcribe(self, samples: stt.Samples, rate: int) -> str:
            return "Box box, mediums"

    ptt = stt.PushToTalk(Transcriber(), Recorder(), lambda text: s.radio_send(text, "VOICE"))
    ptt.press()
    ptt.release()
    ptt.wait()
    assert [r.option_label for r in s.call_log] == ["radio: BOX"]
    s.advance(0.1)
    engineer = [e for e in s.frame().view.radio_log if e.sender == "ENGINEER"]
    assert engineer[-1].source == "VOICE" and engineer[-1].text == "Box box, mediums"
    assert s.radio_path == "VOICE > KEYWORD"
