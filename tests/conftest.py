"""Shared fixtures: a tiny DuckDB file and a fake LLM. No network, no API key."""
import importlib.util
from pathlib import Path

import duckdb
import pytest

from text2sql.config import ROOT, load_settings
from text2sql.db import connect
from text2sql.llm import LLMResponse


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "tiny.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE customers (customer_id VARCHAR, customer_unique_id VARCHAR, customer_state VARCHAR)")
    con.execute("INSERT INTO customers VALUES ('c1', 'u1', 'SP'), ('c2', 'u1', 'SP'), ('c3', 'u2', 'RJ')")
    con.execute("CREATE TABLE orders (order_id VARCHAR, customer_id VARCHAR, order_status VARCHAR)")
    con.execute("INSERT INTO orders VALUES ('o1', 'c1', 'delivered'), ('o2', 'c2', 'canceled'), ('o3', 'c3', 'delivered')")
    con.close()
    return path


@pytest.fixture
def con(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def settings(db_path):
    return load_settings(db_path=db_path, row_limit=100, timeout_s=5, runs_dir=db_path.parent / "runs")


class FakeLLM:
    """Returns canned responses in order and records every call."""

    model = "fake"

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.calls = []

    def chat(self, messages, tools=None, system=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "system": system})
        text = self.texts.pop(0)
        return LLMResponse(text=text, model=self.model, input_tokens=100, output_tokens=20,
                           cost_usd=0.001, assistant_message={"role": "assistant", "content": text})


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture(scope="session")
def evaluate():
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "eval" / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
