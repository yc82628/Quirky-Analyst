"""Schema exploration: what the agent can learn about the database."""
from .db import QueryResult, run_sql


def list_tables(con) -> list[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    return [r[0] for r in rows]


def _check_table(con, name: str) -> None:
    if name not in list_tables(con):
        raise ValueError(f"Unknown table {name!r}. Tables: {', '.join(list_tables(con))}")


def describe_table(con, name: str) -> list[dict]:
    """Columns of one table as [{"name", "type"}], in table order."""
    _check_table(con, name)
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
        [name],
    ).fetchall()
    return [{"name": c, "type": t} for c, t in rows]


def sample_rows(con, name: str, n: int = 3) -> QueryResult:
    _check_table(con, name)
    return run_sql(con, f'SELECT * FROM "{name}" LIMIT {int(n)}', row_limit=max(int(n), 1))


def full_schema_text(con) -> str:
    """Every table with its row count and columns, one block per table."""
    blocks = []
    for table in list_tables(con):
        n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        cols = "\n".join(f"  {c['name']} {c['type']}" for c in describe_table(con, table))
        blocks.append(f"{table} ({n:,} rows)\n{cols}")
    return "\n\n".join(blocks)
