"""Plan a deliverable: the one place the whole pipeline is sequenced.

    interpret the request
      -> retrieve evidence for it
      -> develop the storyline
      -> validate the sections and restore anything requested but dropped
      -> design the pages
      -> bind each page to a real template layout
      -> resolve every displayed value from evidence

Nothing here renders, and nothing here decides what is true. It is the seam
between the model's editorial judgement and Python's custody of the facts, so
the ordering matters: validation runs *after* the model has spoken and *before*
anything is bound, which is why an invented evidence id can never reach a page.

`regenerate_pages` repairs named pages without re-running any of it — no
extraction, no re-projection, not even a re-plan. The critics name pages; this
rebuilds exactly those.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.context.schemas import GenerationContext
from app.deliverable import fingerprint as fp
from app.deliverable.model import (
    Deliverable,
    DeliverableSpecs,
    PageDesign,
    TextElement,
)
from app.generation import chart_planner, narrative_writer, title_writer
from app.llm import tasks
from app.planning import (
    complete_report,
    request_interpreter,
    section_planner,
    visual_planner,
)
from app.planning.schemas import DocumentDesign, OutputBrief, StorylinePlan

log = logging.getLogger("pmi.deliverable.engine")

#: What each planning stage contributes, so a partial fallback can say what it
#: actually lost instead of claiming the whole document is unplanned.
_STAGE_LOST = {
    "plan.complete_report": "the complete report plan",
    "plan.request_brief": "the reading of your request",
    "plan.storyline": "the argument and the choice of sections",
    "plan.document_design": "the page composition",
}


class PlanningError(RuntimeError):
    """Generation cannot proceed — the context said so."""


def build(context: GenerationContext, *, force: bool = False,
          knowledge_version: int = 0,
          content_revision: int = 0, cancel=None) -> Deliverable:
    """Plan a deliverable from a fully built context.

    `cancel` is checked between stages. Nothing is written to disk here, so a
    stopped build simply never returns a `Deliverable` — there is no partial
    document to clean up, which is the point of stopping between stages rather
    than inside one.
    """
    from app.agent.cancellation import check

    blocking = context.blocking_gaps()
    if blocking and not force:
        raise PlanningError("; ".join(gap.message for gap in blocking))

    # Everything that decides the *shape* of the document runs inside one
    # collector, so "did planning fall back?" is answered by what this build
    # did rather than by what the process happens to remember.
    with tasks.collect() as fell_back:
        check(cancel, "planning the complete report")
        complete = complete_report.plan(context)

    brief = request_interpreter.reconcile(complete.brief, context)
    log.info("brief: %s", request_interpreter.summarize(brief))
    plan = complete.storyline
    design = complete.design

    warnings = section_planner.validate(plan, context.evidence)
    warnings += section_planner.enforce_coverage(plan, brief, context.evidence)
    warnings += section_planner.enforce_limitations(plan, context.evidence)
    warnings += _enforce_design_sections(
        design, context, brief, plan, include_limitations=bool(fell_back))

    planned_by = "fallback" if fell_back else "llm"
    pages, bind_warnings = visual_planner.bind_layouts(
        design, context, plan, planned_by=planned_by)
    warnings += bind_warnings

    specs = DeliverableSpecs()
    check(cancel, "building the visuals")
    for page in pages:
        # The complete plan already chose each visual's editorial purpose.
        # Python derives and validates the actual chart/diagram specification,
        # avoiding another model request per slide.
        outcome = chart_planner.build_visuals(page, context, use_model=False)
        specs.charts.update(outcome.charts)
        specs.diagrams.update(outcome.diagrams)
        specs.tables.update(outcome.tables)
        warnings.extend(outcome.warnings)

    deliverable = Deliverable(
        deliverable_id=f"dlv_{uuid.uuid4().hex[:10]}",
        project_id=context.project_id,
        session_id=context.session_id,
        chat_id=context.chat_id,
        title=brief.title_proposal or context.display_name(),
        subtitle=context.subject_line() or context.reporting_period,
        document_kind=brief.document_kind,
        primary_format=brief.primary_format,
        audience_label=brief.audience_label,
        presentation_layout=context.presentation_layout,
        governing_message=plan.governing_message,
        executive_takeaway=plan.executive_takeaway,
        pages=pages,
        specs=specs,
        requested_sections=list(context.requested_sections),
        covered_sections=section_planner.coverage_map(plan, brief),
        fingerprint=fp.compute(context, brief=brief,
                               knowledge_version=knowledge_version,
                               content_revision=content_revision).model_dump(),
        planned_by=planned_by,                                  # type: ignore[arg-type]
        warnings=warnings,
    )
    deliverable.renumber()

    # Prose and titles come after the visuals: what a page says depends on
    # whether the chart it was designed around survived validation.
    check(cancel, "writing the pages")
    copy_by_page = {copy.page_id: copy for copy in complete.page_copy}
    for page in deliverable.pages:
        warnings.extend(narrative_writer.write_page(
            page, context, plan, use_model=False,
            copy=copy_by_page.get(page.page_id)))
        _remove_redundant_visual_text(page, context)
    warnings.extend(title_writer.write_titles(deliverable, context, plan,
                                              use_model=False,
                                              titles=complete.titles))
    for page in deliverable.pages:
        _ensure_readable_page(page, deliverable)
        _normalize_table_only_page(page, context)
    deliverable.warnings = warnings

    if fell_back:
        _mark_unplanned(deliverable, fell_back)

    for gap in context.gaps:
        if gap.severity != "note":
            deliverable.notes.append(f"{gap.message} {gap.remedy}".strip())

    log.info("planned %s: %d pages, %d layouts, planned_by=%s, %d warnings",
             deliverable.deliverable_id, deliverable.page_count,
             len(deliverable.layouts_used), planned_by, len(warnings))
    return deliverable


def _remove_redundant_visual_text(page: PageDesign,
                                  context: Optional[GenerationContext] = None
                                  ) -> None:
    """Let a visual carry the facts it already presents once.

    Commentary survives when it adds evidence the chart, diagram or table does
    not contain, and user-authored text always survives. The common generated
    duplicate — a paragraph or bullets built from exactly the visual's evidence
    — is removed at the planning boundary so every renderer receives the same
    clean page.
    """
    from app.deliverable.model import (
        BulletsElement,
        ChartElement,
        DiagramElement,
        TableElement,
    )

    visual_ids = {
        evidence_id
        for element in page.elements
        if isinstance(element, (ChartElement, DiagramElement, TableElement))
        for evidence_id in element.evidence_ids
    }
    if not visual_ids:
        return

    kept = []
    for element in page.elements:
        if isinstance(element, (TextElement, BulletsElement)):
            own = set(element.evidence_ids)
            duplicate = bool(own) and own <= visual_ids
            authored_by = getattr(element, "authored_by", "python")
            role = getattr(element, "role", "")
            if duplicate and authored_by != "user" and role in ("body", "bullets"):
                continue
            if (isinstance(element, BulletsElement) and context is not None
                    and authored_by != "user" and own & visual_ids):
                visual_statements = {
                    _normalised_statement(item.statement)
                    for item in context.evidence.resolve(own & visual_ids)
                    if item.statement
                }
                element.items = [
                    item for item in element.items
                    if _normalised_statement(item) not in visual_statements
                ]
                element.evidence_ids = [
                    evidence_id for evidence_id in element.evidence_ids
                    if evidence_id not in visual_ids
                ]
                if not element.items:
                    continue
        kept.append(element)
    page.elements = kept


def _normalised_statement(text: str) -> str:
    return " ".join((text or "").casefold().split()).strip(" .")


def _normalize_table_only_page(page: PageDesign,
                               context: GenerationContext) -> None:
    """Give a table the full page when duplicate commentary was removed.

    A planned chart can legitimately downgrade to a table after its data is
    validated.  If the generated commentary then says exactly what that table
    already says, deduplication removes it.  Keeping the old two-column layout
    would leave an empty column, so bind the surviving table to the template's
    native one-column table layout instead.
    """
    from app.deliverable.model import TableElement

    if len(page.elements) != 1 or not isinstance(page.elements[0], TableElement):
        return

    page.composition = "table_full"
    reference = context.template_reference
    catalog = getattr(reference, "catalog", None)
    choice = None
    if catalog is not None:
        choice = catalog.choose(
            composition="table_full",
            purpose=page.purpose,
            family="white",
            needs_subtitle=bool(page.subtitle),
            needs_picture=False,
        )
    if choice is not None:
        page.layout_id = choice.layout.layout_id
        page.layout_name = choice.layout.raw_name.strip()
        if choice.degraded and choice.reason not in page.warnings:
            page.warnings.append(choice.reason)

    page.elements[0].slot = visual_planner._content_slots(choice)[0]


def _ensure_readable_page(page: PageDesign, deliverable: Deliverable) -> None:
    """Remove duplicated furniture and give an empty chapter an honest body.

    Headline and kicker intents are already represented by ``page.title`` and
    ``page.subtitle``. PowerPoint knew to skip those elements, while PDF, Word,
    HTML and Markdown rendered them again as body copy. Normalising once here
    keeps every format aligned and prevents a heading from making an otherwise
    empty page look populated to the planning pipeline.
    """
    from app.deliverable.model import (
        BulletsElement,
        ChartElement,
        DiagramElement,
        ImageElement,
        KpiRowElement,
        TableElement,
    )

    if page.purpose in ("cover", "divider", "closing"):
        return

    page.elements = [
        element for element in page.elements
        if not (isinstance(element, TextElement)
                and element.role in ("headline", "kicker", "source_note"))
    ]
    if _same_heading(page.title, page.subtitle):
        page.subtitle = ""

    body_texts = [element.text for element in page.elements
                  if isinstance(element, TextElement)
                  and element.role in ("body", "callout", "quote")
                  and element.text.strip()]
    if any(_same_heading(text, page.subtitle) for text in body_texts):
        page.subtitle = ""

    def visible(element) -> bool:
        if isinstance(element, TextElement):
            return bool(element.text.strip())
        if isinstance(element, BulletsElement):
            return bool(element.items)
        if isinstance(element, KpiRowElement):
            return bool(element.tiles)
        if isinstance(element, ChartElement):
            return element.spec_id in deliverable.specs.charts
        if isinstance(element, DiagramElement):
            return element.spec_id in deliverable.specs.diagrams
        if isinstance(element, TableElement):
            spec = deliverable.specs.tables.get(element.spec_id)
            return bool(spec and spec.rows)
        if isinstance(element, ImageElement):
            return bool(element.image_ref)
        return False

    if any(visible(element) for element in page.elements):
        return

    # Honest message about what's missing, not a generic excuse. Mirroring
    # the language of app/report/planner.py's _uncovered() pattern.
    title = page.title or page.page_id
    fallback_text = f"{title} — the uploaded files don't cover this."
    page.elements.append(TextElement(
        element_id=f"{page.page_id}.body-empty",
        slot="col1",
        role="body",
        text=fallback_text,
        authored_by="python",
        prominence="primary",
    ))


def _same_heading(title: str, subtitle: str) -> bool:
    normalise = lambda value: " ".join((value or "").casefold().split())
    return bool(normalise(title)) and normalise(title) == normalise(subtitle)


def _enforce_design_sections(design: DocumentDesign,
                             context: GenerationContext,
                             brief: OutputBrief,
                             plan: StorylinePlan, *,
                             include_limitations: bool = True) -> list[str]:
    """Give every restored storyline section a page without another model call."""
    represented = {page.section_id for page in design.pages if page.section_id}
    missing = [
        section.section_id for section in plan.sections
        if section.section_id not in represented
        and (include_limitations
             or section.section_id != "data-quality-and-limitations")
    ]
    if not missing:
        return []

    fallback = visual_planner.fallback_design(context, brief, plan)
    by_section = {page.section_id: page for page in fallback.pages
                  if page.section_id}
    restored: list[str] = []
    for section_id in missing:
        page = by_section.get(section_id)
        if page is None:
            continue
        design.pages.append(page)
        restored.append(section_id)
    if restored:
        # This is a successful internal repair, not a limitation of the report.
        # Keep it in operational logs instead of printing it in the appendix.
        log.info("restored required section page(s) omitted by the design: %s",
                 ", ".join(restored))
    return []


def _mark_unplanned(deliverable: Deliverable, stages: Sequence[str]) -> None:
    """Record fallback provenance in logs without adding system copy to reports."""
    lost = [_STAGE_LOST[s] for s in dict.fromkeys(stages) if s in _STAGE_LOST]
    log.warning("%s used deterministic planning fallback for: %s",
                deliverable.deliverable_id, ", ".join(lost) or "unknown stage")


# ---------------------------------------------------------------- repairs
def regenerate_pages(deliverable: Deliverable, context: GenerationContext,
                     page_ids: Sequence[str], *, reason: str = "") -> Deliverable:
    """Rebuild exactly the named pages, reusing everything else.

    Extraction, the evidence index and the storyline are all untouched: a page
    that overflowed does not mean the argument was wrong, and re-planning to fix
    a layout would change text the user has already read and approved.
    """
    wanted = [p for p in page_ids if deliverable.page(p) is not None]
    missing = [p for p in page_ids if deliverable.page(p) is None]
    if missing:
        log.warning("cannot regenerate unknown page(s): %s", missing)
    if not wanted:
        return deliverable

    revised = deliverable.model_copy(deep=True)
    revised.version = deliverable.version + 1
    revised.parent_version = deliverable.version

    for page_id in wanted:
        page = revised.page(page_id)
        assert page is not None
        page.warnings.append(f"Regenerated: {reason}" if reason
                             else "Regenerated after review.")
        page.source_note = _refresh_source_note(page, context)

    revised.notes.append(
        f"Regenerated {len(wanted)} page(s) after review"
        + (f": {reason}" if reason else "."))
    log.info("regenerated %d page(s) of %s (v%d): %s", len(wanted),
             revised.deliverable_id, revised.version, ", ".join(wanted))
    return revised


def _refresh_source_note(page: PageDesign, context: GenerationContext) -> str:
    from app.evidence import provenance

    return provenance.source_note(context.evidence.resolve(page.evidence_ids))


def drain_planning_warnings() -> list[str]:
    """Warnings recorded by the planning tasks, for the caller's run record."""
    return tasks.drain_warnings()


# ------------------------------------------------------------------ delivery
class Delivered(BaseModel):
    """What a caller gets back: the files, and an honest account of them."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deliverable: Deliverable
    results: list = Field(default_factory=list)
    reviews: list = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)

    @property
    def paths(self) -> list:
        return [r.path for r in self.results if r.page_count]

    @property
    def review(self):
        return self.reviews[-1] if self.reviews else None

    @property
    def shipped_with_findings(self) -> list[str]:
        return self.review.disclosures() if self.review else []


def deliver(context: GenerationContext, *, formats: Optional[Sequence[str]] = None,
            out_dir: Optional[Path] = None, force: bool = False,
            knowledge_version: int = 0, content_revision: int = 0) -> Delivered:
    """Plan, render, review, repair, re-render — the whole §16 pipeline.

    The repair loop is capped at `quality.MAX_REPAIR_PASSES`. A page that fails
    twice is delivered with its finding recorded *in the artifact*, because a
    review loop run against a model's judgement can oscillate indefinitely and a
    document that never ships is worse than one that ships with a stated flaw.
    """
    from app import quality
    from app.config import get_settings
    from app.renderers import registry

    deliverable = build(context, force=force,
                        knowledge_version=knowledge_version,
                        content_revision=content_revision)
    wanted = [registry.normalize(f) for f in
              (formats or [deliverable.primary_format])]
    target = Path(out_dir) if out_dir is not None else (
        Path(get_settings().output_dir)
        / (context.project_id or context.session_id or "adhoc"))

    # Cheap checks first: a grounding failure is worth catching before four
    # files have been written.
    reviews = [quality.review_plan(deliverable, context)]
    if not reviews[-1].passed:
        deliverable, applied = quality.repair(deliverable, context, reviews[-1])
    else:
        applied = []

    results = registry.render_all(deliverable, context, target, wanted)
    primary = next((r for r in results if r.page_count), None)

    for attempt in range(2, quality.MAX_REPAIR_PASSES + 2):
        reviewed = quality.review(deliverable, context, primary,
                                  pass_number=attempt)
        reviews.append(reviewed)
        if reviewed.passed or attempt > quality.MAX_REPAIR_PASSES:
            if not reviewed.passed:
                log.info("shipping %s with %d unresolved finding(s) after %d "
                         "pass(es)", deliverable.deliverable_id,
                         len(reviewed.blocking) + len(reviewed.fixable),
                         attempt - 1)
            break
        deliverable, repaired = quality.repair(deliverable, context, reviewed)
        applied += repaired
        results = registry.render_all(deliverable, context, target, wanted)
        primary = next((r for r in results if r.page_count), None)

    for result in results:
        deliverable.warnings.extend(
            w for w in result.warnings if w not in deliverable.warnings)

    return Delivered(deliverable=deliverable, results=results, reviews=reviews,
                     repairs=applied)
