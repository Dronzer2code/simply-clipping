"""Hackathon H2/H3: hosted LLM providers, tool calls, reply fact check, voice input (no network)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import numpy as np
import pytest

from pitwall_sim.config.models import Compound, EngineerConfig, RadioLlmConfig
from pitwall_sim.engineer.commands import CommandContext, CommandType, validate
from pitwall_sim.radio import stt
from pitwall_sim.radio.hosted_llm import (
    ANTHROPIC_VERSION,
    AnthropicMessagesProvider,
    LLMError,
    LLMReply,
    OpenAIChatProvider,
    Tool,
    ToolCall,
    make_provider,
)
from pitwall_sim.radio.llm_commands import interpret, to_result, tools
from pitwall_sim.radio.llm_replies import fact_check, write_reply

CTX = CommandContext(
    lap=5, race_laps=15, zone_ids=frozenset({"SM1", "SM2"}), overtake_zone_ids=frozenset({"OT1"}),
    corner_ids=frozenset({"T1", "T11", "T15"}),
    compounds=frozenset({Compound.SOFT, Compound.MEDIUM, Compound.HARD}),
)  # fmt: skip
CFG = EngineerConfig(let_teammate_by_gap_s=1.0, push_lap_max_laps=3)
TOOL = Tool("DEFEND", "Defend.", {"type": "object", "properties": {}})


class _FakeTransport:
    """Records the request and answers with a canned JSON body."""

    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, str], dict[str, Any], float]] = []

    def post_json(self, url: str, headers: Mapping[str, str], body: Mapping[str, Any],
                  timeout_s: float) -> dict[str, Any]:  # fmt: skip
        self.calls.append((url, dict(headers), dict(body), timeout_s))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class _FakeProvider:
    """An LLM that answers with a fixed reply after ``delay_s`` (or raises)."""

    name = "fake"

    def __init__(self, reply: LLMReply | Exception, delay_s: float = 0.0) -> None:
        self.reply = reply
        self.delay_s = delay_s
        self.prompts: list[tuple[str, str, tuple[Tool, ...]]] = []

    def complete(self, system: str, user: str, tools: tuple[Tool, ...] = (),
                 timeout_s: float = 2.0) -> LLMReply:  # fmt: skip
        self.prompts.append((system, user, tools))
        time.sleep(self.delay_s)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


# --------------------------------------------------------------------------- providers


def test_openai_provider_sends_tools_and_reads_tool_calls() -> None:
    answer = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "1", "type": "function",
         "function": {"name": "DEFEND", "arguments": json.dumps({"corner_id": "T11"})}},
        {"id": "2", "type": "function", "function": {"name": "ATTACK", "arguments": "{}"}},
    ]}}]}  # fmt: skip
    transport = _FakeTransport(answer)
    provider = OpenAIChatProvider("PLACEHOLDER-model", "sk-test", transport=transport)
    reply = provider.complete("sys", "user", (TOOL,), 2.0)
    assert reply.tool_calls == (ToolCall("DEFEND", {"corner_id": "T11"}), ToolCall("ATTACK", {}))
    url, headers, body, timeout = transport.calls[0]
    assert url == "https://api.openai.com/v1/chat/completions" and timeout == 2.0
    assert headers["Authorization"] == "Bearer sk-test"
    assert body["tools"][0] == {"type": "function", "function": {
        "name": "DEFEND", "description": "Defend.", "parameters": TOOL.parameters}}  # fmt: skip
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_anthropic_provider_sends_tools_and_reads_tool_use_blocks() -> None:
    answer = {"stop_reason": "tool_use", "content": [
        {"type": "thinking", "thinking": ""},
        {"type": "text", "text": "Copy."},
        {"type": "tool_use", "id": "t1", "name": "DEFEND", "input": {"corner_id": "T11"}},
    ]}  # fmt: skip
    transport = _FakeTransport(answer)
    provider = AnthropicMessagesProvider("claude-haiku-5-5", "key", transport=transport)
    reply = provider.complete("sys", "user", (TOOL,), 2.0)
    assert reply == LLMReply("Copy.", (ToolCall("DEFEND", {"corner_id": "T11"}),))
    url, headers, body, _ = transport.calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "key" and headers["anthropic-version"] == ANTHROPIC_VERSION
    assert body["system"] == "sys" and body["tools"][0]["input_schema"] == TOOL.parameters
    assert "temperature" not in body


def test_bad_tool_arguments_and_refusals_are_errors() -> None:
    bad = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "ATTACK", "arguments": "{not json"}}]}}]}  # fmt: skip
    with pytest.raises(LLMError):
        OpenAIChatProvider("m", "k", transport=_FakeTransport(bad)).complete("s", "u")
    refusal = {"stop_reason": "refusal", "content": []}
    with pytest.raises(LLMError):
        AnthropicMessagesProvider("m", "k", transport=_FakeTransport(refusal)).complete("s", "u")


def test_make_provider_off_without_provider_model_or_key() -> None:
    assert make_provider(RadioLlmConfig()) is None  # default: off
    cfg = RadioLlmConfig(provider="anthropic", model="claude-haiku-5-5")
    assert make_provider(cfg, env={}) is None  # no key in the environment
    provider = make_provider(cfg, env={"ANTHROPIC_API_KEY": "k"})
    assert isinstance(provider, AnthropicMessagesProvider)
    assert make_provider(RadioLlmConfig(provider="openai"), env={"OPENAI_API_KEY": "k"}) is None
    custom = RadioLlmConfig(provider="openai", model="m", api_key_env="MY_KEY",
                            base_url="http://localhost:8080/v1")  # fmt: skip
    openai = make_provider(custom, env={"MY_KEY": "k"})
    assert isinstance(openai, OpenAIChatProvider) and openai.base_url == "http://localhost:8080/v1"


def test_the_key_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    cfg = RadioLlmConfig(provider="anthropic", model="m")
    transport = _FakeTransport(LLMError("HTTP 401"))
    provider = make_provider(cfg, transport, env={"ANTHROPIC_API_KEY": "sk-secret-123"})
    assert provider is not None
    with caplog.at_level("DEBUG"):
        assert interpret(provider, "u", (), 1.0) is None
    assert "sk-secret-123" not in caplog.text


# --------------------------------------------------------------------------- commands


def test_tools_cover_every_command_type_with_its_parameters() -> None:
    tool_set = {t.name: t for t in tools(CTX, CFG)}
    assert set(tool_set) == {str(k) for k in CommandType}
    box = tool_set["BOX"].parameters
    assert box["required"] == ["lap", "compound"]
    assert box["properties"]["compound"]["enum"] == ["HARD", "MEDIUM", "SOFT"]
    assert tool_set["DEFEND"].parameters["properties"]["corner_id"]["enum"] == ["T1", "T11", "T15"]
    assert tool_set["PUSH_LAP"].parameters["properties"]["laps"]["maximum"] == 3


def test_tool_calls_become_validated_commands() -> None:
    """Free phrasing -> DEFEND T11 now, ATTACK next lap; each passes commands.validate."""
    calls = (ToolCall("DEFEND", {"corner_id": "T11", "when": "now"}),
             ToolCall("ATTACK", {"when": "next_lap"}),
             ToolCall("BOX", {"lap": 7, "compound": "HARD", "when": "next_lap"}))  # fmt: skip
    result = to_result(calls)
    assert [(c.kind, c.params, c.when) for c in result.commands] == [
        (CommandType.DEFEND, {"corner_id": "T11"}, "now"),
        (CommandType.ATTACK, {}, "next_lap"),
        (CommandType.BOX, {"lap": 7, "compound": "HARD"}, "now"),  # the lap says when
    ]
    assert result.ack == "Copy, defending T11, attacking next lap, boxing lap 7, hards."
    assert all(validate(c.kind, c.params, CTX, CFG).ok for c in result.commands)


def test_invalid_llm_output_is_rejected_by_validate() -> None:
    result = to_result((ToolCall("FLY", {}), ToolCall("DEFEND", {"corner_id": "T99"}),
                        ToolCall("BOX", {"lap": 2, "compound": "PURPLE"}),
                        ToolCall("ATTACK", {"corner_id": "T1"})))  # fmt: skip
    assert result.unknown == ("FLY",)
    checks = [validate(c.kind, c.params, CTX, CFG) for c in result.commands]
    assert not any(c.ok for c in checks)
    assert "no corner T99" in str(checks[0].reason)
    assert "unknown parameter" in str(checks[2].reason)


def test_interpret_falls_back_on_timeout_error_and_no_tools() -> None:
    good = LLMReply("", (ToolCall("ATTACK", {}),))
    assert interpret(_FakeProvider(good), "u", (), 1.0) is not None
    started = time.monotonic()
    assert interpret(_FakeProvider(good, delay_s=1.0), "u", (), 0.1) is None  # timeout
    assert time.monotonic() - started < 0.5  # the caller does not wait for the late answer
    assert interpret(_FakeProvider(LLMError("HTTP 500")), "u", (), 1.0) is None
    assert interpret(_FakeProvider(LLMReply("Nice weather.")), "u", (), 1.0) is None
    assert interpret(_FakeProvider(LLMReply("", (ToolCall("FLY", {}),))), "u", (), 1.0) is None


# --------------------------------------------------------------------------- replies

FACTS = {"message": "Tyres are going, 74% worn.", "lap": "8", "race_laps": "15",
         "battery_mj": "2.1", "tyre_wear_pct": "74", "tyre_age_laps": "9",
         "compound": "MEDIUM", "energy_mode": "BALANCED", "position": "P6"}  # fmt: skip


def test_fact_check_accepts_a_true_short_line() -> None:
    assert fact_check("These mediums are done, 74 percent gone, still P6.", FACTS) is None


def test_fact_check_rejects_wrong_numbers_tyres_direction_and_length() -> None:
    assert "80" in str(fact_check("Mediums are 80% gone.", FACTS))
    assert "number" in str(fact_check("Two laps left on these.", FACTS))  # number words too
    assert "tyre" in str(fact_check("The softs are finished.", FACTS))
    long = "mate " * 21
    assert "20 words" in str(fact_check(long.strip(), FACTS))
    up = {**FACTS, "message": "Up to P5.", "position": "P5"}
    assert "lost" in str(fact_check("Damn, down to P5.", up))
    assert fact_check("Yes! Up to P5.", up) is None


def test_write_reply_uses_the_llm_only_when_the_facts_hold() -> None:
    ok = _FakeProvider(LLMReply('"Tyres are cooked, 74 percent."'))
    assert write_reply(ok, FACTS, 1.0) == "Tyres are cooked, 74 percent."
    system, user, tool_set = ok.prompts[0]
    assert "20 words" in system and "tyre_wear_pct: 74" in user and tool_set == ()
    assert write_reply(_FakeProvider(LLMReply("Tyres at 90%.")), FACTS, 1.0) is None
    assert write_reply(_FakeProvider(LLMReply("ok"), delay_s=1.0), FACTS, 0.1) is None
    assert write_reply(_FakeProvider(LLMError("HTTP 429")), FACTS, 1.0) is None


# --------------------------------------------------------------------------- voice input


class _FakeRecorder:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> tuple[Any, int]:
        return np.zeros(48000, np.float32), 48000


class _FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.rates: list[int] = []

    def transcribe(self, samples: Any, rate: int) -> str:
        self.rates.append(rate)
        return self.text


def test_push_to_talk_transcribes_on_a_worker() -> None:
    heard: list[str] = []
    errors: list[str] = []
    ptt = stt.PushToTalk(_FakeTranscriber(" box box, mediums "), _FakeRecorder(), heard.append,
                         errors.append)  # fmt: skip
    assert ptt.press() and ptt.recording
    assert not ptt.press()  # held: one recording
    ptt.release()
    ptt.wait()
    assert heard == ["box box, mediums"] and errors == []
    silent = stt.PushToTalk(_FakeTranscriber(""), _FakeRecorder(), heard.append, errors.append)
    silent.press()
    silent.release()
    silent.wait()
    assert errors == ["nothing heard"]


def test_voice_disabled_cleanly_without_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt.importlib.util, "find_spec", lambda name: None)
    ok, why = stt.status()
    assert not ok and "faster_whisper" in why and "type instead" in why


def test_resample_to_16k() -> None:
    out = stt.resample(np.zeros((44100, 2)), 44100)
    assert out.dtype == np.float32 and out.shape == (16000,)
