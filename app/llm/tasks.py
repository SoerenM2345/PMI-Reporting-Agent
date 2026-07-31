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
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm import fallbacks, fast_model, get_client, reasoning_model
from app.llm.base import ImagePart, LLMError
from app.llm.prompts import load as load_prompt
from app.llm.schemas import RequestParse, SummaryBullets
from app.llm.serialize import budgeted_json, truncation_note
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


#: Task names that fell back inside the innermost active `collect()` block.
_collected: ContextVar[Optional[list[str]]] = ContextVar("collected", default=None)


@contextmanager
def collect() -> Iterator[list[str]]:
    """The task names that fell back inside this block.

    `_warnings` cannot answer that question. It is one list shared by every
    request in the process and it is only drained by the graph, so a caller that
    reaches the engine without going through a graph node — `/api/content` is
    one — sees warnings left behind by an *earlier, unrelated* run. Asking it
    "did planning fall back?" answers "did planning fall back at some point since
    someone last drained", which is how one failed storyline came to stamp
    "Unplanned layout" on every later document in the process, across sessions.

    A `ContextVar` is scoped to this call and safe under FastAPI's threadpool,
    and it keeps every intermediate signature unchanged — the alternative was
    threading a flag through `interpret`, `develop` and `design_pages`.
    """
    stages: list[str] = []
    token = _collected.set(stages)
    try:
        yield stages
    finally:
        _collected.reset(token)


def _fallback(task: str, exc: Exception, fn: Callable[[], T]) -> T:
    message = (
        f"LLM unavailable for '{task}' ({type(exc).__name__}: {exc}); "
        f"used a deterministic fallback — output is template-based, not analysed."
    )
    log.warning(message)
    _warnings.append(message)
    collected = _collected.get()
    if collected is not None:
        collected.append(task)
    return fn()


def run_task(name: str, *, system: str, user: str, output_model: type[T],
             fallback: Callable[[], T], model: Optional[str] = None,
             max_tokens: Optional[int] = None,
             images: Sequence[ImagePart] = ()) -> T:
    """Run one LLM task, or fall back deterministically and record that it did.

    Every semantic call in the codebase goes through here, so there is exactly
    one place that decides what "the model was unavailable" means and exactly
    one place that records it. The planning pipeline adds nine more callers; if
    each handled its own failure, a keyless run would produce a document that
    looked planned and silently was not — which is the failure `_fallback`'s
    wording was written to prevent.
    """
    try:
        return get_client().structured(
            system=system, user=user, output_model=output_model,
            model=model, max_tokens=max_tokens, images=images,
        )
    except (LLMError, ValidationError) as exc:
        return _fallback(name, exc, fallback)


# --------------------------------------------------------------------- tasks
def parse_request(request_text: str) -> RequestParse:
    """§11: 'Understanding the reporting request' + 'Detecting target audience'."""
    return run_task(
        "parse_request",
        system=load_prompt("detect_pmi_request"),
        user=request_text,
        output_model=RequestParse,
        model=fast_model(),
        fallback=lambda: fallbacks.heuristic_parse(request_text),
    )


def write_summary(
    model: PMIDataModel, audience: Audience, request_text: str
) -> list[str]:
    """§11: 'Generating executive summaries' / 'Creating audience-specific wording'."""
    payload = _serialize_for_llm(model)
    return run_task(
        "write_summary",
        system=load_prompt("create_executive_summary"),
        user=(f"Audience: {audience.value}\n"
              f"Request: {request_text}\n\n"
              f"Standardized PMI data:\n{payload}"),
        output_model=SummaryBullets,
        model=reasoning_model(),
        fallback=lambda: fallbacks.template_summary(model, audience),
    ).bullets


# ------------------------------------------------------------------- helpers
def _serialize_for_llm(model: PMIDataModel, budget_chars: int = 60_000) -> str:
    """Serialize the data model for a prompt without corrupting it.

    The shedding logic now lives in `app/llm/serialize.py` so the planning
    pipeline can reuse it; this keeps the warning wording, which reaches the
    data-quality report.
    """
    # Shed the bulkiest, least summary-relevant collections first.
    payload, dropped = budgeted_json(
        model, budget_chars=budget_chars, exclude={"notes"},
        shed_order=("tasks", "milestones", "budget", "kpis", "risks"),
    )
    if not dropped:
        return payload

    _warnings.append(
        "PMI data model exceeded the prompt budget; the summary was written "
        f"from a subset (omitted {', '.join(dropped)})."
    )
    return f"{truncation_note(dropped)}\n{payload}"
