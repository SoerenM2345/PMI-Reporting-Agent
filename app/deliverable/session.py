"""Plan, store and re-plan a session's deliverable — one plan for both surfaces.

`app/report/pipeline.py` did this for `ReportContent`. The difference that matters
is not the type: it is that the preview and the artifact now read the *same*
object, so they cannot disagree about what the report says.

Re-planning is cheap and happens often — after a cell edit, after a conflict
resolution, after new files. What must survive a re-plan is everything the user
personally contributed:

* **Prose overrides.** A rewritten paragraph is the user's, and re-planning must
  not silently discard it. Overrides are keyed in the knowledge base and
  re-applied after planning, exactly as supplied *values* already are.
* **Corrections.** Those are already durable: a cell edit writes through to
  `PMIDataModel` via `corrections.apply_and_persist`, so a re-plan reads the
  corrected value rather than needing to remember the edit.

The asymmetry is deliberate and is the same one the edit endpoints enforce:
prose is the user's to write, data is not.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.deliverable import fingerprint as fp
from app.deliverable import store
from app.deliverable.model import BulletsElement, Deliverable, TextElement

log = logging.getLogger("pmi.deliverable.session")

#: Where a rewritten paragraph is remembered between re-plans.
OVERRIDE_PREFIX = "dlv:"


def plan(session_id: str, analysis, *, request_text: str = "",
         audience: str = "", fmt: Optional[str] = None,
         presentation_layout: bool = False,
         force: bool = True, cancel=None) -> Deliverable:
    """Plan the session's deliverable and store it as a new version."""
    from app.agent import knowledge as kb_store
    from app.context import builder
    from app.deliverable import engine

    kb = kb_store.load(session_id)
    context = builder.build_for_session(
        session_id, request_text or analysis.request_text or "",
        analysis=analysis)
    if fmt:
        context.requested_output_format = fmt
    context.presentation_layout = presentation_layout
    # The reader named in *this* turn wins: "actually it's for the CFO" is a
    # correction, and falling back to the stored label would ignore it.
    context.audience = (audience or context.audience
                        or analysis.audience_label or "")

    deliverable = engine.build(context, force=force,
                               content_revision=kb.content_revision,
                               cancel=cancel)
    deliverable.warnings.extend(apply_overrides(deliverable, kb))
    deliverable.session_id = session_id
    # What the staleness check will compare against next time. See
    # `Deliverable.request_text` for why it is recorded rather than re-derived.
    deliverable.request_text = context.user_request
    deliverable.audience_label = deliverable.audience_label or context.audience
    store.save(deliverable)
    log.info("session %s: planned deliverable v%d (%d pages, planned_by=%s)",
             session_id, deliverable.version, deliverable.page_count,
             deliverable.planned_by)
    return deliverable


def load(session_id: str, version: Optional[int] = None) -> Optional[Deliverable]:
    return store.load(session_id=session_id, version=version)


def current_or_plan(session_id: str, analysis, **kwargs) -> Deliverable:
    """The stored plan, re-planned first if it has gone stale."""
    deliverable = load(session_id)
    if deliverable is None:
        return plan(session_id, analysis, **kwargs)
    if is_stale(deliverable, session_id, analysis):
        return plan(session_id, analysis, **kwargs)
    return deliverable


# ---------------------------------------------------------------- staleness
def _fingerprint(session_id: str, analysis,
                 deliverable: Optional[Deliverable] = None
                 ) -> fp.ContextFingerprint:
    """The current fingerprint, as the given deliverable would be re-planned.

    The request and the reader come from the deliverable itself rather than from
    the analysis. Otherwise the comparison answers "would a *different* document
    be planned now?" — which is true of any document planned from a chat turn
    the analysis never saw, so every draft would be stale the moment it was
    written. A genuinely new ask arrives through `plan()`, not through a check.
    """
    from app.agent import knowledge as kb_store
    from app.context import builder

    request = ((deliverable.request_text if deliverable is not None else "")
               or analysis.request_text or "")
    context = builder.build_for_session(session_id, request, analysis=analysis)
    if deliverable is not None and deliverable.audience_label:
        context.audience = deliverable.audience_label
    if deliverable is not None:
        context.presentation_layout = deliverable.presentation_layout
    return fp.compute(context,
                      content_revision=kb_store.load(session_id).content_revision)


def is_stale(deliverable: Deliverable, session_id: str, analysis) -> bool:
    return fp.is_stale(deliverable,
                       _fingerprint(session_id, analysis, deliverable))


def stale_reason(deliverable: Deliverable, session_id: str, analysis) -> str:
    return fp.stale_reason(deliverable,
                           _fingerprint(session_id, analysis, deliverable))


def stale_pages(deliverable: Deliverable, session_id: str,
                analysis) -> list[str]:
    return fp.stale_pages(deliverable,
                          _fingerprint(session_id, analysis, deliverable))


# ---------------------------------------------------------------- overrides
def record_override(session_id: str, element_id: str, text: str) -> None:
    """Remember a rewritten paragraph so the next re-plan keeps it."""
    from app.agent import knowledge as kb_store

    kb = kb_store.load(session_id)
    kb.set_prose_override(f"{OVERRIDE_PREFIX}{element_id}", text)
    kb_store.save(kb)


def apply_overrides(deliverable: Deliverable, kb) -> list[str]:
    """Re-apply the user's own wording after planning. Returns warnings.

    Matched by element id, which names the page and the element's *role* — so an
    override survives a re-plan that adds a chart above it, and is dropped when
    the element it was written for no longer exists. Dropping it is correct:
    text attached to a paragraph the report no longer has would otherwise
    reappear somewhere it was never written for.

    Dropping it *quietly* is not. The user typed those words; if they are gone
    they have to be told, in the artifact and not only in a log.
    """
    overrides = {key[len(OVERRIDE_PREFIX):]: value
                 for key, value in (kb.prose_overrides or {}).items()
                 if key.startswith(OVERRIDE_PREFIX)}
    if not overrides:
        return []

    matched: set[str] = set()
    applied = 0
    for page in deliverable.pages:
        for element in page.elements:
            text = overrides.get(element.element_id)
            if text is None:
                continue
            if isinstance(element, BulletsElement):
                element.items = [line for line in text.splitlines() if line.strip()]
            elif isinstance(element, TextElement):
                element.text = text
            else:
                continue
            element.authored_by = "user"
            matched.add(element.element_id)
            applied += 1
    if applied:
        log.info("re-applied %d user-written passage(s) after planning", applied)

    warnings: list[str] = []
    for element_id in overrides:
        if element_id in matched:
            continue
        page_id = element_id.split(".", 1)[0]
        page = deliverable.page(page_id)
        where = f"“{page.title}”" if page is not None and page.title else "the report"
        message = (f"A passage you rewrote on {where} could not be restored — "
                   f"that part of the page no longer exists. Your wording is "
                   f"still saved; nothing was written in its place.")
        warnings.append(message)
        log.warning("orphaned prose override %r: %s", element_id, message)
    return warnings
