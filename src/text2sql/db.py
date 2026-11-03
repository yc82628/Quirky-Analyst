"""Read-only DuckDB access for the agent.

The connection is opened read-only with external file access disabled and the
configuration locked, so agent SQL can't write to the database, read or write
local files, or switch those protections off.
"""
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


def connect(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        str(db_path),
        read_only=True,
        config={"enable_external_access": False, "lock_configuration": True},
    )


def run_sql(con, sql: str, row_limit: int = 1000, timeout_s: float = 20) -> QueryResult:
    """Run one query; never raises. Rows past row_limit are dropped and flagged."""
    timer = threading.Timer(timeout_s, con.interrupt)
    start = time.perf_counter()
    timer.start()
    try:
        cur = con.execute(sql)
        if cur.description is None:
            result = QueryResult(error="Statement returned no result set; only SELECT queries are supported.")
        else:
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(row_limit + 1)
            result = QueryResult(columns, rows[:row_limit], truncated=len(rows) > row_limit)
    except duckdb.InterruptException:
        result = QueryResult(error=f"Query timed out after {timeout_s:g}s.")
    except duckdb.Error as e:
        result = QueryResult(error=f"{type(e).__name__}: {str(e).strip()}")
    finally:
        timer.cancel()
    result.elapsed_s = time.perf_counter() - start
    return result
