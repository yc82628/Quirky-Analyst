import pytest

from text2sql import schema
from text2sql.semantic import Metrics
from text2sql.config import ROOT


def test_list_tables(con):
    assert schema.list_tables(con) == ["customers", "orders"]


def test_describe_table(con):
    cols = schema.describe_table(con, "orders")
    assert [c["name"] for c in cols] == ["order_id", "customer_id", "order_status"]
    assert cols[0]["type"] == "VARCHAR"


def test_unknown_table_is_rejected(con):
    with pytest.raises(ValueError, match="Unknown table"):
        schema.describe_table(con, "orders; DROP TABLE orders")


def test_sample_rows(con):
    r = schema.sample_rows(con, "customers", 2)
    assert r.ok and len(r.rows) == 2


def test_full_schema_text(con):
    text = schema.full_schema_text(con)
    assert "orders (3 rows)" in text
    assert "customer_unique_id VARCHAR" in text


def test_metrics_lookup_and_search():
    m = Metrics(ROOT / "semantic" / "metrics.yaml")
    assert "customer_unique_id" in m.get_metric("customer")["definition"]
    assert m.get_metric("Late Delivery")["name"] == "late_delivery"
    assert m.get_metric("nope") is None
    assert m.search_metrics("total revenue last year")[0]["name"] == "revenue"
