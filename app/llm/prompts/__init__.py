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


@lru_cache(maxsize=None)
def compose(*names: str) -> str:
    """Join several prompts into one system prompt, in the order given.

    Put the stable, shared parts first. The Anthropic client marks the system
    prompt as cacheable, so a constant prefix across the nine planning tasks is
    a real saving; leading with the task-specific part would defeat it.
    """
    return "\n\n---\n\n".join(load(name) for name in names)


def data_block(label: str, text: str, *, limit: int = 20_000) -> str:
    """Fence untrusted text as data, never as instruction.

    Project background, chat history and text lifted out of uploaded files all
    reach planning prompts and are all written by people who are not
    necessarily the person asking. The structural defences do the real work —
    closed schemas with no numeric fields, evidence ids validated against a
    known set — but labelling the boundary costs nothing and makes the rule
    legible to a reader of the prompt.
    """
    body = (text or "").strip()
    if not body:
        return ""
    if len(body) > limit:
        body = body[:limit] + f"\n[... {len(text) - limit} characters omitted]"
    return f"<{label}>\n{body}\n</{label}>"
