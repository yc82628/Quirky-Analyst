"""Step traces: one JSON line per agent step in runs/<run_id>/traces.jsonl."""
import json
import time
from pathlib import Path


class Tracer:
    def __init__(self, run_dir: str | Path | None = None):
        self.path = Path(run_dir) / "traces.jsonl" if run_dir else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []
        self.question_id: str | None = None

    def start(self, question_id: str | None) -> None:
        """Begin a new question; steps from the previous one are cleared."""
        self.question_id = question_id
        self.steps = []

    def log(self, kind: str, **data) -> dict:
        step = {"qid": self.question_id, "step": len(self.steps), "kind": kind, "ts": time.time(), **data}
        self.steps.append(step)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(step, default=str) + "\n")
        return step
