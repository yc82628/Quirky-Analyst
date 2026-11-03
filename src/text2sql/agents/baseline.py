"""Baseline: the full schema in one prompt, one SQL query, no tools, no retry."""
import re
import time

from ..db import run_sql
from ..schema import full_schema_text
from .base import AgentResult

SYSTEM = """You are a data analyst answering business questions about the Olist \
Brazilian e-commerce database. Queries run on DuckDB.

Database schema:

{schema}

Reply with one or two sentences on your approach, then exactly one SQL query in a \
```sql code block. If the question is ambiguous, say which reading you chose \
before the query."""

SQL_BLOCK = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str | None:
    blocks = SQL_BLOCK.findall(text)
    return blocks[-1].strip().rstrip(";").strip() if blocks else None


class BaselineAgent:
    def __init__(self, config, settings, llm, con, tracer):
        self.config, self.settings, self.llm, self.con, self.tracer = config, settings, llm, con, tracer
        self.system = SYSTEM.format(schema=full_schema_text(con))

    def answer(self, question: str, question_id: str | None = None) -> AgentResult:
        self.tracer.start(question_id)
        start = time.perf_counter()
        resp = self.llm.chat([{"role": "user", "content": question}], system=self.system)
        self.tracer.log("llm", model=resp.model, stop_reason=resp.stop_reason, text=resp.text,
                        input_tokens=resp.input_tokens, output_tokens=resp.output_tokens)

        sql = extract_sql(resp.text)
        text = SQL_BLOCK.sub("", resp.text).strip()
        result = AgentResult(sql=sql, text=text, input_tokens=resp.input_tokens,
                             output_tokens=resp.output_tokens, cost_usd=resp.cost_usd)
        if sql is None:
            result.error = "refusal" if resp.stop_reason == "refusal" else "no SQL in response"
        else:
            qr = run_sql(self.con, sql, self.settings.row_limit, self.settings.timeout_s)
            self.tracer.log("sql", sql=sql, error=qr.error, row_count=len(qr.rows), elapsed_s=qr.elapsed_s)
            result.columns, result.rows, result.error, result.truncated = qr.columns, qr.rows, qr.error, qr.truncated
        result.latency_s = time.perf_counter() - start
        result.steps = list(self.tracer.steps)
        return result
