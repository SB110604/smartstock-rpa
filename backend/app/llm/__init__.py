"""LLM provider abstraction (spec 2 / 7.8). LLM_PROVIDER = none | ollama | anthropic | openai.

Every caller must have a rule-based fallback: `get_provider()` returns None when LLM_PROVIDER=none, and any provider
error raises LLMError so callers can fall back. The LLM never touches the database — it only sees tool results."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings as env
from app.core.logging import log_ctx

logger = logging.getLogger("app.llm")


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # provider-native assistant message, appended back to the conversation for tool loops


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


class Provider:
    name = "base"

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[Tool] | None = None) -> Reply:
        raise NotImplementedError

    def tool_result_messages(self, reply: Reply, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        """Messages that feed tool outputs back to the model after `reply`."""
        raise NotImplementedError

    def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=env.LLM_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name} unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise LLMError(f"{self.name} error {r.status_code}: {r.text[:300]}")
        return r.json()


class AnthropicProvider(Provider):
    name = "anthropic"

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[Tool] | None = None) -> Reply:
        body: dict[str, Any] = {"model": env.ANTHROPIC_MODEL, "max_tokens": 1024, "system": system, "messages": messages}
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        data = self._post("https://api.anthropic.com/v1/messages", body,
                          {"x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in data.get("content", []) if b.get("type") == "tool_use"]
        return Reply(text.strip(), calls, {"role": "assistant", "content": data.get("content", [])})

    def tool_result_messages(self, reply: Reply, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [reply.raw, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": c.id, "content": out}
                                                         for c, out in results]}]


class OpenAIProvider(Provider):
    name = "openai"

    def _url(self) -> str:
        return f"{env.OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {env.OPENAI_API_KEY}"}

    def _model(self) -> str:
        return env.OPENAI_MODEL

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[Tool] | None = None) -> Reply:
        body: dict[str, Any] = {"model": self._model(), "messages": [{"role": "system", "content": system}, *messages]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        data = self._post(self._url(), body, self._headers())
        msg = data["choices"][0]["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            args = c["function"].get("arguments") or "{}"
            calls.append(ToolCall(c.get("id", c["function"]["name"]), c["function"]["name"],
                                  json.loads(args) if isinstance(args, str) else args))
        return Reply((msg.get("content") or "").strip(), calls, msg)

    def tool_result_messages(self, reply: Reply, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [reply.raw, *[{"role": "tool", "tool_call_id": c.id, "content": out} for c, out in results]]


class OllamaProvider(OpenAIProvider):
    name = "ollama"

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[Tool] | None = None) -> Reply:
        body: dict[str, Any] = {"model": env.OLLAMA_MODEL, "stream": False,
                                "messages": [{"role": "system", "content": system}, *messages]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        data = self._post(f"{env.OLLAMA_BASE_URL.rstrip('/')}/api/chat", body, {})
        msg = data.get("message", {})
        calls = [ToolCall(f"call_{i}", c["function"]["name"], c["function"].get("arguments") or {})
                 for i, c in enumerate(msg.get("tool_calls") or [])]
        return Reply((msg.get("content") or "").strip(), calls, msg)


def get_provider() -> Provider | None:
    p = env.LLM_PROVIDER
    if p == "anthropic" and env.ANTHROPIC_API_KEY and env.ANTHROPIC_MODEL:
        return AnthropicProvider()
    if p == "openai" and env.OPENAI_API_KEY:
        return OpenAIProvider()
    if p == "ollama":
        return OllamaProvider()
    return None


def status() -> dict[str, Any]:
    p = env.LLM_PROVIDER
    configured = get_provider() is not None
    model = {"anthropic": env.ANTHROPIC_MODEL, "openai": env.OPENAI_MODEL, "ollama": env.OLLAMA_MODEL}.get(p)
    return {"provider": p, "configured": configured, "model": model if configured else None,
            "fallback": "rule-based" if not configured else "rule-based on error"}


def polish(text: str, context: str = "") -> str:
    """Rewrite an agent explanation in clear, short business English; falls back to the template sentence."""
    provider = get_provider()
    if provider is None:
        return text
    try:
        reply = provider.chat(
            "You rewrite inventory reorder explanations for a store manager. Keep every number exactly as given, "
            "keep it under 60 words, plain English, no markdown.",
            [{"role": "user", "content": f"{context}\n\nExplanation: {text}"}],
        )
        out = reply.text.strip()
        return out if 20 <= len(out) <= 600 else text
    except (LLMError, KeyError, ValueError) as exc:
        logger.warning("llm polish failed, using template", extra=log_ctx(error=str(exc)))
        return text
