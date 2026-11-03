"""Run one agent config over the eval set and score it.

Usage:
    python scripts/run_eval.py --agent baseline                 # dev split (everything except holdout)
    python scripts/run_eval.py --agent baseline --ids e01,m03   # a few items while debugging
    python scripts/run_eval.py --agent baseline --split holdout --final

Writes runs/<run_id>/predictions.jsonl, traces.jsonl and summary.json.
Clarify items are run and saved, but graded separately (not by execution accuracy).
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

from text2sql.agents import EXPERIMENTS, build_agent
from text2sql.config import ROOT, load_settings
from text2sql.db import connect
from text2sql.trace import Tracer

HOLDOUT_FILE = ROOT / "eval" / "holdout.txt"


def load_evaluate():
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "eval" / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def holdout_ids() -> set[str]:
    lines = HOLDOUT_FILE.read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def select_items(items, split, ids, limit):
    if ids:
        wanted = set(ids)
        held = wanted & holdout_ids()
        if held:
            raise SystemExit(f"Holdout ids requested: {sorted(held)}. Use --split holdout --final.")
        items = [i for i in items if i["id"] in wanted]
    elif split == "dev":
        items = [i for i in items if i["id"] not in holdout_ids()]
    elif split == "holdout":
        items = [i for i in items if i["id"] in holdout_ids()]
    return items[:limit] if limit else items


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", default="baseline", choices=list(EXPERIMENTS))
    p.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    p.add_argument("--final", action="store_true", help="required to run holdout items")
    p.add_argument("--ids", help="comma-separated eval ids")
    p.add_argument("--limit", type=int)
    p.add_argument("--run-id")
    args = p.parse_args()
    if args.split in ("holdout", "all") and not args.final:
        p.error("holdout items are for final numbers only; add --final")

    evaluate = load_evaluate()
    settings = load_settings()
    items = select_items(evaluate.load_items(), args.split, args.ids and args.ids.split(","), args.limit)
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{args.agent}"
    run_dir = settings.runs_dir / run_id
    tracer = Tracer(run_dir)
    # DuckDB allows one connection config per file per process, so close this before scoring.
    con = connect(settings.db_path)
    agent = build_agent(args.agent, settings, tracer=tracer, con=con)

    pred_path = run_dir / "predictions.jsonl"
    records = []
    with pred_path.open("w", encoding="utf-8") as f:
        for n, item in enumerate(items, 1):
            r = agent.answer(item["question"], question_id=item["id"])
            rec = {
                "id": item["id"], "difficulty": item["difficulty"], "sql": r.sql, "text": r.text,
                "error": r.error, "row_count": len(r.rows), "retries": r.retries,
                "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                "cost_usd": round(r.cost_usd, 6), "latency_s": round(r.latency_s, 2),
            }
            records.append(rec)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            status = r.error or f"{len(r.rows)} rows"
            print(f"[{n}/{len(items)}] {item['id']}: {status} ({r.latency_s:.1f}s, ${r.cost_usd:.4f})")

    con.close()
    print()
    scored_ids =[i["id"] for i in items if i["difficulty"] != "clarify"]
    report = evaluate.score(str(settings.db_path), str(pred_path), ids=scored_ids) if scored_ids else {}

    def avg(key):
        return sum(r[key] for r in records) / len(records) if records else 0.0

    summary = {
        "run_id": run_id, "agent": args.agent, "model": settings.model, "effort": settings.effort,
        "split": "ids" if args.ids else args.split, "n_items": len(records),
        **{k: v for k, v in report.items() if k != "outcomes"},
        "avg_retries": avg("retries"), "avg_input_tokens": avg("input_tokens"),
        "avg_output_tokens": avg("output_tokens"), "avg_cost_usd": avg("cost_usd"),
        "avg_latency_s": avg("latency_s"), "total_cost_usd": sum(r["cost_usd"] for r in records),
        "clarify_pass_rate": None,  # graded separately; judge not built yet
        "outcomes": report.get("outcomes", {}),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"\nAvg cost ${summary['avg_cost_usd']:.4f}/question, avg latency {summary['avg_latency_s']:.1f}s")
    print(f"Saved to {run_dir}")


if __name__ == "__main__":
    main()
