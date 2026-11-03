"""Tool-using agent (stub; implemented in the next task).

Planned loop, up to settings.max_retries revisions:
  1. The model explores with the tools in config.tool_groups (list_tables,
     describe_table, sample_rows, search_metrics, ...).
  2. It runs its query with run_sql.
  3. On an SQL error or an empty result, it reads the result and revises.
     With config.use_checker, silent-error checker findings are fed back the same way.
  4. It ends with a short interpretation; the last run_sql result is the answer.
Tool calls go through ToolBox, so the database stays read-only.
"""
from ..tools import ToolBox
from .base import AgentResult


class ToolAgent:
    def __init__(self, config, settings, llm, con, tracer):
        self.config, self.settings, self.llm, self.con, self.tracer = config, settings, llm, con, tracer
        groups = tuple(g for g in config.tool_groups if g != "examples")  # examples bank not built yet
        self.tools = ToolBox(con, settings, groups)

    def answer(self, question: str, question_id: str | None = None) -> AgentResult:
        raise NotImplementedError(f"{self.config.name!r} agent is not implemented yet; use 'baseline'.")
