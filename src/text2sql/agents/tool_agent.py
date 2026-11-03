"""Tool-using agent: explore the schema, run SQL, read the result, revise.

Loop:
  1. The model explores with the tools in config.tool_groups (list_tables,
     describe_table, sample_rows, search_metrics, ...).
  2. It runs its query with run_sql.
  3. On an SQL error or an empty result, it sees the result plus a note and may
     revise; at most settings.max_retries revisions, then the agent stops.
  4. It ends with a short interpretation; the last run_sql result is the answer.
Tool calls go through ToolBox, so the database stays read-only.
"""
import time

from ..tools import ToolBox
from .base import AgentResult

SYSTEM = """You are a data analyst answering business questions about the Olist \
Brazilian e-commerce database. Queries run on DuckDB.

You don't know the schema yet: use the tools to find the tables and columns you \
need, and look at sample rows when you're unsure what values look like. Then \
answer with run_sql. The last query you run must be the one that answers the \
question; don't run checks after it.

If a query fails or returns no rows, read the result and fix the query. If the \
question is ambiguous, pick the most reasonable reading, say which one, and answer it.
{metrics}
Finish with one or two sentences interpreting the result. Don't repeat the table."""

METRICS_HINT = """
Business terms (revenue, customer, late delivery, ...) have official definitions. \
Look them up with search_metrics or get_metric before writing SQL that uses them.
"""

# Hard cap on model calls per question, so a confused model can't loop forever.
MAX_LLM_CALLS = 25


class ToolAgent:
    def __init__(self, config, settings, llm, con, tracer):
        if "examples" in config.tool_groups or config.use_checker:
            raise NotImplementedError(
                f"{config.name!r} needs the examples bank or the silent-error checker, which aren't built yet."
            )
        self.config, self.settings, self.llm, self.con, self.tracer = config, settings, llm, con, tracer
        self.tools = ToolBox(con, settings, config.tool_groups)
        self.system = SYSTEM.format(metrics=METRICS_HINT if "metrics" in config.tool_groups else "")

    def answer(self, question: str, question_id: str | None = None) -> AgentResult:
        self.tracer.start(question_id)
        self.tools.last_sql = self.tools.last_result = None
        start = time.perf_counter()
        result = AgentResult()
        messages = [{"role": "user", "content": question}]
        failures = 0  # run_sql calls that errored or returned no rows
        after_failure = False

        for _ in range(MAX_LLM_CALLS):
            resp = self.llm.chat(messages, tools=self.tools.specs(), system=self.system)
            result.input_tokens += resp.input_tokens
            result.output_tokens += resp.output_tokens
            result.cost_usd += resp.cost_usd
            self.tracer.log("llm", model=resp.model, stop_reason=resp.stop_reason, text=resp.text,
                            tool_calls=[c.name for c in resp.tool_calls],
                            input_tokens=resp.input_tokens, output_tokens=resp.output_tokens)
            if resp.text:
                result.text = resp.text.strip()
            if not resp.tool_calls:
                if resp.stop_reason in ("refusal", "max_tokens"):
                    result.error = resp.stop_reason
                break

            messages.append(resp.assistant_message)
            tool_results = []
            for call in resp.tool_calls:
                out, is_error = self.tools.call(call.name, call.input)
                self.tracer.log("tool", name=call.name, input=call.input, is_error=is_error, output=out[:2000])
                if call.name == "run_sql":
                    if after_failure:
                        result.retries += 1
                    qr = self.tools.last_result
                    after_failure = not qr.ok or not qr.rows
                    if after_failure:
                        failures += 1
                        left = self.settings.max_retries - failures + 1
                        out += (f"\nNo rows returned. Check filters and values with sample_rows, or say why "
                                f"empty is correct." if qr.ok else "") + f"\n({max(left, 0)} revisions left.)"
                tool_results.append({"type": "tool_result", "tool_use_id": call.id,
                                     "content": out, "is_error": is_error})
            messages.append({"role": "user", "content": tool_results})
            if failures > self.settings.max_retries:
                break
        else:
            result.error = "step limit"

        qr = self.tools.last_result
        result.sql = self.tools.last_sql
        if qr is None:
            result.error = result.error or "no SQL run"
        else:
            result.columns, result.rows, result.truncated = qr.columns, qr.rows, qr.truncated
            result.error = result.error or qr.error
        result.latency_s = time.perf_counter() - start
        result.steps = list(self.tracer.steps)
        return result
