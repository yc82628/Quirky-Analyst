"""Business metric definitions from semantic/metrics.yaml."""
import re
from pathlib import Path

import yaml


class Metrics:
    def __init__(self, path: str | Path):
        self.entries: dict[str, dict] = yaml.safe_load(Path(path).read_text()) or {}

    def names(self) -> list[str]:
        return list(self.entries)

    def get_metric(self, name: str) -> dict | None:
        key = name.strip().lower().replace(" ", "_")
        entry = self.entries.get(key)
        return {"name": key, **entry} if entry else None

    def search_metrics(self, query: str, k: int = 3) -> list[dict]:
        """Rank definitions by word overlap with the query (name words count double)."""
        words = set(_words(query))
        scored = []
        for name, entry in self.entries.items():
            name_words = set(_words(name))
            body_words = set(_words(" ".join(str(v) for v in entry.values())))
            score = 2 * len(words & name_words) + len(words & body_words)
            if score:
                scored.append((score, name))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [self.get_metric(name) for _, name in scored[:k]]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2]
