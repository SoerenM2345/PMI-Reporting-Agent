"""Decide how each page communicates, then bind that to a real layout.

Two halves, deliberately separated.

`design_pages` is the model's: how many pages a section needs, what goes on
each, which element carries the argument and which supports it. It names a
*composition* — "chart with commentary beside it" — and never a coordinate,
because it has no way to know that this master puts its right-hand column at
6.84 inches.

`bind_layouts` is Python's: turn each composition into a `TemplateLayout` from
the catalog, assign every element to a named slot, and resolve every KPI value
from evidence. When the template cannot serve a composition, the page degrades
to the nearest native layout and **carries the reason as a page warning** — the
alternative, drawing free-floating boxes on a blank slide, is precisely how the
previous renderer came to ignore 57 of the template's 59 layouts.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import (
    BulletsElement,
    ChartElement,
    DesignElement,
    DiagramElement,
    ImageElement,
    KpiRowElement,
    KpiTile,
    PageDesign,
    TableElement,
    TextElement,
)
from app.evidence import provenance
from app.evidence.model import EvidenceIndex
from app.evidence.retrieval import pack, retrieve
from app.llm import prompts, reasoning_model, tasks
from app.planning.schemas import (
    DocumentDesign,
    ElementIntent,
    OutputBrief,
    PageIntent,
    SectionIntent,
    StorylinePlan,
)

log = logging.getLogger("pmi.planning.visual")

#: How a section's `recommended_expression` becomes a page composition when the
#: model is unavailable. Not a template — a mapping from "what kind of thing is
#: this" to "what shape communicates it", which is the judgement a fallback can
#: still make honestly.
_EXPRESSION_COMPOSITION = {
    "none": "single",
    "table": "table_full",
    "comparison": "chart_plus_commentary",
    "trend": "hero_chart",
    "composition": "hero_chart",
    "distribution": "hero_chart",
    "sequence": "single",
    "hierarchy": "single",
    "relationship": "single",
    "matrix": "matrix",
}

_EXPRESSION_ELEMENT = {
    "table": "table",
    "comparison": "chart",
    "trend": "chart",
    "composition": "chart",
    "distribution": "chart",
    "sequence": "diagram",
    "hierarchy": "diagram",
    "relationship": "diagram",
    "matrix": "diagram",
}


def design_pages(context: GenerationContext, brief: OutputBrief,
                 plan: StorylinePlan) -> DocumentDesign:
    """The page-by-page design for the whole document."""
    return tasks.run_task(
        "plan.document_design",
        system=prompts.compose("_grounding_rules", "plan_document_design"),
        user=_payload(context, brief, plan),
        output_model=DocumentDesign,
        model=reasoning_model(),
        max_tokens=_max_tokens(),
        fallback=lambda: fallback_design(context, brief, plan),
    )


def _max_tokens() -> int:
    from app.config import get_settings

    return getattr(get_settings(), "llm_max_output_tokens_planning", 16384)


def _payload(context: GenerationContext, brief: OutputBrief,
             plan: StorylinePlan) -> str:
    catalog = getattr(context.template_reference, "catalog", None)
    compositions = ", ".join(sorted(
        {c for c in _EXPRESSION_COMPOSITION.values()} |
        {"two_column", "three_column", "four_column", "kpi_banner", "quote",
         "full_bleed"}))

    parts = [
        f"## The document\n{brief.document_kind.replace('_', ' ')} as "
        f"{brief.primary_format}, for {brief.audience_label}.",
        f"Governing message: {plan.governing_message}",
        f"Narrative flow: {plan.narrative_flow}",
    ]
    if brief.target_page_count:
        parts.append(f"The user asked for about {brief.target_page_count} pages. "
                     f"Respect that.")

    parts.append("## Sections to lay out")
    for section in plan.sections:
        evidence_lines = _evidence_lines(context.evidence, section.evidence_ids)
        parts.append(
            f"### {section.section_id}\n"
            f"Working title: {section.working_title}\n"
            f"Message: {section.intended_message}\n"
            f"Purpose: {section.purpose} | suggested pages: "
            f"{section.suggested_pages} | expression the storyline suggested: "
            f"{section.recommended_expression}\n"
            f"Evidence available to this section:\n{evidence_lines}")

    parts.append(f"## Compositions available\n{compositions}")
    if catalog is not None:
        available = sorted({lay.columns for lay in catalog.content_layouts()
                            if lay.columns})
        parts.append(f"The template natively supports content layouts with "
                     f"{available} column(s), plus cover, section-divider, "
                     f"full-bleed-image and closing layouts. A composition that "
                     f"needs more columns than exist will be degraded.")
    return "\n\n".join(parts)


def _evidence_lines(evidence: EvidenceIndex, ids: Sequence[str],
                    limit: int = 25) -> str:
    items = evidence.resolve(ids)[:limit]
    if not items:
        return "(none — this section can only state that nothing was found)"
    return "\n".join(item.one_line() for item in items)


# ============================================================ keyless design
def fallback_design(context: GenerationContext, brief: OutputBrief,
                    plan: StorylinePlan) -> DocumentDesign:
    """One page per section, shaped by the evidence rather than by a template.

    The old fallback would have been "cover, four KPI cards, six tables". This
    at least varies with what the evidence supports — but it makes no editorial
    judgement, and the deliverable says so on its first page.
    """
    pages: list[PageIntent] = [PageIntent(
        page_id="cover", section_id="", purpose="cover", composition="single",
        message_title=context.display_name(),
        supporting_message=context.company_names.as_sentence()
        or context.reporting_period,
    )]

    for section in plan.sections:
        expression = section.recommended_expression
        composition = _EXPRESSION_COMPOSITION.get(expression, "single")
        element_role = _EXPRESSION_ELEMENT.get(expression)

        # Several separate findings are a list, not a paragraph. Running six
        # evidence statements together into one body block is how the old
        # fallback produced pages nobody could skim, and it is also the only
        # shape the preview can offer to rewrite line by line.
        body_role = "bullets" if len(section.evidence_ids) >= 3 else "body"
        elements = [ElementIntent(role=body_role,
                                  intent=section.intended_message
                                  or section.working_title,
                                  evidence_ids=section.evidence_ids[:8],
                                  prominence="primary")]
        if element_role:
            elements.insert(0, ElementIntent(
                role=element_role, intent=section.working_title,
                evidence_ids=section.evidence_ids, prominence="primary"))
            elements[-1].prominence = "supporting"

        pages.append(PageIntent(
            page_id=section.section_id,
            section_id=section.section_id,
            purpose="content" if section.purpose != "appendix" else "appendix",
            composition=composition,
            message_title=section.working_title,
            supporting_message=section.intended_message,
            elements=elements,
        ))

    return DocumentDesign(
        pages=pages,
        rationale="Assembled without a language model: one page per requested "
                  "topic, shaped by the evidence available to it.")


# ============================================================ layout binding
def bind_layouts(design: DocumentDesign, context: GenerationContext,
                 plan: StorylinePlan, *,
                 planned_by: str = "llm") -> tuple[list[PageDesign], list[str]]:
    """Turn page intents into renderable pages bound to real template layouts."""
    reference = context.template_reference
    catalog = getattr(reference, "catalog", None)
    warnings: list[str] = []
    pages: list[PageDesign] = []
    seen: set[str] = set()

    for index, intent in enumerate(design.pages):
        page_id = _unique(intent.page_id or f"page-{index + 1}", seen)
        seen.add(page_id)

        needs_picture = any(e.role == "image" for e in intent.elements)
        choice = None
        if catalog is not None:
            choice = catalog.choose(
                composition=intent.composition,
                purpose=intent.purpose,
                needs_subtitle=bool(intent.supporting_message),
                needs_picture=needs_picture,
            )

        page = PageDesign(
            page_id=page_id,
            index=index,
            section_id=intent.section_id,
            purpose=intent.purpose,
            composition=intent.composition,
            layout_id=choice.layout.layout_id if choice else "",
            layout_name=choice.layout.raw_name.strip() if choice else "",
            title=intent.message_title,
            subtitle=intent.supporting_message,
            speaker_notes=intent.speaker_notes_intent,
            planned_by=planned_by,                              # type: ignore[arg-type]
        )
        if choice is not None and choice.degraded:
            page.warnings.append(choice.reason)
            warnings.append(f"{page_id}: {choice.reason}")

        slots = _content_slots(choice)
        page.elements = _bind_elements(intent, context.evidence, slots, page)
        page.evidence_ids = _page_evidence(intent, page)
        page.source_note = provenance.source_note(
            context.evidence.resolve(page.evidence_ids))
        pages.append(page)

    return pages, warnings


def _content_slots(choice) -> list[str]:
    if choice is None:
        return ["col1"]
    slots = [slot.slot_id for slot in choice.layout.column_slots]
    return slots or ["col1"]


def _bind_elements(intent: PageIntent, evidence: EvidenceIndex,
                   slots: Sequence[str], page: PageDesign) -> list[DesignElement]:
    """Assign every element to a slot and resolve every value from evidence."""
    elements: list[DesignElement] = []
    ordered = _ordered(intent)
    body_index = 0
    #: Element ids are numbered *within a role*, not across the page. A
    #: positional id (`risks-e2`) moves the moment anything is inserted above
    #: it — and the user's rewritten paragraph, which is matched by id in
    #: `session.apply_overrides`, then lands on whatever took that position.
    #: Resolving a conflict so a chart finally validates is enough to do it.
    seen: dict[str, int] = {}

    for element in ordered:
        seen[element.role] = seen.get(element.role, 0) + 1
        element_id = f"{page.page_id}.{element.role}{seen[element.role]}"
        # Headline-ish roles go to the page furniture, not into a column.
        if element.role in ("headline", "kicker", "source_note"):
            slot = {"headline": "title", "kicker": "subtitle",
                    "source_note": ""}[element.role]
        else:
            slot = slots[body_index % len(slots)] if slots else ""
            body_index += 1

        built = _build(element, element_id, slot, evidence, page)
        if built is not None:
            elements.append(built)
    return elements


def _ordered(intent: PageIntent) -> list[ElementIntent]:
    """Respect the model's stated visual hierarchy where it gave one."""
    if not intent.visual_hierarchy:
        return list(intent.elements)
    rank = {role: position for position, role
            in enumerate(intent.visual_hierarchy)}
    return sorted(intent.elements,
                  key=lambda e: (rank.get(e.role, len(rank)),
                                 e.prominence != "primary"))


def _build(element: ElementIntent, element_id: str, slot: str,
           evidence: EvidenceIndex, page: PageDesign) -> Optional[DesignElement]:
    ids = [i for i in element.evidence_ids if evidence.get(i)]
    unknown = evidence.unknown(element.evidence_ids)
    if unknown:
        page.warnings.append(
            f"An element cited {len(unknown)} evidence item(s) that do not "
            f"exist; they were dropped.")

    common = dict(element_id=element_id, slot=slot, evidence_ids=ids,
                  authored_by="llm", prominence=element.prominence)

    if element.role in ("headline", "kicker", "body", "callout", "quote",
                        "source_note"):
        return TextElement(role=element.role, text=element.intent, **common)
    if element.role == "bullets":
        return BulletsElement(items=[], **common)

    # A chart, table, diagram or KPI row with nothing behind it cannot be
    # built. Keeping it would put a caption on the page with no figure under
    # it — which is precisely the `Chart: Workstream Progress` stub the old
    # renderers emitted. Drop it and say why.
    if element.role in ("table", "chart", "diagram", "kpi_row") and not ids:
        page.warnings.append(
            f"A {element.role.replace('_', ' ')} was planned for this page but "
            f"cites no evidence, so it could not be built.")
        log.info("dropped %s element on %s: no evidence", element.role,
                 page.page_id)
        return None

    if element.role == "table":
        return TableElement(spec_id=f"{element_id}-table",
                            caption=element.intent, **common)
    if element.role == "chart":
        return ChartElement(spec_id=f"{element_id}-chart",
                            caption=element.intent, **common)
    if element.role == "diagram":
        return DiagramElement(spec_id=f"{element_id}-diagram",
                              caption=element.intent, **common)
    if element.role == "kpi_row":
        return KpiRowElement(tiles=_tiles(ids, evidence), **common)
    if element.role == "image":
        return ImageElement(image_ref="", alt=element.intent, **common)
    log.debug("unknown element role %r; dropped", element.role)
    return None


def _tiles(ids: Sequence[str], evidence: EvidenceIndex) -> list[KpiTile]:
    """Resolve KPI values in Python.

    The model chose *which* figures deserve a tile. It did not, and could not,
    write what they say.
    """
    tiles: list[KpiTile] = []
    for evidence_id in ids[:6]:
        item = evidence.get(evidence_id)
        if item is None:
            continue
        tiles.append(KpiTile(
            label=item.label,
            evidence_id=evidence_id,
            display=item.display or "Not Reported",
            emphasis=_emphasis(item),
            note="disputed" if item.is_contested else
                 ("read from an image" if item.needs_review else ""),
        ))
    return tiles


def _emphasis(item) -> str:
    if item.is_contested:
        return "warn"
    if item.severity in ("critical", "high"):
        return "bad"
    if item.value is None:
        return "muted"
    return "none"


def _page_evidence(intent: PageIntent, page: PageDesign) -> list[str]:
    seen: list[str] = []
    for element in page.elements:
        for evidence_id in element.evidence_ids:
            if evidence_id not in seen:
                seen.append(evidence_id)
    return seen


def _unique(candidate: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9\-]+", "-", candidate.casefold()).strip("-") or "page"
    if base not in taken:
        return base
    for suffix in range(2, 200):
        attempt = f"{base}-{suffix}"
        if attempt not in taken:
            return attempt
    return f"{base}-{len(taken)}"
