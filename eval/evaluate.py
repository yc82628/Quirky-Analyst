"""Score a text-to-SQL agent against eval_set.yaml using execution accuracy.

1) Build the expected results once (runs every gold query):
       python eval/evaluate.py build data/olist.duckdb

2) Score your agent. predictions.jsonl has one JSON object per line:
       {"id": "m03", "sql": "SELECT ..."}
   then run:
       python eval/evaluate.py score data/olist.duckdb predictions.jsonl

Clarify items (c01-c05) have no SQL and are not scored here; grade those by
hand or with an LLM judge using their expected_behavior field.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import yaml

HERE = Path(__file__).parent
EVAL_FILE = HERE / "eval_set.yaml"
EXPECTED_FILE = HERE / "expected_results.json"
DECIMALS = 2


def load_items():
    return yaml.safe_load(EVAL_FILE.read_text())["items"]


def run_query(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return {"columns": cols, "rows": [[normalize(v) for v in r] for r in rows]}


def normalize(v):
    """Make values comparable: round floats, stringify dates and decimals."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) or type(v).__name__ == "Decimal":
        f = round(float(v), DECIMALS)
        return int(f) if f == int(f) else f
    return str(v)


def results_match(pred, gold, order_matters):
    """Execution-accuracy comparison.

    - Column names and column order are ignored.
    - The prediction may contain extra columns, but every gold column must
      appear in it (same values, same row count).
    - Row order is checked only when order_matters is true.
    - Text columns that only label buckets (e.g. '1 early') are skipped when
      the gold has other columns to check; see is_label_column.
    """
    if len(pred["rows"]) != len(gold["rows"]):
        return False
    pred_cols = list(zip(*pred["rows"])) if pred["rows"] else []
    gold_cols = list(zip(*gold["rows"])) if gold["rows"] else []
    if not gold_cols:
        return True

    def key(col):
        return list(col) if order_matters else sorted(col, key=repr)

    checkable = [c for c in gold_cols if not is_label_column(c)] or gold_cols
    pred_keys = [key(c) for c in pred_cols]
    used = set()
    for gcol in checkable:
        gk = key(gcol)
        hit = next((i for i, pk in enumerate(pred_keys) if i not in used and pk == gk), None)
        if hit is None:
            return False
        used.add(hit)
    return True


def is_label_column(col):
    """Bucket labels like '3 1-3 days late' or 'on_time' are wording choices."""
    vals = [v for v in col if v is not None]
    if not vals or not all(isinstance(v, str) for v in vals):
        return False
    return all(v[:1].isdigit() and " " in v for v in vals) or all(
        v in {"late", "on_time", "more_than_7_days_late", "on_time_or_early"} for v in vals
    )


def build(db_path):
    con = duckdb.connect(db_path, read_only=True)
    expected = {}
    for item in load_items():
        if item["difficulty"] == "clarify":
            continue
        expected[item["id"]] = run_query(con, item["gold_sql"])
    EXPECTED_FILE.write_text(json.dumps(expected, indent=1))
    print(f"Wrote {len(expected)} expected results to {EXPECTED_FILE.name}")


def score(db_path, predictions_path):
    items = {i["id"]: i for i in load_items() if i["difficulty"] != "clarify"}
    expected = json.loads(EXPECTED_FILE.read_text())
    preds = {}
    for line in Path(predictions_path).read_text().splitlines():
        if line.strip():
            p = json.loads(line)
            preds[p["id"]] = p.get("sql")

    con = duckdb.connect(db_path, read_only=True)
    by_diff, by_tag, failures = defaultdict(Counter), defaultdict(Counter), []
    for qid, item in items.items():
        sql = preds.get(qid)
        try:
            ok = bool(sql) and results_match(run_query(con, sql), expected[qid], item["order_matters"])
            reason = "wrong result" if not ok else ""
        except Exception as e:  # noqa: BLE001 - any SQL error is a miss
            ok, reason = False, f"error: {str(e).splitlines()[0][:80]}"
        if not sql:
            reason = "no prediction"
        by_diff[item["difficulty"]][ok] += 1
        for tag in item["tags"]:
            by_tag[tag][ok] += 1
        if not ok:
            failures.append((qid, reason))

    total = sum(c[True] for c in by_diff.values())
    n = sum(sum(c.values()) for c in by_diff.values())
    print(f"Execution accuracy: {total}/{n} = {100 * total / n:.1f}%\n")
    for d in ("easy", "medium", "hard"):
        c = by_diff[d]
        print(f"  {d:7s} {c[True]:>3}/{sum(c.values()):<3}")
    print("\nWeakest tags:")
    worst = sorted(by_tag.items(), key=lambda kv: kv[1][True] / sum(kv[1].values()))[:8]
    for tag, c in worst:
        print(f"  {tag:18s} {c[True]:>3}/{sum(c.values()):<3}")
    if failures:
        print("\nFailures:")
        for qid, reason in failures:
            print(f"  {qid}: {reason}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("build", "score"):
        sys.exit(__doc__)
    if sys.argv[1] == "build":
        build(sys.argv[2])
    else:
        score(sys.argv[2], sys.argv[3])
