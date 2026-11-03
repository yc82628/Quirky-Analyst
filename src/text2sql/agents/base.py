"""Agent interface, result type, and the experiment configs.

Each row of the results table is an AgentConfig, not a separate code path.
"""
from dataclasses import dataclass, field
from typing import Protocol

from ..config import Settings
from ..db import connect
from ..trace import Tracer


@dataclass
class AgentResult:
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    text: str = ""
    steps: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    retries: int = 0
    error: str | None = None
    truncated: bool = False


class Agent(Protocol):
    config: "AgentConfig"

    def answer(self, question: str, question_id: str | None = None) -> AgentResult: ...


@dataclass(frozen=True)
class AgentConfig:
    name: str
    kind: str  # "baseline" or "tool"
    tool_groups: tuple[str, ...] = ()
    use_checker: bool = False


EXPERIMENTS = {
    c.name: c
    for c in [
        AgentConfig("baseline", "baseline"),
        AgentConfig("tools", "tool", ("schema",)),
        AgentConfig("tools+metrics", "tool", ("schema", "metrics")),
        AgentConfig("tools+metrics+examples", "tool", ("schema", "metrics", "examples")),
        AgentConfig("tools+metrics+examples+checker", "tool", ("schema", "metrics", "examples"), use_checker=True),
    ]
}


def build_agent(name: str, settings: Settings, llm=None, tracer: Tracer | None = None, con=None) -> Agent:
    """Create the agent for one experiment. llm defaults to the configured provider."""
    config = EXPERIMENTS[name]
    if llm is None:
        from ..llm import AnthropicLLM

        llm = AnthropicLLM(settings.model, settings.effort, settings.api_key)
    con = con or connect(settings.db_path)
    tracer = tracer or Tracer()
    if config.kind == "baseline":
        from .baseline import BaselineAgent

        return BaselineAgent(config, settings, llm, con, tracer)
    from .tool_agent import ToolAgent

    return ToolAgent(config, settings, llm, con, tracer)
