"""The semantic tasks the LLM is allowed to do (spec §11).

Each task is: try the model, validate against a schema, and on any failure fall
back to a deterministic heuristic **while recording a warning**. The warning is
the point. The original code wrapped every call in `except Exception: pass`, which
made a broken API key look exactly like a working one — the report still rendered,
with template prose, and nobody could tell. Now a run that fell back says so, and
that statement reaches the data-quality report (§21.17).

Spec §11 also lists what the LLM must NOT be the final authority for: calculations,
dates, budget variances, synergy figures, risk scores, file generation. None of
those are in this module.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm import fallbacks, fast_model, get_client, reasoning_model
from app.llm.base import LLMError
from app.llm.prompts import load as load_prompt
from app.llm.schemas import RequestParse, SummaryBullets
from app.models.pmi import Audience, PMIDataModel

log = logging.getLogger("pmi.llm")

T = TypeVar("T", bound=BaseModel)

#: Warnings recorded by the most recent task calls. The graph drains this into
#: the run's warning list after each node.
_warnings: list[str] = []


def drain_warnings() -> list[str]:
    """Return and clear warnings accumulated since the last drain."""
    global _warnings
    out, _warnings = _warnings, []
    return out


def _fallback(task: str, exc: Exception, fn: Callable[[], T]) -> T:
    message = (
        f"LLM unavailable for '{task}' ({type(exc).__name__}: {exc}); "
        f"used a deterministic fallback — output is template-based, not analysed."
    )
    log.warning(message)
    _warnings.append(message)
    return fn()


# --------------------------------------------------------------------- tasks
def parse_request(request_text: str) -> RequestParse:
    """§11: 'Understanding the reporting request' + 'Detecting target audience'."""
    try:
        return get_client().structured(
            system=load_prompt("detect_pmi_request"),
            user=request_text,
            output_model=RequestParse,
            model=fast_model(),
        )
    except (LLMError, ValidationError) as exc:
        return _fallback(
            "parse_request", exc, lambda: fallbacks.heuristic_parse(request_text)
        )


def write_summary(
    model: PMIDataModel, audience: Audience, request_text: str
) -> list[str]:
    """§11: 'Generating executive summaries' / 'Creating audience-specific wording'."""
    try:
        payload = _serialize_for_llm(model)
        result = get_client().structured(
            system=load_prompt("create_executive_summary"),
            user=(
                f"Audience: {audience.value}\n"
                f"Request: {request_text}\n\n"
                f"Standardized PMI data:\n{payload}"
            ),
            output_model=SummaryBullets,
            model=reasoning_model(),
        )
        return result.bullets
    except (LLMError, ValidationError) as exc:
        return _fallback(
            "write_summary", exc, lambda: fallbacks.template_summary(model, audience)
        ).bullets


# ------------------------------------------------------------------- helpers
def _serialize_for_llm(model: PMIDataModel, budget_chars: int = 60_000) -> str:
    """Serialize the data model for a prompt without corrupting it.

    The original code did `model_dump_json()[:12000]`, which slices mid-token and
    hands the model malformed JSON. Instead we drop whole entities from the tail
    of the largest collections until the payload fits, and say what we dropped —
    truncated-but-valid beats corrupt-but-complete.
    """
    payload = model.model_dump_json(exclude={"notes"}, indent=None)
    if len(payload) <= budget_chars:
        return payload

    trimmed = model.model_copy(deep=True)
    dropped: list[str] = []

    # Shed the bulkiest, least summary-relevant collections first.
    for field in ("tasks", "milestones", "budget", "kpis", "risks"):
        while len(payload) > budget_chars:
            items = getattr(trimmed, field, None)
            if not items:
                break
            items.pop()
            payload = trimmed.model_dump_json(exclude={"notes"}, indent=None)
        removed = len(getattr(model, field, [])) - len(getattr(trimmed, field, []))
        if removed:
            dropped.append(f"{removed} {field}")

    if dropped:
        note = f"NOTE: payload truncated for size — omitted {', '.join(dropped)}."
        _warnings.append(
            "PMI data model exceeded the prompt budget; the summary was written "
            f"from a subset (omitted {', '.join(dropped)})."
        )
        return f"{note}\n{payload}"
    return payload
