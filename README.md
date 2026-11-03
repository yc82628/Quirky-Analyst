# Quirky Analyst: an Olist text-to-SQL agent

An agent that answers business questions about the
[Olist Brazilian e-commerce dataset](https://github.com/olist/work-at-olist-data)
by exploring the schema, writing SQL, running it, and fixing its own errors,
plus an evaluation set to measure how well it does.

> Status: evaluation set and scorer done; agent skeleton next, then the
> silent-error checker (see `CLAUDE.md`).

## Layout

| Path | What it is |
|---|---|
| `eval/eval_set.yaml` | 75 questions: 20 easy, 25 medium, 25 hard with gold SQL, plus 5 ambiguous ones |
| `eval/evaluate.py` | Builds expected results and scores predictions by execution accuracy |
| `eval/expected_results.json` | Output of every gold query |
| `eval/example_predictions.jsonl` | A deliberately flawed run (4 classic mistakes) to show a score report |
| `semantic/metrics.yaml` | Business definitions (revenue, customer, late delivery…) the gold SQL follows |
| `scripts/load_data.py` | Loads the CSVs into DuckDB with short table names |
| `data/` | Raw CSVs and `olist.duckdb` (not committed) |

## Quick start

```bash
pip install -r requirements.txt
git clone --depth 1 https://github.com/olist/work-at-olist-data data/raw
python scripts/load_data.py data/raw/datasets data/olist.duckdb
python eval/evaluate.py score data/olist.duckdb eval/example_predictions.jsonl
```

Predictions are one JSON object per line: `{"id": "m03", "sql": "SELECT ..."}`.

## How scoring works

A prediction passes when its result matches the gold result:

- column names and column order don't matter, and extra columns are allowed
- numbers are compared after rounding to 2 decimals
- row order is checked only for rankings and time series (`order_matters: true`)
- bucket label text (e.g. `late` vs `is_late = true`) is ignored; the values must still match

The report breaks accuracy down by difficulty and by tag, so you can see
which kind of question the agent fails, e.g. `definition_trap` or `window`.
The 5 `clarify` items are graded separately: the agent passes if it asks a
clarifying question or states its assumption.

## Traps built into the set

- **customer_id vs customer_unique_id.** customer_id is new for every order, so
  "how many customers ordered twice?" returns 0 if the agent uses it (m17, h02, h09).
- **Revenue definition.** Excludes freight and canceled/unavailable orders (m01 and most money questions).
- **Partial years.** 2018 data stops in early September, so full-year comparisons mislead (h23).
- **Portuguese category names.** Questions use English names; the agent must find the translation table (m20).
- **Grain.** Multi-item orders get double-counted when joining reviews to order_items (h06, h15).

## Results

| Agent | Easy | Medium | Hard | Overall | Avg retries | Cost / question |
|---|---|---|---|---|---|---|
| baseline (one-shot, full schema) | | | | | | |
| + schema tools & retries | | | | | | |
| + metric definitions | | | | | | |
| + retrieved examples | | | | | | |
| + silent-error checker in the loop | | | | | | |

## Silent-error checker (planned)

The worst text-to-SQL failures don't raise errors. The query runs and returns a
believable number that is wrong. The checker runs after any agent, this one or
another tool, and flags answers that are probably wrong even though the SQL
succeeded:

- **Grain:** joins that inflate totals (row count vs distinct keys)
- **Partial periods:** comparisons that use a month or year the data only partly covers
- **Definitions:** SQL that contradicts `semantic/metrics.yaml`, e.g. `customer_id` used to count customers
- **Reconciliation:** a second, independent query that disagrees with the first
- **Plausibility:** values the data can't produce, such as a percentage above 100

It never sees the gold SQL. It's graded on two numbers:

| Test set | Silent errors caught | Correct answers falsely flagged |
|---|---|---|
| Mutated gold SQL | | |
| Real agent runs | | |
