"""Write each page's prose, and guard what it says.

Every figure a page states must already be in the evidence. `app/report/guard.py`
enforces that by containment: a number in model-authored text that is not in the
numeric corpus is rejected. That machinery is reused verbatim here — it was built
for the revision loop and the semantics are identical.

What happens on rejection matters. The text is not silently dropped and the
figure is not silently deleted: the page keeps the *deterministic* statement the
evidence itself carries, and records that the authored version was refused. A
page that quietly loses its prose looks thin for no reason a reader can see.

The old fallback wrote "No executive summary was produced for this report." That
sentence is worse than an empty page: it tells the reader something failed
without telling them what, and it appears in the artifact as though it were
content. The deterministic path here states what the evidence says instead.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import BulletsElement, PageDesign, TextElement
from app.evidence.model import EvidenceIndex, EvidenceItem
from app.llm import prompts, reasoning_model, tasks
from app.planning.schemas import PageCopy, StorylinePlan

log = logging.getLogger("pmi.generation.narrative")

#: Prose long enough to overflow any slot the template offers. The overflow
#: critic measures properly; this is a cheap guard before that.
MAX_BODY_CHARS = 1400
MAX_BULLETS = 7

#: Sections whose job is to say what to do next. Matched on the storyline's
#: `purpose` first; the title is the backstop for a structure the user wrote
#: themselves, where the purpose classifier never ran.
_RECOMMENDS = re.compile(
    r"\b(recommend\w*|next step\w*|way forward|actions? required)\b", re.I)

#: Said in the small grey provenance line every renderer already draws, because
#: a reader must never mistake a proposal for something a source reported.
AI_RECOMMENDATION_NOTE = (
    "AI-generated recommendations. Not drawn from the uploaded sources — "
    "these are suggestions for discussion and require manager verification "
    "before they are acted on."
)

#: The body text above the recommendations. It has to be set explicitly: leaving
#: it empty falls through to `_deterministic_body`, which correctly reports that
#: there is no evidence — so the page rendered "Not enough data" directly above
#: the very recommendations written to answer it.
RECOMMENDATION_LEAD_IN = (
    "No uploaded source covers this topic. The actions below are proposed for "
    "discussion rather than reported from the data."
)


def write_page(page: PageDesign, context: GenerationContext,
               plan: Optional[StorylinePlan] = None, *,
               use_model: bool = True,
               copy: Optional[PageCopy] = None) -> list[str]:
    """Fill the page's text elements. Returns warnings."""
    warnings: list[str] = []
    items = context.evidence.resolve(page.evidence_ids)

    supplied = copy is not None
    with tasks.collect() as fell_back:
        copy = copy or (_ask(page, context, plan, items) if use_model
                        else fallback_copy(page, context, items))

    # A "Recommendations" section that no source speaks to would otherwise read
    # "Not enough data", which is true and useless. Recommendations are the one
    # thing worth writing when there is nothing to restate, because they propose
    # an action rather than asserting a fact about the project.
    recommendations = _recommendations_for(page, context, plan, items, warnings)
    if recommendations:
        copy = copy.model_copy(update={"bullets": recommendations,
                                       "body": RECOMMENDATION_LEAD_IN})
        page.source_note = " ".join(
            part for part in (page.source_note, AI_RECOMMENDATION_NOTE) if part)

    # The guard exists to stop a *model* stating a figure the evidence does not
    # hold. When the text is Python's own, containment is the wrong test: the
    # corpus cannot contain a count Python has just derived — "2 critical risk(s)
    # have no mitigation" — so checking it swaps a real finding for a plain
    # restatement of the rows, and records a warning accusing Python of
    # inventing its own arithmetic.
    #
    # `use_model` alone cannot answer "is this the model's text?": the task may
    # have asked and fallen back internally, returning exactly the deterministic
    # copy below. Only the collector knows.
    accept = _accept if ((use_model or supplied) and not fell_back) else _trusted

    if copy.message_title and accept(copy.message_title, context, page, warnings,
                                     "title"):
        page.title = copy.message_title
    if copy.supporting_message and accept(copy.supporting_message, context, page,
                                          warnings, "subtitle"):
        page.subtitle = copy.supporting_message
    if copy.speaker_notes:
        page.speaker_notes = copy.speaker_notes

    for element in page.elements:
        if isinstance(element, TextElement) and element.role in (
                "body", "callout", "quote"):
            text = copy.callout if element.role == "callout" else copy.body
            # `element.text` starts life as the design intent (often just the
            # section title), not finished copy. Rendering it when PageCopy is
            # empty produced pages such as "Open Decisions / Open Decisions"
            # with no decision content. Only preserve it here when a user has
            # explicitly authored that element.
            if not text and element.authored_by == "user":
                text = element.text
            if not text:
                text = _deterministic_body(items, context)
            if accept(text, context, page, warnings, element.role):
                element.text = _clip(text, MAX_BODY_CHARS)
                element.authored_by = "llm" if (use_model or supplied) else "python"
            else:
                element.text = _deterministic_body(items, context)
                element.authored_by = "python"
        elif isinstance(element, BulletsElement):
            bullets = copy.bullets or _deterministic_bullets(items)
            kept: list[str] = []
            for bullet in bullets[:MAX_BULLETS]:
                if accept(bullet, context, page, warnings, "bullet"):
                    kept.append(_clip(bullet, 220))
            element.items = kept or _deterministic_bullets(items)[:MAX_BULLETS]
            element.authored_by = "llm" if copy.bullets and kept else "python"

    return warnings


def _recommendations_for(page: PageDesign, context: GenerationContext,
                         plan: Optional[StorylinePlan],
                         items: Sequence[EvidenceItem],
                         warnings: list[str]) -> list[str]:
    """Recommended actions for a recommendations page with nothing to report.

    Guarded here rather than by the caller's `accept`: that is `_trusted` when
    the page's own copy fell back to Python, and this text is the model's. A
    recommendation carrying a figure the evidence does not hold is exactly what
    `guard.check_text` exists to stop, so it is checked on its own terms.
    """
    if not _wants_recommendations(page, plan, items):
        return []

    section = plan.section(page.section_id) if plan is not None else None
    topic = (section.working_title if section is not None else "") or page.title

    proposed = tasks.write_recommendations(
        topic,
        audience=context.audience or "",
        project_context=context.project_context or "",
    )
    kept = [_clip(text, 220) for text in proposed
            if _accept(text, context, page, warnings, "recommendation")]
    if proposed and not kept:
        log.warning("page %s: every recommendation stated a figure outside the "
                    "evidence and was rejected", page.page_id)
    return kept[:MAX_BULLETS]


def _wants_recommendations(page: PageDesign, plan: Optional[StorylinePlan],
                           items: Sequence[EvidenceItem]) -> bool:
    """Whether this page is a recommendations section the sources do not answer.

    The evidence test comes first and is deliberately strict: one substantive
    record is enough to prefer restating it. Proposing actions *instead of*
    reporting what a source said would be the pipeline overriding its own
    evidence, which is a far worse failure than a thin page.
    """
    if any(not item.is_absence for item in items):
        return False

    section = plan.section(page.section_id) if plan is not None else None
    if section is not None:
        if section.purpose == "plan":
            return True
        if _RECOMMENDS.search(section.working_title or ""):
            return True
    return bool(_RECOMMENDS.search(page.title or ""))


def _ask(page: PageDesign, context: GenerationContext,
         plan: Optional[StorylinePlan],
         items: Sequence[EvidenceItem]) -> PageCopy:
    return tasks.run_task(
        "write.page",
        system=prompts.compose("_grounding_rules", "write_page"),
        user=_payload(page, context, plan, items),
        output_model=PageCopy,
        model=reasoning_model(),
        max_tokens=2048,
        fallback=lambda: fallback_copy(page, context, items),
    )


def _payload(page: PageDesign, context: GenerationContext,
             plan: Optional[StorylinePlan],
             items: Sequence[EvidenceItem]) -> str:
    roles = ", ".join(sorted({e.role for e in page.elements})) or "none"
    parts = [
        f"## This page\nPurpose: {page.purpose} | composition: "
        f"{page.composition}\nWorking title: {page.title}\n"
        f"Working subtitle: {page.subtitle}\nElements to write: {roles}",
    ]
    if plan is not None:
        section = plan.section(page.section_id)
        parts.append(f"## The argument\nGoverning message: "
                     f"{plan.governing_message}")
        if section is not None:
            parts.append(f"This section must land: {section.intended_message}\n"
                         f"It answers: {section.management_question}")
    if context.audience:
        parts.append(f"Reader: {context.audience}")
    if context.company_names.as_sentence():
        parts.append(context.company_names.as_sentence())
    parts.append("## Evidence for this page\n"
                 + "\n".join(item.one_line() for item in items[:30]))

    absences = [i for i in items if i.is_absence]
    if absences:
        parts.append("Some of this page's subject is not covered by any source. "
                     "Say what is missing and what would be needed; do not "
                     "estimate.")
    return "\n\n".join(parts)


# ----------------------------------------------------------------- the guard
def _accept(text: str, context: GenerationContext, page: PageDesign,
            warnings: list[str], where: str) -> bool:
    """Whether authored text may be used: no figure outside the evidence."""
    from app.report import guard

    offending = guard.check_text(text, context.evidence.numeric_corpus())
    if not offending:
        return True

    message = (f"Authored {where} on page {page.page_id!r} stated "
               f"{', '.join(offending[:3])}, which is not in the evidence; the "
               f"deterministic wording was used instead.")
    warnings.append(message)
    page.warnings.append(message)
    log.warning(message)
    return False


def _trusted(text: str, context: GenerationContext, page: PageDesign,
             warnings: list[str], where: str) -> bool:
    """The guard's signature, for text Python authored from the evidence."""
    return True


# --------------------------------------------------------- deterministic path
def fallback_copy(page: PageDesign, context: GenerationContext,
                  items: Sequence[EvidenceItem]) -> PageCopy:
    """Honest, plain prose from the evidence's own statements."""
    return PageCopy(
        page_id=page.page_id,
        message_title=page.title,
        supporting_message=page.subtitle,
        body=_deterministic_body(items, context),
        bullets=_deterministic_bullets(items),
        speaker_notes="",
    )


def _deterministic_body(items: Sequence[EvidenceItem],
                        context: Optional[GenerationContext] = None) -> str:
    """What the evidence says, in sentences Python authored.

    Never "no summary was produced". If there is genuinely nothing, it says what
    is missing and what would answer it — a precise gap is useful, a generic
    failure notice is not.
    """
    substantive = [i for i in items if not i.is_absence]
    absences = [i for i in items if i.is_absence]

    if not substantive:
        return "Not enough data"

    sentences = [i.statement for i in substantive[:4] if i.statement]
    body = " ".join(sentences)

    contested = [i for i in substantive if i.is_contested]
    if contested:
        body += (f" Sources disagree about {len(contested)} of these figures; "
                 f"the disagreement is unresolved and the values above should "
                 f"not be treated as agreed.")
    if absences:
        body += " " + " ".join(i.statement for i in absences[:2])
    return body


def _deterministic_bullets(items: Sequence[EvidenceItem]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item.statement:
            out.append(item.statement)
        if len(out) >= MAX_BULLETS:
            break
    return out


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    # Cut at a sentence boundary where possible: a paragraph ending mid-clause
    # reads as a bug, which undermines everything else on the page.
    cut = text[:limit]
    for boundary in (". ", "; "):
        index = cut.rfind(boundary)
        if index > limit * 0.6:
            return cut[:index + 1]
    return cut.rstrip() + "…"
