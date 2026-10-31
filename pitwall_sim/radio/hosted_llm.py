"""Hosted LLM providers for the team radio (hackathon H2 / H3), over plain HTTPS.

Two backends behind one small interface (:class:`LLMProvider`):

- ``openai``: OpenAI-compatible Chat Completions with ``tools`` (any server that
  speaks that API, via ``base_url``);
- ``anthropic``: the Anthropic Messages API with ``tools``.

The provider only turns a prompt into text and tool calls. It never sees race
state and never changes it: callers build the prompt from public / Our Car data
and send every tool call through ``engineer.commands.validate`` (HR-07).

HTTP goes through a :class:`Transport` (``httpx`` when installed, else the
standard library), so tests use a fake transport and never touch the network.
The API key is read from the environment variable named in config and is never
logged.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pitwall_sim.config.models import RadioLlmConfig

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2026-10-21"
DEFAULT_KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
MAX_TOKENS = 1024


class LLMError(RuntimeError):
    """The provider failed (HTTP error, bad JSON, no key); the caller falls back."""


@dataclass(frozen=True)
class Tool:
    """A function the model may call: name, description, JSON schema of its input."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model made (arguments already parsed from JSON)."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMReply:
    """What the model answered: free text and tool calls (either may be empty)."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class Transport(Protocol):
    """POST a JSON body, return the decoded JSON response (raise on any failure)."""

    def post_json(self, url: str, headers: Mapping[str, str], body: Mapping[str, Any],
                  timeout_s: float) -> dict[str, Any]:  # fmt: skip
        """POST ``body``; return the JSON object answered."""
        ...


class HttpTransport:
    """``httpx`` if installed (optional extra ``[llm]``), else ``urllib``."""

    def post_json(self, url: str, headers: Mapping[str, str], body: Mapping[str, Any],
                  timeout_s: float) -> dict[str, Any]:  # fmt: skip
        """POST ``body`` as JSON; raise :class:`LLMError` on any HTTP or decode failure."""
        try:
            import httpx  # noqa: PLC0415 (optional dependency)
        except ImportError:
            return _urllib_post(url, headers, body, timeout_s)
        try:
            response = httpx.post(url, headers=dict(headers), json=dict(body), timeout=timeout_s)
        except httpx.HTTPError as exc:
            raise LLMError(f"{type(exc).__name__}") from None
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise LLMError("response is not JSON") from None
        if not isinstance(data, dict):
            raise LLMError("response is not a JSON object")
        return data


def _urllib_post(url: str, headers: Mapping[str, str], body: Mapping[str, Any],
                 timeout_s: float) -> dict[str, Any]:  # fmt: skip
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json", **headers},
    )  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise LLMError(type(exc).__name__) from None
    if not isinstance(data, dict):
        raise LLMError("response is not a JSON object")
    return data


class LLMProvider(Protocol):
    """A hosted model: one request in, text and tool calls out."""

    name: str

    def complete(self, system: str, user: str, tools: tuple[Tool, ...] = (),
                 timeout_s: float = 2.0) -> LLMReply:  # fmt: skip
        """Answer ``user`` under ``system``, optionally calling ``tools``."""
        ...


def _arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments as a dict (OpenAI sends a JSON string); bad JSON -> LLMError."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raise LLMError("tool arguments are not JSON") from None
    if not isinstance(raw, dict):
        raise LLMError("tool arguments are not an object")
    return raw


@dataclass
class OpenAIChatProvider:
    """OpenAI-compatible Chat Completions with function tools."""

    model: str
    api_key: str
    base_url: str = OPENAI_URL
    transport: Transport = field(default_factory=HttpTransport)
    name: str = "openai"

    def complete(self, system: str, user: str, tools: tuple[Tool, ...] = (),
                 timeout_s: float = 2.0) -> LLMReply:  # fmt: skip
        """Send one chat request; return the first choice's text and tool calls."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }  # fmt: skip
        if tools:
            body["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.parameters}}
                for t in tools
            ]  # fmt: skip
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        url = self.base_url.rstrip("/") + "/chat/completions"
        data = self.transport.post_json(url, headers, body, timeout_s)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("no choices in the response") from None
        calls = []
        for call in message.get("tool_calls") or ():
            function = call.get("function") or {}
            calls.append(ToolCall(str(function.get("name", "")),
                                  _arguments(function.get("arguments", "{}"))))  # fmt: skip
        return LLMReply(str(message.get("content") or ""), tuple(calls))


@dataclass
class AnthropicMessagesProvider:
    """Anthropic Messages API with client tools."""

    model: str
    api_key: str
    base_url: str = ANTHROPIC_URL
    transport: Transport = field(default_factory=HttpTransport)
    name: str = "anthropic"

    def complete(self, system: str, user: str, tools: tuple[Tool, ...] = (),
                 timeout_s: float = 2.0) -> LLMReply:  # fmt: skip
        """Send one Messages request; return its text blocks and ``tool_use`` blocks."""
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": "low"},  # a radio call, not a hard problem: fast
        }
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description,
                              "input_schema": t.parameters} for t in tools]  # fmt: skip
            body["tool_choice"] = {"type": "auto"}
        headers = {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION,
                   "content-type": "application/json"}  # fmt: skip
        url = self.base_url.rstrip("/") + "/v1/messages"
        data = self.transport.post_json(url, headers, body, timeout_s)
        if data.get("stop_reason") == "refusal":
            raise LLMError("the model declined")
        content = data.get("content")
        if not isinstance(content, list):
            raise LLMError("no content in the response")
        texts, calls = [], []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(str(block.get("name", "")),
                                      _arguments(block.get("input", {}))))  # fmt: skip
        return LLMReply(" ".join(t for t in texts if t).strip(), tuple(calls))


def make_provider(cfg: RadioLlmConfig, transport: Transport | None = None,
                  env: Mapping[str, str] | None = None) -> LLMProvider | None:  # fmt: skip
    """Build the configured provider, or None (off, no model, or no key in the env)."""
    if cfg.provider is None:
        return None
    if not cfg.model:
        logger.warning("radio_llm.provider is %s but radio_llm.model is not set: LLM off",
                       cfg.provider)  # fmt: skip
        return None
    env = os.environ if env is None else env
    key_env = cfg.api_key_env or DEFAULT_KEY_ENV[cfg.provider]
    key = env.get(key_env, "").strip()
    if not key:
        logger.warning("radio LLM off: environment variable %s is not set", key_env)
        return None
    transport = transport or HttpTransport()
    if cfg.provider == "openai":
        return OpenAIChatProvider(cfg.model, key, cfg.base_url or OPENAI_URL, transport)
    return AnthropicMessagesProvider(cfg.model, key, cfg.base_url or ANTHROPIC_URL, transport)


def call_with_timeout[R](fn: Callable[[], R], timeout_s: float) -> R:
    """Run ``fn`` on a daemon thread; raise TimeoutError after ``timeout_s`` wall seconds.

    A late answer is dropped (the thread finishes on its own); the caller falls back.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 (re-raised in the caller)
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=run, daemon=True, name="radio-llm-call").start()
    if not done.wait(timeout_s):
        raise TimeoutError(f"no answer within {timeout_s:g} s")
    if "error" in box:
        raise box["error"]
    value: R = box["value"]
    return value
