# CLAUDE.md: Olist text-to-SQL analyst agent

## What this project is
A portfolio project for Data Analyst and AI/ML Engineer roles. An agent
answers business questions about the Olist Brazilian e-commerce data by
exploring the schema, writing SQL, running it against DuckDB, recovering from
errors, and returning a table, a chart and a short interpretation.

The project's main claim is measured, not demoed: a results table showing how
much each agent component improves execution accuracy on `eval/eval_set.yaml`.

## Current state (already done, verified)
- `scripts/load_data.py`: loads the 9 Olist CSVs into DuckDB with short table names.
- `semantic/metrics.yaml`: business definitions (revenue, customer, late delivery…).
- `eval/eval_set.yaml`: 75 items (20 easy, 25 medium, 25 hard with gold SQL, 5 `clarify`).
- `eval/evaluate.py`: `build` regenerates `expected_results.json`; `score` grades a
  predictions JSONL by execution accuracy, broken down by difficulty and tag.
- Every gold query has been run; `python eval/evaluate.py score data/olist.duckdb eval/example_predictions.jsonl`
  must print `66/70 = 94.3%`.

## First task: scaffold the skeleton
Build the structure and interfaces with working stubs, then the baseline. Don't
build the full agent in one pass.

```
src/text2sql/
  config.py        # settings from env: DB path, model name, max_retries, row_limit, timeout
  db.py            # read-only DuckDB connection; run_sql() with row limit + timeout; returns columns, rows, error
  schema.py        # list_tables(), describe_table(name), sample_rows(name, n), full_schema_text()
  semantic.py      # load metrics.yaml; get_metric(name); search_metrics(query)
  tools.py         # tool specs (JSON schema) + dispatcher mapping tool name -> function
  llm.py           # thin provider wrapper: chat(messages, tools) -> response; one place to swap models
  trace.py         # append one JSON line per step to runs/<run_id>/traces.jsonl
  agents/
    base.py        # Agent protocol: answer(question) -> AgentResult(sql, rows, text, steps, tokens, cost, latency)
    baseline.py    # one prompt with full schema -> one SQL, no tools, no retry
    tool_agent.py  # loop: explore schema -> write SQL -> run -> on error/empty, read result and retry (<= max_retries)
scripts/
  run_eval.py      # run an agent over eval_set -> runs/<run_id>/predictions.jsonl + traces, then call evaluate.score
app/
  streamlit_app.py # question box -> answer, SQL (collapsible), table, chart, trace viewer
tests/
  test_db.py, test_schema.py, test_evaluate.py   # no network, no LLM calls
```

## Experiments the skeleton must support
Each experiment is an agent config, not a code fork. Planned rows of the results table:
1. `baseline`: full schema in prompt, one shot
2. `tools`: schema exploration tools + execution with retries
3. `tools+metrics`: plus `semantic/metrics.yaml` lookup
4. `tools+metrics+examples`: plus retrieved few-shot example queries (never from eval items)
5. `tools+metrics+examples+checker`: plus silent-error checker findings fed back into the loop

Record for each run: execution accuracy (overall, by difficulty, by tag), avg
retries, tokens, cost and latency per question, and clarify-item pass rate.

## Second task: silent-error checker
The project's differentiator. Text-to-SQL agents are common; the hard failures
are queries that run cleanly and return a believable wrong number. The checker
runs after any agent (ours, or another tool's predictions JSONL) and flags
answers that are probably wrong even though the SQL succeeded. Start it once the
`tools` row has numbers, so there are real wrong answers to test on.

Input: question, SQL, result columns/rows, plus read-only DB, schema and
`metrics.yaml`. It never sees gold SQL or expected results.

```
src/text2sql/checks/
  base.py           # Check protocol: run(question, sql, result, ctx) -> list[Finding(check, severity, message, evidence)]
  grain.py          # fan-out: after joins, compare COUNT(*) with COUNT(DISTINCT key) of the aggregated entity
  partial_period.py # comparisons using periods the data only partly covers (2018 ends early Sept; first/last months)
  definitions.py    # SQL vs metrics.yaml: customer_id for customers, freight in revenue, missing status filter
  reconcile.py      # LLM writes an independent second query; flag if results disagree (only check that calls llm.py)
  plausibility.py   # values the data can't produce: pct > 100, share > 1, count > table rows, negative durations
  runner.py         # run the checks enabled in the agent config -> CheckReport
scripts/
  make_silent_errors.py  # apply classic mistakes to gold SQL -> eval/silent_errors.jsonl (checker test set only)
eval/
  check_eval.py     # grade the checker against score() outcomes
tests/
  test_checks.py    # hand-written SQL per check, no LLM calls
```

How it's measured:
- `score()` in `evaluate.py` must also return per-item outcomes (pass / wrong
  result / error / no prediction) without changing its printed report.
- Silent error = SQL ran but scored "wrong result". SQL errors are loud and out of scope.
- Catch rate = flagged silent errors / all silent errors.
  False-flag rate = flagged passes / all passes. Report both overall, per check and by tag.
- First fixture: in `eval/example_predictions.jsonl`, e02, m01 and m17 must be
  flagged; h23 is an SQL error, so ignore it.
- Larger test set: `make_silent_errors.py` mutates gold SQL with known mistakes
  (customer_unique_id -> customer_id, add freight to revenue, drop the status
  filter, join reviews to order_items without pre-aggregating). Silent errors from
  real agent runs count too; report the two sources separately.

Two ways to use it: standalone over any predictions file, and inside
`tool_agent` (experiment 5), where findings come back as an observation and the
revision counts toward `max_retries`.

## Rules
- Database access is read-only. Never write to `data/olist.duckdb` from agent code.
- Don't edit `gold_sql` or `expected_results.json` to make an agent pass. If a gold
  query is genuinely wrong, fix it, rerun `python eval/evaluate.py build data/olist.duckdb`,
  and note the change in the commit message.
- Never put eval questions or gold SQL into prompts or few-shot examples (leakage).
- The checker never reads `gold_sql`, `expected_results.json` or eval notes. Its rules
  come from the schema and `metrics.yaml`, not from specific eval items. Gold SQL may
  only be used by `make_silent_errors.py` to build checker test cases.
- Keep a held-out slice: before tuning, pick ~15 ids, list them in `eval/holdout.txt`, and
  only score them for final numbers. Tune checker rules on non-holdout items only.
- Tests must run without an API key. Mock `llm.py` in tests.
- API keys come from environment variables / `.env`, never committed.
- Windows machine: use `pathlib`, no shell-specific commands in Python code.

## Setup
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
git clone --depth 1 https://github.com/olist/work-at-olist-data data/raw
python scripts/load_data.py data/raw/datasets data/olist.duckdb
python eval/evaluate.py score data/olist.duckdb eval/example_predictions.jsonl   # expect 66/70
```
