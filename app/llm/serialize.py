"""Fit a Pydantic payload into a prompt budget without corrupting it.

The obvious implementation — `model_dump_json()[:12000]` — slices mid-token and
hands the model malformed JSON, which it will then confidently misread. This
drops **whole entities** from the tail of the largest collections until the
payload fits, and reports what it dropped so the caller can say so in the prompt.
Truncated-but-valid beats corrupt-but-complete.

Reporting the loss matters as much as making it cleanly. A model handed a subset
it believes is the whole will write "there are three open risks"; a model told it
is seeing 40 of 137 will not.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from pydantic import BaseModel

log = logging.getLogger("pmi.llm.serialize")


def budgeted_json(payload: BaseModel, *, budget_chars: int,
                  shed_order: Sequence[str],
                  exclude: Optional[set[str]] = None) -> tuple[str, list[str]]:
    """Serialize `payload` under `budget_chars`, shedding `shed_order` first.

    Returns the JSON and a human-readable list of what was dropped
    (`["12 tasks", "3 milestones"]`), empty when nothing was.

    `shed_order` is the caller's judgement about what is least load-bearing for
    *this* prompt — a summary can lose individual tasks long before it can lose
    the risk register.
    """
    exclude = exclude or set()
    text = payload.model_dump_json(exclude=exclude, indent=None)
    if len(text) <= budget_chars:
        return text, []

    trimmed = payload.model_copy(deep=True)
    dropped: list[str] = []

    for field in shed_order:
        while len(text) > budget_chars:
            items = getattr(trimmed, field, None)
            if not items:
                break
            items.pop()
            text = trimmed.model_dump_json(exclude=exclude, indent=None)
        removed = len(getattr(payload, field, []) or []) - \
            len(getattr(trimmed, field, []) or [])
        if removed:
            dropped.append(f"{removed} {field}")

    if len(text) > budget_chars:
        # Everything sheddable is gone and it still does not fit. Say so rather
        # than slicing: a caller that knows it failed can pick a smaller task.
        log.warning("payload still %d chars after shedding %s (budget %d)",
                    len(text), shed_order, budget_chars)
    return text, dropped


def truncation_note(dropped: Sequence[str]) -> str:
    """The line to put at the head of a truncated payload."""
    if not dropped:
        return ""
    return f"NOTE: payload truncated for size — omitted {', '.join(dropped)}."
