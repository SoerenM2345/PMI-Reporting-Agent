"""Judge whether the document reads like a considered deliverable.

The only critic that may use a model, and the only one whose findings are matters
of taste rather than fact. It runs two ways:

* **With page images and a vision model** — the existing client Protocol already
  accepts `images`, so no interface change was needed. This is the only check
  that can see what a reader sees.
* **Without either** — a deterministic heuristic pass over the plan: how many
  pages repeat the same composition, how many words are in a bullet, whether
  every title names a topic instead of stating a finding, whether a page is all
  text or all chart.

The mode is recorded on every finding, because "the design was reviewed" and "the
design was checked against six heuristics" are different claims and only one of
them is true here. On this machine LibreOffice is absent, so a deck is never
rasterised and the deck's design review is always heuristic.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.context.schemas import GenerationContext
from app.deliverable.model import Deliverable, PageDesign
from app.quality.schemas import ArtifactReview, Finding, finding

log = logging.getLogger("pmi.quality.design")

#: More than this many consecutive pages with one composition reads as a
#: template rather than an argument.
MAX_REPEATED_COMPOSITION = 3
#: A bullet longer than this is a paragraph wearing a bullet's clothes.
MAX_BULLET_WORDS = 32
MAX_BULLETS_PER_PAGE = 7
#: Words on one page beyond which a reader skims instead of reading.
MAX_WORDS_PER_PAGE = 220

_TOPIC_TITLE = re.compile(
    r"^(?:overview|summary|status(?: update)?|update|introduction|background|"
    r"appendix|agenda|contents|next steps|conclusion|risks?|issues?|budget|"
    r"synergies|synergy|milestones?|decisions?|dependencies|tasks?|"
    r"workstreams?|kpis?|financials?|progress)\s*$", re.I)


class DesignFinding(BaseModel):
    """One observation from the vision pass."""

    page_id: str = ""
    severity: str = "warn"
    problem: str = ""
    suggestion: str = ""


class DesignFindings(BaseModel):
    findings: list[DesignFinding] = Field(default_factory=list)
    overall: str = ""


def review(deliverable: Deliverable, context: GenerationContext, *,
           images: Sequence[bytes] = (), pass_number: int = 1,
           use_model: bool = True) -> ArtifactReview:
    """Heuristics always; the vision pass as well when it is possible."""
    result = ArtifactReview(review_id=f"design-{pass_number}",
                            pass_number=pass_number)
    result.add(*heuristics(deliverable, context))

    if images and use_model:
        result.add(*_vision(deliverable, context, images))
    else:
        why = ("no page images could be produced on this machine"
               if not images else "no model was available")
        result.add(finding(
            "design", "note",
            f"The visual design was checked against layout heuristics only, "
            f"because {why}. Nothing has looked at the rendered pages.",
            detail="heuristic-only"))
    return result


# ================================================================ heuristics
def heuristics(deliverable: Deliverable,
               context: GenerationContext) -> list[Finding]:
    findings: list[Finding] = []
    findings += _check_variety(deliverable)
    findings += _check_titles(deliverable)
    findings += _check_density(deliverable)
    findings += _check_visual_balance(deliverable)
    findings += _check_layout_use(deliverable, context)
    findings += _check_placeholders(deliverable)
    return findings


def _check_variety(deliverable: Deliverable) -> list[Finding]:
    """Consecutive pages built the same way."""
    findings: list[Finding] = []
    content = [p for p in deliverable.pages if p.purpose == "content"]
    if len(content) < MAX_REPEATED_COMPOSITION + 1:
        return findings

    run, previous = 1, None
    for page in content:
        if page.composition == previous:
            run += 1
            if run == MAX_REPEATED_COMPOSITION + 1:
                findings.append(finding(
                    "design", "warn",
                    f"{run} consecutive pages use the {page.composition} "
                    f"composition, which reads as a template rather than an "
                    f"argument.",
                    page_id=page.page_id, action="relayout"))
        else:
            run, previous = 1, page.composition

    distinct = {p.composition for p in content}
    if len(content) >= 4 and len(distinct) == 1:
        findings.append(finding(
            "design", "fix",
            f"Every content page uses the same composition "
            f"({content[0].composition}), so nothing signals which page matters.",
            action="relayout"))
    return findings


def _check_titles(deliverable: Deliverable) -> list[Finding]:
    """Titles that name a subject instead of stating a finding."""
    findings: list[Finding] = []
    topical = [p for p in deliverable.pages
               if p.purpose == "content" and _TOPIC_TITLE.match(p.title or "")]
    if topical:
        findings.append(finding(
            "design", "warn",
            f"{len(topical)} page title(s) name a topic rather than state a "
            f"finding: {', '.join(repr(p.title) for p in topical[:3])}.",
            page_id=topical[0].page_id, action="regenerate_page"))

    openings: dict[str, list[str]] = {}
    for page in deliverable.pages:
        if page.purpose != "content" or not page.title:
            continue
        opening = " ".join(page.title.split()[:2]).casefold()
        openings.setdefault(opening, []).append(page.page_id)
    for opening, pages in openings.items():
        if len(pages) >= 3:
            findings.append(finding(
                "design", "warn",
                f"{len(pages)} page titles open with “{opening}”.",
                page_id=pages[0], action="regenerate_page"))

    missing = [p.page_id for p in deliverable.pages
               if p.purpose not in ("closing",) and not (p.title or "").strip()]
    if missing:
        findings.append(finding(
            "design", "fix",
            f"{len(missing)} page(s) have no title.",
            page_id=missing[0], action="regenerate_page"))
    return findings


def _check_density(deliverable: Deliverable) -> list[Finding]:
    findings: list[Finding] = []
    for page in deliverable.pages:
        if page.purpose != "content":
            continue

        words = len(page.text_content().split())
        if words > MAX_WORDS_PER_PAGE and not page.has_visual:
            findings.append(finding(
                "design", "warn",
                f"This page carries {words} words and no visual; a reader will "
                f"skim it.",
                page_id=page.page_id, action="split_page"))

        for element in page.elements:
            items = getattr(element, "items", None)
            if not items:
                continue
            if len(items) > MAX_BULLETS_PER_PAGE:
                findings.append(finding(
                    "design", "warn",
                    f"This page has {len(items)} bullets; above "
                    f"{MAX_BULLETS_PER_PAGE} they stop being scannable.",
                    page_id=page.page_id, element_id=element.element_id,
                    action="split_page"))
            longest = max((len(item.split()) for item in items), default=0)
            if longest > MAX_BULLET_WORDS:
                findings.append(finding(
                    "design", "warn",
                    f"A bullet on this page runs to {longest} words, which is a "
                    f"paragraph rather than a bullet.",
                    page_id=page.page_id, element_id=element.element_id,
                    action="shorten"))
    return findings


def _check_visual_balance(deliverable: Deliverable) -> list[Finding]:
    findings: list[Finding] = []
    content = [p for p in deliverable.pages if p.purpose == "content"]
    if not content:
        return findings

    with_visual = [p for p in content if p.has_visual]
    if len(content) >= 4 and not with_visual:
        findings.append(finding(
            "design", "warn",
            "No page in this document carries a chart, table or diagram. If the "
            "evidence supports one, the argument would land harder with it.",
            action="relayout"))

    for page in content:
        primary = [e for e in page.elements if e.prominence == "primary"]
        if len(primary) > 2:
            findings.append(finding(
                "design", "warn",
                f"This page marks {len(primary)} elements as primary, so nothing "
                f"is.",
                page_id=page.page_id, action="relayout"))
    return findings


def _check_layout_use(deliverable: Deliverable,
                      context: GenerationContext) -> list[Finding]:
    """Whether the template is being used or merely opened."""
    findings: list[Finding] = []
    if deliverable.primary_format != "pptx":
        return findings

    layouts = deliverable.layouts_used
    if len(deliverable.pages) >= 4 and len(layouts) < 2:
        findings.append(finding(
            "design", "fix",
            f"The whole deck sits on one layout ({layouts[0] if layouts else '?'}). "
            f"The template offers layouts designed for different kinds of page.",
            action="relayout"))

    degraded = [p.page_id for p in deliverable.pages
                if any("columns" in w or "closest native" in w
                       for w in p.warnings)]
    if degraded:
        findings.append(finding(
            "design", "note",
            f"{len(degraded)} page(s) were fitted to a layout other than the one "
            f"designed for them.",
            page_id=degraded[0]))
    return findings


def _check_placeholders(deliverable: Deliverable) -> list[Finding]:
    """Placeholder text that survived into the artifact."""
    findings: list[Finding] = []
    needles = ("click to add", "lorem ipsum", "tbd", "tbc", "xxx", "todo",
               "placeholder", "[insert", "your text here")
    for page in deliverable.pages:
        body = page.text_content().casefold()
        for needle in needles:
            if needle in body:
                findings.append(finding(
                    "design", "block",
                    f"This page contains placeholder text (“{needle}”).",
                    page_id=page.page_id, action="regenerate_page"))
                break
    return findings


# =============================================================== vision pass
def _vision(deliverable: Deliverable, context: GenerationContext,
            images: Sequence[bytes]) -> list[Finding]:
    """Show the rendered pages to a vision model and ask what is wrong."""
    import base64

    from app.llm import prompts, tasks, vision_model
    from app.llm.base import ImagePart

    parts = [ImagePart(b64=base64.b64encode(image).decode("ascii"),
                       media_type="image/png")
             for image in images[:12]]
    index = "\n".join(f"Image {number}: page {page.page_id} "
                      f"({page.purpose}, {page.composition})"
                      for number, page in enumerate(deliverable.pages[:12],
                                                    start=1))

    result = tasks.run_task(
        "review.design",
        system=prompts.compose("_grounding_rules", "review_design"),
        user=f"## The pages you are looking at\n{index}\n\n"
             f"## The document\n{deliverable.document_kind} for "
             f"{deliverable.audience_label}\n"
             f"Governing message: {deliverable.governing_message}",
        output_model=DesignFindings,
        model=vision_model(),
        max_tokens=3072,
        images=parts,
        fallback=lambda: DesignFindings(),
    )

    known = {page.page_id for page in deliverable.pages}
    findings: list[Finding] = []
    for observation in result.findings:
        severity = observation.severity if observation.severity in (
            "block", "fix", "warn", "note") else "warn"
        message = observation.problem
        if observation.suggestion:
            message = f"{message} {observation.suggestion}"
        findings.append(finding(
            "design", severity, message,
            page_id=observation.page_id if observation.page_id in known else None,
            action="relayout" if severity in ("fix", "block") else "none",
            detail="vision"))
    return findings
