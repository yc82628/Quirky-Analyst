import json

import pytest

from text2sql.agents import build_agent
from text2sql.agents.baseline import extract_sql
from text2sql.tools import ToolBox
from text2sql.trace import Tracer


def test_extract_sql_takes_last_block():
    text = "First try:\n```sql\nSELECT 1\n```\nBetter:\n```SQL\nSELECT 2;\n```"
    assert extract_sql(text) == "SELECT 2"
    assert extract_sql("no code here") is None


def test_baseline_runs_the_sql_it_gets(settings, con, fake_llm):
    llm = fake_llm("Count distinct people.\n```sql\nSELECT COUNT(DISTINCT customer_unique_id) AS n FROM customers\n```")
    agent = build_agent("baseline", settings, llm=llm, con=con)
    r = agent.answer("How many customers?", question_id="t1")

    assert r.rows == [(2,)] and r.error is None
    assert r.text == "Count distinct people."
    assert r.cost_usd == 0.001
    assert "customer_unique_id VARCHAR" in llm.calls[0]["system"]  # full schema in the prompt
    assert llm.calls[0]["tools"] is None
    assert [s["kind"] for s in r.steps] == ["llm", "sql"]


def test_baseline_reports_sql_errors_without_retrying(settings, con, fake_llm):
    llm = fake_llm("```sql\nSELECT * FROM nope\n```")
    r = build_agent("baseline", settings, llm=llm, con=con).answer("?")
    assert r.error and "nope" in r.error
    assert len(llm.calls) == 1


def test_baseline_without_sql_keeps_the_text(settings, con, fake_llm):
    llm = fake_llm("Do you mean best by revenue or by number of orders?")
    r = build_agent("baseline", settings, llm=llm, con=con).answer("Who are our best customers?")
    assert r.sql is None and r.error == "no SQL in response"
    assert "revenue" in r.text


def test_traces_are_written(settings, con, fake_llm, tmp_path):
    tracer = Tracer(tmp_path / "run")
    llm = fake_llm("```sql\nSELECT 1\n```")
    build_agent("baseline", settings, llm=llm, con=con, tracer=tracer).answer("?", question_id="e01")
    lines = (tmp_path / "run" / "traces.jsonl").read_text().splitlines()
    assert [json.loads(line)["qid"] for line in lines] == ["e01", "e01"]


def test_tool_agent_is_a_stub_for_now(settings, con, fake_llm):
    with pytest.raises(NotImplementedError):
        build_agent("tools", settings, llm=fake_llm(), con=con).answer("?")


def test_toolbox_dispatch(settings, con):
    tools = ToolBox(con, settings, groups=("schema", "metrics"))
    assert {s["name"] for s in tools.specs()} >= {"run_sql", "describe_table", "search_metrics"}

    out, is_error = tools.call("run_sql", {"sql": "SELECT COUNT(*) AS n FROM orders"})
    assert not is_error and json.loads(out)["rows"] == [[3]]
    assert tools.last_result.rows == [(3,)]

    out, is_error = tools.call("describe_table", {"table": "missing"})
    assert is_error and "Unknown table" in json.loads(out)["error"]

    assert tools.call("drop_everything", {})[1] is True
    assert ToolBox(con, settings).call("search_metrics", {"query": "revenue"})[1] is True  # group not enabled
