"""Tool specs (JSON schema) the agent can call, and the dispatcher that runs them.

Tools come in groups so each experiment is a config switch:
  schema  - list_tables, describe_table, sample_rows, run_sql
  metrics - search_metrics, get_metric
  examples (planned) - search_examples over a few-shot bank that never contains eval items
"""
import json

from . import schema
from .db import QueryResult, run_sql
from .semantic import Metrics

# How many result rows the model sees after run_sql; the full result stays with the agent.
PREVIEW_ROWS = 20


def _spec(name, description, properties=None, required=()):
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        },
    }


TABLE = {"table": {"type": "string", "description": "Table name, as returned by list_tables."}}

TOOL_GROUPS = {
    "schema": [
        _spec("list_tables", "List the tables in the Olist database."),
        _spec("describe_table", "Column names and types of one table.", TABLE, ["table"]),
        _spec(
            "sample_rows",
            "A few example rows from one table, to see what values look like.",
            {**TABLE, "n": {"type": "integer", "description": "Rows to return (1-10).", "default": 3}},
            ["table"],
        ),
        _spec(
            "run_sql",
            "Run one read-only DuckDB SELECT query. Returns columns, the first rows and the row count, or an error.",
            {"sql": {"type": "string", "description": "A single DuckDB SELECT statement."}},
            ["sql"],
        ),
    ],
    "metrics": [
        _spec(
            "search_metrics",
            "Search the business definitions (revenue, customer, late delivery, ...) by keywords.",
            {"query": {"type": "string"}},
            ["query"],
        ),
        _spec("get_metric", "Get one business definition by name.", {"name": {"type": "string"}}, ["name"]),
    ],
}


def result_payload(result: QueryResult, preview_rows: int = PREVIEW_ROWS) -> dict:
    if not result.ok:
        return {"error": result.error}
    return {
        "columns": result.columns,
        "rows": [list(r) for r in result.rows[:preview_rows]],
        "row_count": len(result.rows),
        "truncated": result.truncated,
    }


class ToolBox:
    """Runs tool calls against one read-only connection.

    run_sql results are also kept in `last_result` so the agent can return the
    full table without asking the model to repeat it.
    """

    def __init__(self, con, settings, groups=("schema",), metrics: Metrics | None = None):
        self.con = con
        self.settings = settings
        self.groups = tuple(groups)
        self.metrics = metrics or (Metrics(settings.metrics_path) if "metrics" in groups else None)
        self.last_sql: str | None = None
        self.last_result: QueryResult | None = None
        self._handlers = {
            "list_tables": lambda: schema.list_tables(self.con),
            "describe_table": lambda table: schema.describe_table(self.con, table),
            "sample_rows": lambda table, n=3: result_payload(
                schema.sample_rows(self.con, table, min(max(int(n), 1), 10))
            ),
            "run_sql": self._run_sql,
            "search_metrics": lambda query: self.metrics.search_metrics(query),
            "get_metric": lambda name: self.metrics.get_metric(name)
            or {"error": f"No metric {name!r}. Known: {', '.join(self.metrics.names())}"},
        }

    def specs(self) -> list[dict]:
        return [spec for g in self.groups for spec in TOOL_GROUPS[g]]

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool. Returns (JSON text for the model, is_error)."""
        allowed = {s["name"] for s in self.specs()}
        if name not in allowed:
            return json.dumps({"error": f"Unknown tool {name!r}"}), True
        try:
            out = self._handlers[name](**args)
        except (TypeError, ValueError) as e:
            return json.dumps({"error": str(e)}), True
        is_error = isinstance(out, dict) and "error" in out
        return json.dumps(out, default=str), is_error

    def _run_sql(self, sql: str) -> dict:
        result = run_sql(self.con, sql, self.settings.row_limit, self.settings.timeout_s)
        self.last_sql, self.last_result = sql, result
        return result_payload(result)
