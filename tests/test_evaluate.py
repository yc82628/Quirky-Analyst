import pytest

from text2sql.config import ROOT


def res(*rows):
    return {"columns": [f"c{i}" for i in range(len(rows[0]) if rows else 0)], "rows": [list(r) for r in rows]}


def test_column_names_and_order_are_ignored(evaluate):
    gold = res(("SP", 10), ("RJ", 5))
    pred = res((10, "SP"), (5, "RJ"))
    assert evaluate.results_match(pred, gold, order_matters=False)


def test_extra_columns_allowed_missing_ones_not(evaluate):
    gold = res(("SP", 10))
    assert evaluate.results_match(res(("SP", 10, "x")), gold, False)
    assert not evaluate.results_match(res(("SP",)), gold, False)


def test_row_order_only_checked_when_it_matters(evaluate):
    gold = res(("a", 1), ("b", 2))
    pred = res(("b", 2), ("a", 1))
    assert evaluate.results_match(pred, gold, order_matters=False)
    assert not evaluate.results_match(pred, gold, order_matters=True)


def test_numbers_rounded_to_two_decimals(evaluate):
    assert evaluate.normalize(3.14159) == 3.14
    assert evaluate.normalize(2.0) == 2
    assert evaluate.normalize(1.004) == evaluate.normalize(1)  # rounding happens when results are read


def test_bucket_labels_are_ignored(evaluate):
    gold = res(("1 early", 10), ("2 late", 3))
    pred = res(("early", 10), ("late", 3))
    assert evaluate.results_match(pred, gold, order_matters=True)


def test_row_count_must_match(evaluate):
    assert not evaluate.results_match(res((1,), (2,)), res((1,)), False)


@pytest.mark.skipif(not (ROOT / "data" / "olist.duckdb").exists(), reason="needs data/olist.duckdb")
def test_example_predictions_score(evaluate):
    db = str(ROOT / "data" / "olist.duckdb")
    preds = str(ROOT / "eval" / "example_predictions.jsonl")
    report = evaluate.score(db, preds)
    assert (report["correct"], report["total"]) == (66, 70)
    assert report["outcomes"]["e02"] == "wrong result"
    assert report["outcomes"]["h23"].startswith("error")

    subset = evaluate.score(db, preds, ids=["e01", "e02"])
    assert (subset["correct"], subset["total"]) == (1, 2)
