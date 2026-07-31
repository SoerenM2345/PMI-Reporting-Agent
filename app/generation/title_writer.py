"""Write every title in one call, so the document does not repeat itself.

Batched deliberately. Written page by page, a model opens six consecutive slides
with the same verb — "Delivery remains…", "Budget remains…", "Synergies
remain…" — and no single call can see it happening. Seeing all the pages at once
is the only way to avoid it, and it is cheaper.

Titles are checked the same way prose is: a conclusion the evidence does not
support is rejected, and so is one stating a figure. Where a title is refused,
the page keeps its planned working title rather than losing its heading.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import Deliverable
from app.llm import fast_model, prompts, tasks
from app.planning.schemas import DocumentTitles, PageTitle, StorylinePlan

log = logging.getLogger("pmi.generation.titles")

#: A slide title longer than this will not fit the template's 12.33 x 0.37in
#: title box at 21pt. The overflow critic measures properly; this stops the
#: obvious cases before anything is rendered.
MAX_TITLE_CHARS = 110
MAX_SUBTITLE_CHARS = 150

#: Openings that signal a title describing rather than concluding.
_WEAK_OPENINGS = re.compile(
    r"^(overview|summary|status|update|introduction|background|appendix|"
    r"agenda|contents|next steps|conclusion)\b\s*$", re.I)


def write_titles(deliverable: Deliverable, context: GenerationContext,
                 plan: Optional[StorylinePlan] = None, *,
                 use_model: bool = True,
                 titles: Optional[DocumentTitles] = None) -> list[str]:
    """Retitle the document and its pages in place. Returns warnings."""
    warnings: list[str] = []
    if not deliverable.pages:
        return warnings

    supplied = titles is not None
    with tasks.collect() as fell_back:
        titles = titles or (_ask(deliverable, context, plan) if use_model
                            else fallback_titles(deliverable, context))

    # Only the model's own words are checked for containment. A title Python
    # computed — "2 critical risk(s) have no mitigation action" — states a count
    # the corpus cannot hold, and rejecting it would replace the finding with
    # the topic. See `narrative_writer.write_page` for the full reasoning.
    accept = _accept if ((use_model or supplied) and not fell_back) else _trusted

    if titles.document_title and accept(titles.document_title, context,
                                        warnings, "document title"):
        deliverable.title = _clip(titles.document_title, MAX_TITLE_CHARS)
    if titles.document_subtitle:
        deliverable.subtitle = _clip(titles.document_subtitle, MAX_SUBTITLE_CHARS)

    by_page = {t.page_id: t for t in titles.titles}
    for page in deliverable.pages:
        title = by_page.get(page.page_id)
        if title is None:
            continue
        if title.title and accept(title.title, context, warnings,
                                  f"title of {page.page_id}"):
            page.title = _clip(title.title, MAX_TITLE_CHARS)
        if title.subtitle:
            page.subtitle = _clip(title.subtitle, MAX_SUBTITLE_CHARS)

    warnings.extend(_check_variety(deliverable))
    return warnings


def _ask(deliverable: Deliverable, context: GenerationContext,
         plan: Optional[StorylinePlan]) -> DocumentTitles:
    return tasks.run_task(
        "write.titles",
        system=prompts.compose("_grounding_rules", "write_titles"),
        user=_payload(deliverable, context, plan),
        output_model=DocumentTitles,
        model=fast_model(),
        max_tokens=3072,
        fallback=lambda: fallback_titles(deliverable, context),
    )


def _payload(deliverable: Deliverable, context: GenerationContext,
             plan: Optional[StorylinePlan]) -> str:
    parts = [
        f"## The document\n{deliverable.document_kind.replace('_', ' ')} for "
        f"{deliverable.audience_label or 'an unnamed reader'}",
        f"Governing message: {deliverable.governing_message}",
    ]
    if context.company_names.as_sentence():
        parts.append(context.company_names.as_sentence())
    if context.project_name:
        parts.append(f"Project or deal name: {context.project_name}")

    parts.append("## The pages, in order")
    for page in deliverable.pages:
        evidence = context.evidence.resolve(page.evidence_ids)[:6]
        lines = "\n".join(f"  - {item.statement}" for item in evidence
                          if item.statement)
        parts.append(
            f"### {page.page_id} ({page.purpose}, {page.composition})\n"
            f"Working title: {page.title or '(none)'}\n"
            f"Working subtitle: {page.subtitle or '(none)'}\n"
            f"What this page rests on:\n{lines or '  - (nothing)'}")
    return "\n\n".join(parts)


def _accept(text: str, context: GenerationContext, warnings: list[str],
            where: str) -> bool:
    from app.report import guard

    offending = guard.check_text(text, context.evidence.numeric_corpus())
    if offending:
        message = (f"The authored {where} stated {', '.join(offending[:2])}, "
                   f"which is not in the evidence; the planned title was kept.")
        warnings.append(message)
        log.warning(message)
        return False


def _trusted(text: str, context: GenerationContext, warnings: list[str],
             where: str) -> bool:
    """`_accept`'s signature, for titles Python authored from the evidence."""
    return True
    return True


def _check_variety(deliverable: Deliverable) -> list[str]:
    """Flag titles that describe rather than conclude, and repeated openings."""
    warnings: list[str] = []

    weak = [p.page_id for p in deliverable.pages
            if p.purpose == "content" and _WEAK_OPENINGS.match(p.title or "")]
    if weak:
        warnings.append(
            f"{len(weak)} page title(s) name a topic rather than state a "
            f"finding ({', '.join(weak[:3])}).")

    openings: dict[str, list[str]] = {}
    for page in deliverable.pages:
        if page.purpose != "content" or not page.title:
            continue
        opening = " ".join(page.title.split()[:2]).casefold()
        openings.setdefault(opening, []).append(page.page_id)
    for opening, pages in openings.items():
        if len(pages) >= 3:
            warnings.append(
                f"{len(pages)} pages open with {opening!r}, which reads as a "
                f"template rather than an argument.")
    return warnings


def fallback_titles(deliverable: Deliverable,
                    context: GenerationContext) -> DocumentTitles:
    """Keep the planned titles. Better a plain heading than an invented finding."""
    return DocumentTitles(
        document_title=deliverable.title or context.display_name(),
        document_subtitle=deliverable.subtitle or context.subject_line(),
        titles=[PageTitle(page_id=p.page_id, title=p.title, subtitle=p.subtitle)
                for p in deliverable.pages],
    )


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split()).rstrip(" .")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.7 else cut).rstrip() + "…"
