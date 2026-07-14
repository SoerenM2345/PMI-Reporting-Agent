"""Prompt assets (spec §16 `app/prompts/`).

Prompts live as `.md` files rather than string literals so they can be reviewed
and edited without touching Python, and so the repo shows them as first-class
artefacts. `load()` caches — a prompt is read once per process.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """Load prompt `name` (without extension) from app/llm/prompts/."""
    path = _DIR / f"{name}.md"
    if not path.is_file():
        available = sorted(p.stem for p in _DIR.glob("*.md"))
        raise FileNotFoundError(f"no prompt {name!r}; available: {available}")
    return path.read_text(encoding="utf-8").strip()
