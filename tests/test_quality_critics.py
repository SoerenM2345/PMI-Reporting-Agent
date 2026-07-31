"""The four critics and the repair loop (`app/quality/`).

Each critic is tested by giving it something genuinely wrong and checking it says
so, in words a user could act on — and by giving it something right and checking
it stays quiet. A critic that fires on a clean document costs a regeneration pass
and rewrites text the user had already accepted, so false positives are failures
too.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.context import builder
from app.context.schemas import KnowledgeDigest, UserConstraint
from app.deliverable import engine
from app.deliverable.model import (
    BulletsElement,
    ChartElement,
    Deliverable,
    PageDesign,
    TextElement,
)
from app.extractors.base import make_source
from app.models.entities import PMIProject
from app.models.pmi import (
    BudgetItem,
    Conflict,
    Milestone,
    PMIDataModel,
    Risk,
    Severity,
    SourceFormat,
    Status,
    Task,
)
from app.models.quality import ConflictEvidence
from app.quality import completeness, design_review, grounding, overflow, rasterize
from app.quality import repair, review, review_plan
from app.quality import textmetrics
from app.renderers import registry

XLSX, PNG = SourceFormat.EXCEL, SourceFormat.IMAGE
TODAY = date(2026, 7, 27)


@pytest.fixture
def model() -> PMIDataModel:
    from app.agent.calculations import recompute_derived

    xlsx = make_source("integration_tracker.xlsx", XLSX, sheet_name="Workplan")
    image = make_source("risk_dashboard.png", PNG, extraction_confidence=0.35)
    built = PMIDataModel(
        project=PMIProject(project_id="p1", reporting_date=TODAY,
                           reporting_period="July 2026",
                           day_1_date=TODAY + timedelta(days=66)),
        source_files=["integration_tracker.xlsx", "risk_dashboard.png"],
        tasks=[Task(task_id="T1", title="Payroll cutover", owner="Anna Schmidt",
                    workstream="Finance", due_date=TODAY - timedelta(days=3),
                    status=Status.IN_PROGRESS, progress_percentage=60.0,
                    source_references=[xlsx])],
        milestones=[Milestone(milestone_id="M1", name="ERP go-live",
                              planned_date=date(2026, 9, 15),
                              forecast_date=date(2026, 9, 30),
                              status=Status.IN_PROGRESS,
                              source_references=[xlsx]),
                    Milestone(milestone_id="M2", name="Legal close",
                              planned_date=date(2026, 8, 1),
                              status=Status.COMPLETED,
                              source_references=[xlsx])],
        risks=[Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                    impact=5, status=Status.IN_PROGRESS,
                    source_references=[image])],
        budget=[BudgetItem(budget_item_id="B1", category="ERP migration",
                           budget=1_000_000.0, actual=900_000.0,
                           forecast=1_220_000.0, currency="EUR",
                           source_references=[xlsx]),
                BudgetItem(budget_item_id="B2", category="Rebranding",
                           budget=400_000.0, actual=380_000.0,
                           forecast=470_000.0, currency="EUR",
                           source_references=[xlsx])],
    )
    built, issues = recompute_derived(built, TODAY)
    built.validation_issues.extend(issues)
    return built


def context_for(model, request_text="Prepare a SteerCo pack.", **kwargs):
    return builder._assemble(
        scope="project", project_id="proj", chat_id=None, session_id=None,
        model=model,
        digest=kwargs.pop("digest", KnowledgeDigest(
            free_text="MedAxis SE is integrating NordCare GmbH.")),
        folder_name="", quality=None, request_text=request_text,
        requested_format=None, messages=[])


@pytest.fixture
def clean(model, scripted_planning):
    """A document that should pass every critic."""
    context = context_for(model)
    return engine.build(context), context


# ================================================================== grounding
def test_a_clean_document_passes_grounding(clean):
    deliverable, context = clean
    assert grounding.check(deliverable, context).passed


def test_an_invented_figure_in_model_prose_blocks(clean):
    deliverable, context = clean
    page = deliverable.pages[2]
    page.elements.append(TextElement(
        element_id="bad", role="body", authored_by="llm",
        evidence_ids=["ev:budget:B1"],
        text="Spending has overrun by EUR 987,654 this quarter."))

    reviewed = grounding.check(deliverable, context)
    assert reviewed.verdict == "block"
    blocking = reviewed.blocking[0]
    assert "987654" in blocking.message or "987,654" in blocking.detail
    assert blocking.page_id == page.page_id
    assert blocking.suggested_action == "regenerate_page"


def test_the_same_figure_from_the_user_is_flagged_not_rejected(clean):
    """The user is allowed to know something the files do not. A model is not."""
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="user", role="body", authored_by="user",
        text="Spending has overrun by EUR 987,654 this quarter."))

    reviewed = grounding.check(deliverable, context)
    assert reviewed.verdict != "block"
    assert any("written by the user" in f.message for f in reviewed.warnings)


def test_an_invented_person_blocks(clean):
    """A hallucinated owner is worse than a hallucinated number: somebody will
    go looking for her."""
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="ghost", role="body", authored_by="llm",
        evidence_ids=["ev:risk:R1"],
        text="This risk is owned by Sarah Chen in the Bergmann workstream."))

    reviewed = grounding.check(deliverable, context)
    assert reviewed.verdict == "block"
    assert any("Sarah Chen" in f.message for f in reviewed.blocking)


def test_a_person_who_is_in_the_evidence_is_accepted(clean):
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="real", role="body", authored_by="llm",
        evidence_ids=["ev:task:T1"],
        text="Anna Schmidt owns the payroll cutover in the Finance workstream."))
    assert grounding.check(deliverable, context).passed


def test_a_company_name_from_project_context_is_accepted(clean):
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="names", role="body", authored_by="llm",
        evidence_ids=["ev:task:T1"],
        text="MedAxis SE and NordCare GmbH are aligning payroll."))
    assert grounding.check(deliverable, context).passed


def test_an_invented_date_blocks(clean):
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="date", role="body", authored_by="llm",
        evidence_ids=["ev:milestone:M1"],
        text="The go-live was rescheduled to 04-11-2027."))

    reviewed = grounding.check(deliverable, context)
    assert reviewed.verdict == "block"
    assert any("date" in f.message for f in reviewed.blocking)


def test_a_date_in_the_evidence_is_accepted_in_any_format(clean):
    """`15-09-2026`, `2026-09-15` and `15 September 2026` are one date, and the
    renderers legitimately use different formats."""
    deliverable, context = clean
    for text in ("Planned for 15-09-2026.", "Planned for 2026-09-15.",
                 "Planned for 15 September 2026."):
        deliverable.pages[2].elements = [TextElement(
            element_id="d", role="body", authored_by="llm",
            evidence_ids=["ev:milestone:M1"], text=text)]
        assert grounding.check(deliverable, context).passed, text


def test_an_unlinked_figure_is_flagged_for_citation(clean):
    """Whether a figure is *supported* is one question; whether it is *linked*
    is a weaker one, so this warns rather than blocking."""
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="unbound", role="body", authored_by="llm", evidence_ids=[],
        text="Progress stands at 60%."))
    reviewed = grounding.check(deliverable, context)
    unlinked = [f for f in reviewed.findings if f.element_id == "unbound"]
    assert unlinked and unlinked[0].severity == "warn"
    assert unlinked[0].suggested_action == "add_citation"


def test_a_term_of_art_containing_a_digit_is_not_a_figure(clean):
    """"Day 1", "Q4" and "phase 2" are PMI vocabulary. Blocking a page for
    saying "before Day 1" costs a regeneration and rewrites accepted text."""
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="termofart", role="body", authored_by="llm", evidence_ids=[],
        text="The mitigation window closes as Day 1 approaches in Q4."))
    assert not [f for f in grounding.check(deliverable, context).findings
                if f.element_id == "termofart"]


def test_a_chart_that_stops_validating_blocks(clean):
    """A repair pass can edit a page after the chart planner validated it."""
    deliverable, context = clean
    spec = next(iter(deliverable.specs.charts.values()))
    spec.series[0].points[0].value = 424242.0

    reviewed = grounding.check(deliverable, context)
    assert reviewed.verdict == "block"
    assert any("no longer validates" in f.message for f in reviewed.blocking)


def test_titles_are_grounded_too(clean):
    deliverable, context = clean
    deliverable.pages[2].title = "Spend is EUR 5,555,555 over budget"
    assert grounding.check(deliverable, context).verdict == "block"


# =============================================================== completeness
def test_a_clean_document_passes_completeness(clean):
    deliverable, context = clean
    assert completeness.check(deliverable, context).passed


def test_a_requested_topic_that_is_nowhere_blocks(model, scripted_planning):
    context = context_for(model, "Prepare a pack:\n1. Risks\n2. TSA exit readiness")
    deliverable = engine.build(context)
    # Simulate a page being lost after planning.
    deliverable.pages = [p for p in deliverable.pages
                         if "tsa" not in p.page_id]
    deliverable.covered_sections["TSA exit readiness"] = ["tsa-exit-readiness"]

    reviewed = completeness.check(deliverable, context)
    assert reviewed.verdict == "block"
    assert any("TSA exit readiness" in f.message for f in reviewed.blocking)


def test_a_retitled_section_still_counts_as_coverage(model, scripted_planning):
    context = context_for(model, "Prepare a pack:\n1. Budget position\n2. Risks")
    deliverable = engine.build(context)
    assert completeness.check(deliverable, context).passed


def test_omitting_must_disclose_evidence_blocks(model, scripted_planning):
    """The check the whole evidence layer exists to make possible.

    Three layers could drop it — retrieval, planning, a repair pass — so it is
    verified against the artifact rather than trusted in the middle.
    """
    context = context_for(model)
    deliverable = engine.build(context)
    required = context.evidence.must_include()
    assert required, "the fixture must have must-include evidence"

    for page in deliverable.pages:
        page.evidence_ids = [i for i in page.evidence_ids if i not in required]
    deliverable.specs.charts.clear()
    deliverable.specs.tables.clear()
    deliverable.specs.diagrams.clear()

    reviewed = completeness.check(deliverable, context)
    assert reviewed.verdict == "block"
    blocking = reviewed.blocking[0]
    assert "must be disclosed" in blocking.message
    assert set(blocking.evidence_ids) & set(required)


def test_presenting_a_contested_figure_as_settled_blocks(model,
                                                        scripted_planning):
    model.conflicts.append(Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("integration_tracker.xlsx", XLSX),
            value="2026-09-15"),
            ConflictEvidence(
                source_reference=make_source("weekly.pptx",
                                             SourceFormat.POWERPOINT),
                value="2026-10-01")]))
    context = context_for(model)
    deliverable = engine.build(context, force=True)

    # Strip every mention of the disagreement.
    for page in deliverable.pages:
        page.source_note = ""
        for element in page.elements:
            if hasattr(element, "text"):
                element.text = "All figures are agreed."
            if hasattr(element, "items"):
                element.items = []
    deliverable.notes.clear()
    deliverable.specs.tables.clear()

    assert any("disputed" in f.message
               for f in completeness.check(deliverable, context).blocking)


def test_an_unlabelled_assumption_is_a_fix(model, scripted_planning):
    context = context_for(
        model, digest=KnowledgeDigest(
            assumptions=["Headcount synergies land in Q4."]))
    deliverable = engine.build(context)
    assumption = context.evidence.of_kind("assumption")[0]
    deliverable.pages[1].evidence_ids.append(assumption.evidence_id)
    for page in deliverable.pages:
        for element in page.elements:
            if hasattr(element, "text"):
                element.text = "Everything is fine."

    reviewed = completeness.check(deliverable, context)
    assert any("assumption" in f.message for f in reviewed.fixable)


def test_a_page_budget_the_document_exceeds_is_a_fix(model, scripted_planning):
    context = context_for(model, "A one-pager for the CFO.")
    context.user_constraints.append(
        UserConstraint(kind="max_pages", value="1"))
    deliverable = engine.build(context)

    reviewed = completeness.check(deliverable, context)
    assert any("at most 1 page" in f.message for f in reviewed.fixable)


def test_charts_the_user_refused_are_a_fix(model, scripted_planning):
    context = context_for(model, "A SteerCo pack, no charts.")
    deliverable = engine.build(context)
    if not any(p.of_role("chart") for p in deliverable.pages):
        pytest.skip("this plan produced no chart")
    assert any("no charts" in f.message
               for f in completeness.check(deliverable, context).fixable)


def test_a_transcribed_figure_that_is_never_disclosed_is_a_fix(clean):
    deliverable, context = clean
    for page in deliverable.pages:
        page.source_note = ""
        for element in page.elements:
            if hasattr(element, "caption"):
                element.caption = ""
    for spec in deliverable.specs.tables.values():
        spec.caption = ""
    assert any("read from an image" in f.message
               for f in completeness.check(deliverable, context).fixable)


# =================================================================== overflow
def test_an_overlong_title_is_caught_analytically(clean, tmp_path):
    """The template's title box is 12.33 x 0.37in at 21pt."""
    deliverable, context = clean
    deliverable.pages[2].title = (
        "This title is far too long to fit inside the template's single-line "
        "title placeholder and will therefore run out of its box and off the "
        "edge of the slide where nobody can read it at all")

    result = registry.render(deliverable, context, tmp_path, "pptx")
    reviewed = overflow.check(result, deliverable, context)
    assert reviewed.verdict in ("fix", "fix_then_ship")
    assert any("does not fit" in f.message for f in reviewed.fixable)
    assert any(f.page_id == deliverable.pages[2].page_id
               for f in reviewed.fixable)


def test_a_clean_deck_has_no_overflow(clean, tmp_path):
    deliverable, context = clean
    result = registry.render(deliverable, context, tmp_path, "pptx")
    reviewed = overflow.check(result, deliverable, context)
    assert not reviewed.blocking, [f.message for f in reviewed.blocking]


def test_content_off_the_canvas_is_caught(clean, tmp_path):
    from app.renderers.common import MeasuredBox, RenderResult

    _deliverable, context = clean
    result = RenderResult(path=tmp_path / "x.pptx", page_count=1,
                          element_boxes=[MeasuredBox(
                              page_id="p", name="pmi:body", left_in=12.0,
                              top_in=1.0, width_in=4.0, height_in=1.0,
                              text="off the edge")])
    reviewed = overflow.check_pptx(result, _deliverable, context)
    assert any("past the edge" in f.message for f in reviewed.fixable)


def test_overlapping_content_is_caught(clean, tmp_path):
    from app.renderers.common import MeasuredBox, RenderResult

    deliverable, context = clean
    boxes = [MeasuredBox(page_id="p", name="pmi:body", left_in=1.0, top_in=2.0,
                         width_in=4.0, height_in=2.0, text="a"),
             MeasuredBox(page_id="p", name="pmi:callout", left_in=1.2,
                         top_in=2.2, width_in=4.0, height_in=2.0, text="b")]
    result = RenderResult(path=tmp_path / "x.pptx", page_count=1,
                          element_boxes=boxes)
    assert any("overlap" in f.message
               for f in overflow.check_pptx(result, deliverable, context).fixable)


def test_a_page_with_a_title_and_nothing_under_it_blocks(clean, tmp_path):
    deliverable, context = clean
    page = deliverable.pages[2]
    page.elements = []
    result = registry.render(deliverable, context, tmp_path, "pptx")
    assert any("nothing under it" in f.message or "no content" in f.message
               for f in overflow.check(result, deliverable, context).blocking)


def test_the_pdf_is_rasterised_and_checked_for_blank_pages(clean, tmp_path):
    deliverable, context = clean
    result = registry.render(deliverable, context, tmp_path, "pdf")
    reviewed = overflow.check(result, deliverable, context)
    assert not reviewed.blocking, [f.message for f in reviewed.blocking]

    pages = rasterize.pdf_pages(result.path)
    assert pages and all(not rasterize.is_blank(p) for p in pages)


@pytest.mark.skipif(not rasterize.has_soffice(),
                    reason="LibreOffice is not installed; the deck cannot be "
                           "rasterised, so its visual check is analytic only")
def test_the_deck_rasterises_when_libreoffice_is_available(clean, tmp_path):
    deliverable, context = clean
    result = registry.render(deliverable, context, tmp_path, "pptx")
    pages = rasterize.pptx_pages(result.path)
    assert pages and len(pages) == deliverable.page_count
    assert all(not rasterize.is_blank(page) for page in pages)


def test_deck_rasterisation_reports_absence_rather_than_success(clean, tmp_path):
    """`None` means "not checked", never "checked and fine"."""
    deliverable, context = clean
    result = registry.render(deliverable, context, tmp_path, "pptx")
    pages = rasterize.pptx_pages(result.path)
    if rasterize.has_soffice():
        assert pages is not None
    else:
        assert pages is None


# ================================================================== metrics
def test_measurement_wraps_on_words_and_reports_lines():
    extent = textmetrics.measure(
        "Forecast integration spend exceeds the approved budget envelope",
        size_pt=12.0, max_width_in=2.0)
    assert extent.line_count > 1
    assert extent.width_in <= 2.0 + 0.01
    assert extent.height_in > 0.2


def test_measurement_is_pessimistic_not_optimistic():
    """Over-estimating flags text that would have fitted; under-estimating
    ships a deck with a title off the slide."""
    text = "Forecast spend exceeds the approved envelope"
    padded = textmetrics.text_width_in(text, size_pt=12.0)
    bare = padded / textmetrics.SAFETY_MARGIN
    assert padded > bare
    assert textmetrics.SAFETY_MARGIN > 1.0


def test_a_size_that_fits_can_be_found_or_ruled_out():
    short = textmetrics.largest_size_that_fits(
        "Short title", box_width_in=12.0, box_height_in=0.4, ceiling_pt=21.0)
    assert short == 21.0

    impossible = textmetrics.largest_size_that_fits(
        "word " * 400, box_width_in=2.0, box_height_in=0.3, ceiling_pt=21.0)
    assert impossible is None


def test_shortening_prefers_a_sentence_boundary():
    text = ("Spending is inside budget on actuals. The forecast is not. "
            "The Committee should decide how it is funded.")
    shortened = textmetrics.shorten_to_fit(
        text, size_pt=12.0, box_width_in=3.0, box_height_in=0.45)
    assert len(shortened) < len(text)
    assert shortened.endswith((".", "…"))
    assert "…" not in shortened or shortened.count(".") == 0


def test_the_measured_font_is_named_not_assumed():
    """Aptos is a Microsoft font and is usually absent from a build host."""
    assert textmetrics.measured_font_name()


# ==================================================================== design
def test_a_clean_document_raises_no_design_blockers(clean):
    deliverable, context = clean
    reviewed = design_review.review(deliverable, context, use_model=False)
    assert not reviewed.blocking, [f.message for f in reviewed.blocking]


def test_the_heuristic_only_mode_says_so(clean):
    """"The design was reviewed" and "six heuristics ran" are different claims."""
    deliverable, context = clean
    reviewed = design_review.review(deliverable, context, use_model=False)
    assert any("heuristics only" in f.message for f in reviewed.findings)
    assert any("Nothing has looked at the rendered pages" in f.message
               for f in reviewed.findings)


def test_every_page_the_same_shape_is_flagged(clean):
    deliverable, context = clean
    for page in deliverable.pages:
        if page.purpose == "content":
            page.composition = "single"
    reviewed = design_review.review(deliverable, context, use_model=False)
    assert any("same composition" in f.message or "consecutive pages" in f.message
               for f in reviewed.findings)


def test_topic_titles_are_flagged(clean):
    deliverable, context = clean
    deliverable.pages[2].title = "Risks"
    deliverable.pages[3].title = "Budget"
    reviewed = design_review.review(deliverable, context, use_model=False)
    assert any("name a topic rather than state a finding" in f.message
               for f in reviewed.findings)


def test_placeholder_text_that_survived_blocks(clean):
    deliverable, context = clean
    deliverable.pages[2].elements.append(TextElement(
        element_id="tbd", role="body", text="Click to add text"))
    assert any("placeholder text" in f.message
               for f in design_review.review(deliverable, context,
                                             use_model=False).blocking)


def test_an_overlong_bullet_is_flagged(clean):
    deliverable, context = clean
    deliverable.pages[2].elements.append(BulletsElement(
        element_id="long", items=["word " * 50]))
    assert any("paragraph rather than a bullet" in f.message
               for f in design_review.review(deliverable, context,
                                             use_model=False).findings)


def test_a_deck_on_one_layout_is_a_fix(clean):
    deliverable, context = clean
    for page in deliverable.pages:
        page.layout_id = "27:title-only"
    assert any("one layout" in f.message
               for f in design_review.review(deliverable, context,
                                             use_model=False).fixable)


# ================================================================ the review
def test_the_combined_review_runs_every_critic(clean, tmp_path):
    deliverable, context = clean
    result = registry.render(deliverable, context, tmp_path, "pptx")
    reviewed = review(deliverable, context, result, use_model=False)
    for critic in ("grounding", "completeness", "overflow", "design"):
        assert reviewed.by_critic(critic) is not None
    assert reviewed.verdict in ("ship", "fix_then_ship", "block")


def test_the_plan_review_needs_no_rendered_file(clean):
    deliverable, context = clean
    reviewed = review_plan(deliverable, context)
    assert reviewed.format == ""
    assert reviewed.by_critic("grounding") is not None


def test_pages_to_regenerate_are_ordered_by_severity(clean):
    from app.quality.schemas import ArtifactReview, finding

    reviewed = ArtifactReview()
    reviewed.add(finding("design", "warn", "cosmetic", page_id="c"),
                 finding("overflow", "fix", "overflows", page_id="b"),
                 finding("grounding", "block", "ungrounded", page_id="a"))
    # A `warn` page is not rebuilt: the finding is disclosed instead.
    assert reviewed.pages_to_regenerate == ["a", "b"]
    assert reviewed.verdict == "block"
    assert "cosmetic" in reviewed.disclosures()


# ==================================================================== repair
def test_repair_rewrites_an_ungrounded_page_from_the_evidence(clean):
    deliverable, context = clean
    page = deliverable.pages[2]
    page.elements = [TextElement(
        element_id="bad", role="body", authored_by="llm",
        evidence_ids=["ev:risk:R1"],
        text="The overrun is EUR 987,654 and Sarah Chen owns it.")]

    reviewed = grounding.check(deliverable, context)
    assert reviewed.verdict == "block"

    repaired, applied = repair(deliverable, context, reviewed)
    assert applied
    assert repaired.version == deliverable.version + 1

    fixed = repaired.page(page.page_id)
    body = fixed.elements[0].text
    assert "987,654" not in body and "Sarah Chen" not in body
    assert fixed.elements[0].authored_by == "python"
    assert grounding.check(repaired, context).passed


def test_repair_shortens_rather_than_truncating_mid_clause(clean):
    from app.quality.schemas import ArtifactReview, finding

    deliverable, context = clean
    page = deliverable.pages[2]
    page.title = ("A title long enough that it cannot possibly fit inside the "
                  "template's single line title placeholder at twenty one point")

    reviewed = ArtifactReview()
    reviewed.add(finding("overflow", "fix", "does not fit",
                         page_id=page.page_id, action="shorten"))
    repaired, applied = repair(deliverable, context, reviewed)
    assert applied
    assert len(repaired.page(page.page_id).title) < len(page.title)


def test_repair_drops_an_element_the_user_refused(clean):
    from app.quality.schemas import ArtifactReview, finding

    deliverable, context = clean
    page = next((p for p in deliverable.pages if p.of_role("chart")), None)
    if page is None:
        pytest.skip("this plan produced no chart")

    reviewed = ArtifactReview()
    reviewed.add(finding("completeness", "fix", "no charts were wanted",
                         page_id=page.page_id, action="drop_element"))
    repaired, _applied = repair(deliverable, context, reviewed)
    assert not repaired.page(page.page_id).of_role("chart")


def test_an_unrepairable_finding_is_disclosed_in_the_artifact(clean):
    """A document that failed review and does not say so is worse than one that
    fails visibly: the reader has no way to know."""
    from app.quality.schemas import ArtifactReview, finding

    deliverable, context = clean
    reviewed = ArtifactReview()
    reviewed.add(finding("completeness", "block",
                         "A finding that must be disclosed appears nowhere.",
                         action="none"))

    repaired, _applied = repair(deliverable, context, reviewed)
    assert any("did not pass its own review" in w for w in repaired.warnings)
    callouts = repaired.pages[0].of_role("callout")
    assert any("appears nowhere" in c.text for c in callouts)
    assert callouts[0].emphasis == "bad"


def test_a_passing_review_repairs_nothing(clean):
    deliverable, context = clean
    reviewed = review_plan(deliverable, context)
    if not reviewed.passed:
        pytest.skip(f"the fixture does not pass cleanly: {reviewed.summary()}")
    repaired, applied = repair(deliverable, context, reviewed)
    assert repaired is deliverable and applied == []


# ================================================================== delivery
def test_deliver_runs_the_whole_pipeline(model, scripted_planning, tmp_path):
    context = context_for(model)
    delivered = engine.deliver(context, formats=["pptx", "pdf"],
                               out_dir=tmp_path)

    assert len(delivered.results) == 2
    assert all(result.path.is_file() for result in delivered.results)
    assert delivered.reviews, "a delivery must be reviewed"
    assert delivered.review.verdict in ("ship", "fix_then_ship", "block")


def test_delivery_caps_the_repair_loop(model, scripted_planning, tmp_path,
                                      monkeypatch):
    """An unbounded loop against a model's judgement can oscillate forever."""
    from app import quality
    from app.quality.schemas import ArtifactReview, finding

    calls = []

    def always_broken(*_args, **kwargs):
        calls.append(kwargs.get("pass_number", 0))
        reviewed = ArtifactReview(pass_number=kwargs.get("pass_number", 1))
        reviewed.add(finding("design", "fix", "never satisfied", page_id="cover",
                             action="none"))
        return reviewed

    monkeypatch.setattr(quality, "review", always_broken)
    delivered = engine.deliver(context_for(model), formats=["pptx"],
                               out_dir=tmp_path)

    assert len(calls) <= quality.MAX_REPAIR_PASSES + 1
    assert delivered.results[0].path.is_file(), "it must still ship"
    assert delivered.shipped_with_findings


def test_delivery_discloses_what_it_shipped_with(model, scripted_planning,
                                                tmp_path):
    context = context_for(model)
    delivered = engine.deliver(context, formats=["pptx"], out_dir=tmp_path)
    if delivered.review.passed:
        assert delivered.shipped_with_findings == []
    else:
        assert delivered.shipped_with_findings
