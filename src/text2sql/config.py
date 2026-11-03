"""Settings from environment variables (and .env at the repo root)."""
import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# USD per million (input, output) tokens. Used for the cost column of the results table.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass(frozen=True)
class Settings:
    db_path: Path
    model: str
    effort: str
    max_retries: int
    row_limit: int
    timeout_s: float
    api_key: str | None
    runs_dir: Path
    metrics_path: Path


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def load_settings(**overrides) -> Settings:
    settings = Settings(
        db_path=_path(os.getenv("DB_PATH", "data/olist.duckdb")),
        model=os.getenv("LLM_MODEL") or "claude-opus-5-5",
        effort=os.getenv("LLM_EFFORT") or "high",
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        row_limit=int(os.getenv("ROW_LIMIT", "1000")),
        timeout_s=float(os.getenv("QUERY_TIMEOUT_S", "20")),
        api_key=os.getenv("LLM_API_KEY") or None,
        runs_dir=_path(os.getenv("RUNS_DIR", "runs")),
        metrics_path=ROOT / "semantic" / "metrics.yaml",
    )
    return replace(settings, **overrides)


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    """input_tokens excludes cached tokens; cache writes cost 1.25x input, reads 0.1x."""
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    billed_in = input_tokens + 1.25 * cache_write_tokens + 0.1 * cache_read_tokens
    return (billed_in * price_in + output_tokens * price_out) / 1_000_000
