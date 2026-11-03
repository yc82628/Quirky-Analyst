import json
from dataclasses import replace

import pytest

from text2sql.agents import build_agent, tool_agent
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


GOOD_SQL = "SELECT COUNT(DISTINCT customer_unique_id) AS n FROM customers"


def test_tool_agent_explores_then_answers(settings, con, fake_llm):
    llm = fake_llm(
        [("list_tables", {})],
        [("describe_table", {"table": "customers"})],
        [("run_sql", {"sql": GOOD_SQL})],
        "There are 2 distinct customers.",
    )
    r = build_agent("tools", settings, llm=llm, con=con).answer("How many customers?", question_id="t1")

    assert r.rows == [(2,)] and r.sql == GOOD_SQL and r.error is None
    assert r.text == "There are 2 distinct customers."
    assert r.retries == 0 and r.input_tokens == 400 and r.cost_usd == pytest.approx(0.004)
    assert "customer_unique_id VARCHAR" not in llm.calls[0]["system"]  # schema comes from tools, not the prompt
    assert {t["name"] for t in llm.calls[0]["tools"]} == {"list_tables", "describe_table", "sample_rows", "run_sql"}
    reply = llm.calls[1]["messages"][-1]["content"][0]
    assert reply["type"] == "tool_result" and reply["tool_use_id"] == "t1_0"
    assert "orders" in reply["content"]
    assert [s["kind"] for s in r.steps] == ["llm", "tool", "llm", "tool", "llm", "tool", "llm"]


def test_tool_agent_revises_after_an_error(settings, con, fake_llm):
    llm = fake_llm([("run_sql", {"sql": "SELECT * FROM nope"})], [("run_sql", {"sql": GOOD_SQL})], "2 customers.")
    r = build_agent("tools", settings, llm=llm, con=con).answer("How many customers?")

    assert r.rows == [(2,)] and r.error is None and r.retries == 1
    error_reply = llm.calls[1]["messages"][-1]["content"][0]
    assert error_reply["is_error"] is True and "nope" in error_reply["content"]
    assert "3 revisions left" in error_reply["content"]


def test_tool_agent_flags_empty_results(settings, con, fake_llm):
    empty = "SELECT * FROM orders WHERE order_status = 'Delivered'"
    llm = fake_llm([("run_sql", {"sql": empty})], [("run_sql", {"sql": GOOD_SQL})], "Done.")
    r = build_agent("tools", settings, llm=llm, con=con).answer("?")

    note = llm.calls[1]["messages"][-1]["content"][0]
    assert note["is_error"] is False and "No rows returned" in note["content"]
    assert r.retries == 1


def test_tool_agent_stops_after_max_retries(settings, con, fake_llm):
    bad = [("run_sql", {"sql": "SELECT * FROM nope"})]
    llm = fake_llm(bad, bad, bad)
    r = build_agent("tools", replace(settings, max_retries=1), llm=llm, con=con).answer("?")

    assert len(llm.calls) == 2  # first try + one revision, then stop
    assert r.retries == 1 and "nope" in r.error


def test_tool_agent_step_limit(settings, con, fake_llm, monkeypatch):
    monkeypatch.setattr(tool_agent, "MAX_LLM_CALLS", 2)
    llm = fake_llm([("list_tables", {})], [("list_tables", {})], [("list_tables", {})])
    r = build_agent("tools", settings, llm=llm, con=con).answer("?")
    assert r.error == "step limit" and len(llm.calls) == 2


def test_tool_agent_without_sql_keeps_the_text(settings, con, fake_llm):
    llm = fake_llm("Do you mean best by revenue or by number of orders?")
    r = build_agent("tools", settings, llm=llm, con=con).answer("Who are our best customers?")
    assert r.sql is None and r.error == "no SQL run" and "revenue" in r.text


def test_tool_agent_metrics_config(settings, con, fake_llm):
    llm = fake_llm([("get_metric", {"name": "revenue"})], "Revenue excludes freight.")
    r = build_agent("tools+metrics", settings, llm=llm, con=con).answer("What counts as revenue?")

    assert {"search_metrics", "get_metric"} <= {t["name"] for t in llm.calls[0]["tools"]}
    assert "search_metrics" in llm.calls[0]["system"]
    assert "freight" in llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert r.error == "no SQL run"


@pytest.mark.parametrize("name", ["tools+metrics+examples", "tools+metrics+examples+checker"])
def test_unbuilt_configs_fail_loudly(settings, con, fake_llm, name):
    with pytest.raises(NotImplementedError):
        build_agent(name, settings, llm=fake_llm(), con=con)


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
