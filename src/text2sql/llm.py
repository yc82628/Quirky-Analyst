"""Thin LLM wrapper: the one place that knows about the provider SDK.

Agents build messages in the Anthropic Messages format and call
`llm.chat(messages, tools, system)`. To try another provider, add a class with
the same `chat` method that translates to and from that format.
Tests use a fake with the same interface, so they need no API key.
"""
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import cost_usd

# Server-side refusal fallback: if a model declines, the API retries on another
# model inside the same call. The serving model is recorded in LLMResponse.model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # Append this to `messages` to continue the conversation (keeps thinking blocks intact).
    assistant_message: dict[str, Any] = field(default_factory=dict)


class LLM(Protocol):
    model: str

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             system: str | None = None) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(self, model: str, effort: str = "high", api_key: str | None = None,
                 max_tokens: int = 16000):
        import anthropic

        # With no key given, the SDK reads ANTHROPIC_API_KEY or an `ant auth login` profile.
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def chat(self, messages, tools=None, system=None) -> LLMResponse:
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            # Own breakpoint so the system prompt (schema) is cached across questions.
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if tools:
            kwargs["tools"] = tools
        if self.model in FALLBACK_MODELS:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        resp = self.client.beta.messages.create(**kwargs)

        u = resp.usage
        cache_write = u.cache_creation_input_tokens or 0
        cache_read = u.cache_read_input_tokens or 0
        return LLMResponse(
            text="".join(b.text for b in resp.content if b.type == "text"),
            tool_calls=[ToolCall(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"],
            stop_reason=resp.stop_reason,
            model=resp.model,
            input_tokens=u.input_tokens + cache_write + cache_read,
            output_tokens=u.output_tokens,
            cost_usd=cost_usd(resp.model, u.input_tokens, u.output_tokens, cache_write, cache_read),
            assistant_message={"role": "assistant", "content": resp.content},
        )
