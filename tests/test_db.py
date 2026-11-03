from text2sql.db import run_sql


def test_select_returns_columns_and_rows(con):
    r = run_sql(con, "SELECT order_id, order_status FROM orders ORDER BY order_id")
    assert r.ok
    assert r.columns == ["order_id", "order_status"]
    assert r.rows[0] == ("o1", "delivered")
    assert not r.truncated


def test_bad_sql_returns_error_instead_of_raising(con):
    r = run_sql(con, "SELECT * FROM no_such_table")
    assert not r.ok
    assert "no_such_table" in r.error


def test_writes_are_blocked(con):
    for sql in ["CREATE TABLE x AS SELECT 1", "DELETE FROM orders", "INSERT INTO orders VALUES ('o9', 'c9', 'x')"]:
        assert not run_sql(con, sql).ok, sql
    assert run_sql(con, "SELECT count(*) FROM orders").rows == [(3,)]


def test_file_access_and_config_changes_are_blocked(con, tmp_path):
    out = (tmp_path / "leak.csv").as_posix()
    assert not run_sql(con, f"COPY orders TO '{out}'").ok
    assert not run_sql(con, "SET enable_external_access = true").ok


def test_row_limit_truncates(con):
    r = run_sql(con, "SELECT * FROM range(50)", row_limit=10)
    assert len(r.rows) == 10
    assert r.truncated


def test_timeout_interrupts_slow_query(con):
    r = run_sql(con, "SELECT sum(a.range * b.range) FROM range(200000) a, range(200000) b", timeout_s=0.3)
    assert not r.ok
    assert "timed out" in r.error
    assert r.elapsed_s < 5
