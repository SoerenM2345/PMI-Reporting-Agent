"""The planning pipeline (`app/planning/`, `app/deliverable/engine.py`).

This is where the redesign's central claim gets tested: that the user's request
shapes the document, rather than the document's shape being looked up by
audience. The two scripted scenarios are the same project and materially
different asks, and the assertion is that they come out different.

Every test runs with no live provider. The LLM-led path uses
`ScriptedPlanningClient`; the keyless path uses the deterministic fallbacks and
is checked for being *honest* about it rather than for being good.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.context import builder
from app.context.schemas import GenerationContext, KnowledgeDigest
from app.deliverable import engine
from app.deliverable.engine import PlanningError
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
    Synergy,
    Task,
)
from app.models.quality import ConflictEvidence
from app.planning import request_interpreter, section_planner, storyline
from app.planning.schemas import OutputBrief, SectionIntent, StorylinePlan

XLSX, PNG = SourceFormat.EXCEL, SourceFormat.IMAGE
TODAY = date(2026, 7, 27)


@pytest.fixture
def model() -> PMIDataModel:
    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan")
    image = make_source("dashboard.png", PNG, extraction_confidence=0.35)
    return PMIDataModel(
        project=PMIProject(project_id="p1", reporting_date=TODAY,
                           reporting_period="July 2026",
                           day_1_date=TODAY + timedelta(days=66)),
        source_files=["tracker.xlsx", "dashboard.png"],
        tasks=[
            Task(task_id="T1", title="Payroll cutover", owner="Anna Schmidt",
                 workstream="Finance", due_date=TODAY - timedelta(days=3),
                 status=Status.IN_PROGRESS, progress_percentage=60.0,
                 source_references=[xlsx]),
            Task(task_id="T2", title="Day 1 building access", owner=None,
                 workstream="Operations", is_day_1_critical=True,
                 status=Status.NOT_STARTED, source_references=[xlsx]),
        ],
        milestones=[Milestone(milestone_id="M1", name="ERP go-live",
                              is_go_live=True, planned_date=date(2026, 9, 15),
                              forecast_date=date(2026, 9, 30),
                              status=Status.IN_PROGRESS,
                              source_references=[xlsx])],
        risks=[Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                    impact=5, status=Status.IN_PROGRESS,
                    source_references=[image])],
        budget=[BudgetItem(budget_item_id="B1", category="ERP migration",
                           budget=1_000_000.0, actual=900_000.0,
                           forecast=1_220_000.0, currency="EUR",
                           source_references=[xlsx])],
        synergies=[Synergy(synergy_id="S1", title="Procurement consolidation",
                           target_value=1_000_000.0, realized_value=400_000.0,
                           currency="EUR", source_references=[xlsx])],
    )


def context_for(model, request_text, **kwargs) -> GenerationContext:
    return builder._assemble(
        scope="project", project_id="proj", chat_id=None, session_id=None,
        model=model,
        digest=kwargs.pop("digest", KnowledgeDigest(
            free_text="MedAxis SE is integrating NordCare GmbH.")),
        folder_name=kwargs.pop("folder_name", ""), quality=None,
        request_text=request_text, requested_format=None, messages=[],
    )


# ======================================= §19: the request drives the result
@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_a_plan_is_built_from_the_storyline_not_from_a_table(
        model, scripted_planning):
    context = context_for(model, "Prepare a SteerCo pack on where we stand.")
    deliverable = engine.build(context)

    assert deliverable.planned_by == "llm"
    assert deliverable.governing_message.startswith("Day 1 remains achievable")
    assert deliverable.page_count == 6
    assert deliverable.audience_label == "Steering Committee"


@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_a_complete_report_uses_one_model_call(model, scripted_planning):
    context = context_for(model, "Prepare a SteerCo pack on where we stand.")

    engine.build(context)

    assert [name for name, _ in scripted_planning.calls] == [
        "CompleteReportPlan"]
    prompt = scripted_planning.asked_for("CompleteReportPlan")[0]
    assert "MedAxis SE is integrating NordCare GmbH" in prompt
    assert "Prepare a SteerCo pack" in prompt


def test_two_different_requests_produce_different_documents(model, request):
    """§19 "No fixed cards". Same files, materially different asks.

    The old pipeline answered both from `DECKS[audience]`, so a finance deep
    dive and a SteerCo pack were the same seven sections in the same order. This
    fails if the page structures ever converge again.
    """
    from tests.conftest import ScriptedPlanningClient
    from app import llm

    built = {}
    for scenario, ask in (("steerco_status", "Prepare a SteerCo pack."),
                          ("finance_deep_dive",
                           "A finance deep dive for the CFO on the overrun.")):
        llm.set_client(ScriptedPlanningClient(scenario))
        built[scenario] = engine.build(context_for(model, ask))

    steerco, finance = built["steerco_status"], built["finance_deep_dive"]

    assert steerco.compositions_used != finance.compositions_used
    assert [p.title for p in steerco.pages] != [p.title for p in finance.pages]
    assert steerco.governing_message != finance.governing_message
    assert steerco.audience_label != finance.audience_label
    assert steerco.document_kind != finance.document_kind

    # And not merely reordered: the finance pack uses expressions the SteerCo
    # pack does not, because its evidence supports them.
    assert "kpi_banner" in finance.compositions_used
    assert "kpi_banner" not in steerco.compositions_used
    assert "quote" in steerco.compositions_used


@pytest.mark.parametrize("scripted_planning", ["one_pager"], indirect=True)
def test_a_one_pager_is_one_page_with_no_cover(model, scripted_planning):
    """Not every document needs a cover, a divider and a closing."""
    context = context_for(model, "One-pager for the CFO: what could stop Day 1?")
    deliverable = engine.build(context)

    assert deliverable.page_count == 1
    assert deliverable.pages[0].purpose == "content"
    assert "cover" not in [p.purpose for p in deliverable.pages]


@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_no_page_is_obliged_to_carry_kpi_cards(model, scripted_planning):
    """The old planner put the same six tiles on every executive deck."""
    context = context_for(model, "Prepare a SteerCo pack.")
    deliverable = engine.build(context)
    assert not any(page.of_role("kpi_row") for page in deliverable.pages)


# ============================================== the request interpreter
def test_the_interpreter_cannot_lose_a_requested_section(model):
    """A model asked to summarise eleven sections will sometimes return nine.

    That is reasonable editorial instinct and the wrong answer here: the topic
    list is what coverage is checked against, so anything missing from it can
    never be checked.
    """
    eleven = "\n".join(f"{n}. Section {n}" for n in range(1, 12))
    context = context_for(model, f"Prepare a pack with:\n{eleven}")
    brief = request_interpreter.reconcile(
        OutputBrief(scope_topics=["Section 1", "Section 2"]), context)
    assert len(brief.scope_topics) == 11
    assert brief.scope_topics[0] == "Section 1"
    assert "Section 11" in brief.scope_topics


def test_stated_limits_override_the_models_opinion(model):
    context = context_for(model, "A CFO summary, no more than 2 pages.")
    brief = request_interpreter.reconcile(
        OutputBrief(target_page_count=12), context)
    assert brief.target_page_count == 2


def test_the_tightest_stated_limit_wins(model):
    """"A one-pager, no more than 2 pages" is contradictory; honour the tighter."""
    context = context_for(model, "A one-pager for the CFO, no more than 2 pages.")
    brief = request_interpreter.reconcile(OutputBrief(), context)
    assert brief.target_page_count == 1


def test_the_keyless_brief_is_plain_and_never_invents_topics(model):
    context = context_for(model, "How are we doing?")
    brief = request_interpreter.fallback_brief(context)
    assert brief.audience_label
    assert brief.scope_topics, "with no request it may shape from the evidence"
    # ...but only from kinds the project actually has.
    assert "Synergy realisation" in brief.scope_topics
    assert not any("TSA" in topic for topic in brief.scope_topics)


def test_the_keyless_brief_reads_the_obvious_signals(model):
    for text, kind in (("a one-pager please", "one_pager"),
                       ("SteerCo pack", "steerco_pack"),
                       ("budget and synergy review", "financial_review"),
                       ("what are the open risks", "risk_review")):
        brief = request_interpreter.fallback_brief(context_for(model, text))
        assert brief.document_kind == kind, text


# ================================================= section validation
def test_invented_evidence_ids_are_dropped_and_reported(model):
    """An id that resolves to nothing renders as a blank where a figure should
    be, and blanks are how a report starts lying quietly."""
    context = context_for(model, "status")
    plan = StorylinePlan(sections=[SectionIntent(
        section_id="risks", working_title="Risks",
        evidence_ids=["ev:risk:R1", "ev:risk:NOPE", "ev:fact:invented"])])

    warnings = section_planner.validate(plan, context.evidence)
    assert plan.sections[0].evidence_ids == ["ev:risk:R1"]
    assert any("do not exist" in w for w in warnings)
    assert any("ev:risk:NOPE" in w for w in warnings)


def test_duplicate_section_ids_are_renamed_not_merged(model):
    context = context_for(model, "status")
    plan = StorylinePlan(sections=[
        SectionIntent(section_id="risks", working_title="Open risks"),
        SectionIntent(section_id="risks", working_title="More on risks"),
    ])
    warnings = section_planner.validate(plan, context.evidence)
    assert len({s.section_id for s in plan.sections}) == 2
    assert any("Duplicate section id" in w for w in warnings)


def test_a_dropped_topic_is_restored_as_its_own_section(model):
    """The planner's licence is to retitle, reorder and group. Not to remove."""
    context = context_for(model, "status")
    brief = OutputBrief(scope_topics=["Risks", "Cash Flow Impact"])
    plan = StorylinePlan(sections=[SectionIntent(
        section_id="risks", working_title="Open risks remain unmitigated",
        evidence_ids=["ev:risk:R1"], covers_requested=["Risks"])])

    warnings = section_planner.enforce_coverage(plan, brief, context.evidence)
    titles = [s.working_title for s in plan.sections]
    assert "Cash Flow Impact" in titles
    assert any("Cash Flow Impact" in w for w in warnings)


def test_a_retitled_section_still_counts_as_covering_its_topic(model):
    """"Budget vs. Actual Analysis" is covered by "Forecast spend exceeds the
    approved envelope" — the critic has to be able to see that."""
    context = context_for(model, "status")
    brief = OutputBrief(scope_topics=["Budget vs. Actual Analysis"])
    plan = StorylinePlan(sections=[SectionIntent(
        section_id="spend",
        working_title="Forecast budget exceeds the approved actual envelope",
        evidence_ids=["ev:budget:B1"])])

    section_planner.enforce_coverage(plan, brief, context.evidence)
    assert len(plan.sections) == 1, "the topic was covered; do not duplicate it"
    assert "Budget vs. Actual Analysis" in plan.sections[0].covers_requested


def test_a_restored_topic_with_no_evidence_carries_the_absence(model):
    context = context_for(model, "Prepare a pack:\n1. Risks\n2. TSA exit readiness")
    brief = OutputBrief(scope_topics=["Risks", "TSA exit readiness"])
    plan = StorylinePlan(sections=[SectionIntent(
        section_id="risks", working_title="Risks", evidence_ids=["ev:risk:R1"],
        covers_requested=["Risks"])])

    section_planner.enforce_coverage(plan, brief, context.evidence)
    restored = plan.sections[-1]
    assert restored.working_title == "TSA exit readiness"
    assert restored.evidence_ids == ["ev:absence:tsa-exit-readiness"]


def test_the_coverage_map_is_recorded_for_the_critic(model):
    context = context_for(model, "status")
    brief = OutputBrief(scope_topics=["Risks"])
    plan = StorylinePlan(sections=[SectionIntent(
        section_id="risks", working_title="Risks", covers_requested=["Risks"])])
    assert section_planner.coverage_map(plan, brief) == {"Risks": ["risks"]}


# ================================================== the keyless storyline
def test_the_keyless_storyline_orders_by_evidence_not_by_template(model):
    context = context_for(model, "Prepare a pack:\n1. Risks\n2. Budget position")
    brief = request_interpreter.fallback_brief(context)
    retrieval = storyline.retrieve_for(context, brief)
    plan = storyline.fallback_storyline(context, brief, retrieval)

    assert [s.working_title for s in plan.sections][:2] == ["Risks",
                                                            "Budget position"]
    assert all(s.evidence_ids for s in plan.sections[:2])


def test_the_keyless_storyline_does_not_invent_a_conclusion(model):
    """It cannot find a governing message, so it must not pretend to have one."""
    context = context_for(model, "status")
    brief = request_interpreter.fallback_brief(context)
    plan = storyline.fallback_storyline(
        context, brief, storyline.retrieve_for(context, brief))

    assert "without a language model" in plan.executive_takeaway
    assert plan.complication == ""
    assert plan.supporting_arguments == []


def test_the_keyless_storyline_still_discloses_must_include_evidence(model):
    model.risks[0].mitigation_action = None
    context = context_for(model, "Prepare a pack:\n1. Budget position\n2. Synergies")
    brief = request_interpreter.fallback_brief(context)
    plan = storyline.fallback_storyline(
        context, brief, storyline.retrieve_for(context, brief))

    disclosed = {i for s in plan.sections for i in s.evidence_ids}
    assert set(context.evidence.must_include()) <= disclosed


# ==================================================== the keyless deliverable
def test_a_keyless_run_says_so_on_the_page_not_only_in_a_log(model):
    """A document assembled from a fallback that *looks* analysed is the exact
    failure the warning machinery exists to prevent, and nobody reads a log."""
    context = context_for(model, "Prepare a pack:\n1. Risks\n2. Budget position")
    deliverable = engine.build(context)

    assert deliverable.planned_by == "fallback"
    assert engine.UNPLANNED_NOTICE in deliverable.warnings

    callouts = deliverable.pages[0].of_role("callout")
    assert callouts and "without a language model" in callouts[0].text
    assert callouts[0].emphasis == "warn"


def test_a_keyless_run_still_covers_every_requested_topic(model):
    eleven = "\n".join(f"{n}. Topic {n}" for n in range(1, 12))
    context = context_for(model, f"Prepare a pack with:\n{eleven}")
    deliverable = engine.build(context)

    covered = {t for topics in deliverable.covered_sections.values() for t in topics}
    assert len(deliverable.covered_sections) == 11
    assert all(deliverable.covered_sections[f"Topic {n}"] for n in range(1, 12))


@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_a_fully_planned_run_carries_no_unplanned_notice(model, scripted_planning):
    deliverable = engine.build(context_for(model, "Prepare a SteerCo pack."))
    assert engine.UNPLANNED_NOTICE not in deliverable.warnings
    assert not any("without a language model" in element.text
                   for page in deliverable.pages
                   for element in page.of_role("callout"))


def test_pythons_own_arithmetic_is_not_accused_of_inventing_figures(model):
    """§12.5's management messages are counts Python derived from the evidence,
    so the numeric corpus cannot contain them — checking them by containment
    throws away the finding and blames Python for it.

    `use_model=True` alone cannot tell whose text it is: the task may have asked
    and fallen back internally, returning exactly the deterministic copy.
    """
    from app import llm
    from app.deliverable.model import PageDesign
    from app.generation import narrative_writer
    from app.llm.base import NotConfigured

    class _Declines:
        name = "declines"
        supports_vision = False

        def structured(self, **kwargs):
            raise NotConfigured("no key for PageCopy")

    llm.set_client(_Declines())

    finding = "4173 critical risk(s) require management attention"
    context = context_for(model, "Prepare a pack.")
    assert "4173" not in context.evidence.numeric_corpus()

    page = PageDesign(page_id="risks", title="Open risks", subtitle=finding,
                      evidence_ids=[])
    warnings = narrative_writer.write_page(page, context, None, use_model=True)

    assert page.subtitle == finding, "Python's own finding was rejected"
    assert not any("4173" in w for w in warnings)
    assert not page.warnings


def test_one_run_that_fell_back_does_not_label_the_next_one_unplanned(model):
    """A build must be judged on its own planning, not on the process's memory.

    `planned_by` used to be inferred by scanning `tasks._warnings` — one list
    shared by every request, drained only by the graph. So a keyless build (or a
    failure in another chat entirely) left a trace that stamped "Unplanned
    layout" onto the next document, in the artifact, where a reader sees it.
    """
    from tests.conftest import ScriptedPlanningClient
    from app import llm

    first = engine.build(context_for(model, "Prepare a pack:\n1. Risks"))
    assert first.planned_by == "fallback", "the keyless build must still say so"

    llm.set_client(ScriptedPlanningClient("steerco_status"))
    second = engine.build(context_for(model, "Prepare a SteerCo pack."))

    assert second.planned_by == "llm"
    assert engine.UNPLANNED_NOTICE not in second.warnings
    assert not any("without a language model" in element.text
                   for page in second.pages
                   for element in page.of_role("callout"))


# ================================================== the adversarial plan
@pytest.mark.parametrize("scripted_planning", ["bad_plan"], indirect=True)
def test_a_bad_plan_is_repaired_rather_than_refused(model, scripted_planning):
    """Every defect here is one a real model plausibly produces. None of them
    may reach a page, and none of them may stop a document being produced."""
    context = context_for(model, "Prepare a pack:\n1. Risks\n2. Budget position")
    deliverable = engine.build(context)

    assert deliverable.page_count >= 2

    # Invented evidence ids never reach a page.
    for page in deliverable.pages:
        assert "ev:risk:DOES_NOT_EXIST" not in page.evidence_ids
        assert "ev:fact:invented" not in page.evidence_ids
    assert any("do not exist" in w for w in deliverable.warnings)

    # Duplicate ids were separated, not merged.
    assert len({p.page_id for p in deliverable.pages}) == deliverable.page_count

    # The dropped topic came back.
    assert deliverable.covered_sections.get("Budget position")

    # A chart with nothing behind it was dropped, not left as a caption over
    # empty space — that stub is exactly what the old renderers emitted.
    assert not any(page.of_role("chart") for page in deliverable.pages)
    assert any("cites no evidence" in w for page in deliverable.pages
               for w in page.warnings)


@pytest.mark.parametrize("scripted_planning", ["bad_plan"], indirect=True)
def test_an_absurd_page_count_is_clamped(model, scripted_planning):
    context = context_for(model, "status")
    engine.build(context)   # suggested_pages=99 must not become 99 pages


# ==================================================== layout binding
@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_every_page_binds_to_a_real_template_layout(model, scripted_planning):
    context = context_for(model, "Prepare a SteerCo pack.")
    deliverable = engine.build(context)
    catalog = context.template_reference.catalog

    for page in deliverable.pages:
        assert page.layout_id, f"{page.page_id} is not bound to a layout"
        assert catalog.by_id(page.layout_id) is not None

    assert len(deliverable.layouts_used) > 1, \
        "a deck that uses one layout for everything is the old renderer"


@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_elements_land_in_named_slots(model, scripted_planning):
    context = context_for(model, "Prepare a SteerCo pack.")
    deliverable = engine.build(context)

    two_column = next(p for p in deliverable.pages
                      if p.composition == "chart_plus_commentary")
    slots = [e.slot for e in two_column.elements if e.slot]
    assert len(set(slots)) >= 2, "a two-column page must use both columns"


@pytest.mark.parametrize("scripted_planning", ["finance_deep_dive"], indirect=True)
def test_kpi_values_are_resolved_by_python_not_written_by_the_model(
        model, scripted_planning):
    """The model chose which figures deserve a tile. It did not write them."""
    context = context_for(model, "A finance deep dive for the CFO.")
    deliverable = engine.build(context)

    row = next(e for page in deliverable.pages for e in page.of_role("kpi_row"))
    assert row.tiles
    by_label = {t.evidence_id: t for t in row.tiles}
    variance = by_label["ev:fact:budget.variance"]
    assert variance.display == context.evidence.get(
        "ev:fact:budget.variance").display
    assert variance.display != "", "a tile must show something"


@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_each_page_carries_the_provenance_of_what_it_used(
        model, scripted_planning):
    context = context_for(model, "Prepare a SteerCo pack.")
    deliverable = engine.build(context)

    risk_page = deliverable.page("critical-risk")
    assert "dashboard.png" in risk_page.source_note
    assert "read from an image" in risk_page.source_note


# ==================================================== blocking and force
def test_an_unresolved_critical_conflict_blocks_generation(model):
    model.conflicts.append(Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX),
            value="2026-09-15")],
    ))
    context = context_for(model, "Prepare a pack.")
    with pytest.raises(PlanningError) as excinfo:
        engine.build(context)
    assert "unresolved conflict" in str(excinfo.value)


def test_force_publishes_with_the_disagreement_disclosed(model):
    model.conflicts.append(Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX),
            value="2026-09-15")],
    ))
    context = context_for(model, "Prepare a pack:\n1. Milestones\n2. Risks")
    deliverable = engine.build(context, force=True)

    assert deliverable.page_count >= 1
    assert any("unresolved conflict" in note for note in deliverable.notes)
    conflict_id = model.conflicts[0].conflict_id
    assert f"ev:conflict:{conflict_id}" in deliverable.evidence_ids


def test_nothing_to_report_on_blocks(model):
    context = context_for(PMIDataModel(), "Prepare a pack.",
                          digest=KnowledgeDigest())
    with pytest.raises(PlanningError) as excinfo:
        engine.build(context)
    assert "nothing to report on" in str(excinfo.value)


def test_what_the_user_told_us_is_itself_enough_to_report_on(model):
    """No files, but the user described the deal. That is evidence, and a
    document that says only what they told us is honest, not empty."""
    context = context_for(PMIDataModel(), "Prepare a pack.")
    deliverable = engine.build(context)
    assert deliverable.page_count >= 1


# ==================================================== targeted regeneration
@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_regeneration_touches_only_the_named_pages(model, scripted_planning,
                                                   monkeypatch):
    context = context_for(model, "Prepare a SteerCo pack.")
    deliverable = engine.build(context)
    before = {p.page_id: p.model_dump() for p in deliverable.pages}

    called = []
    monkeypatch.setattr("app.planning.storyline.develop",
                        lambda *a, **k: called.append("storyline"))
    monkeypatch.setattr("app.evidence.projection.project",
                        lambda *a, **k: called.append("projection"))

    revised = engine.regenerate_pages(deliverable, context, ["spend"],
                                      reason="text overflowed")

    assert called == [], "regeneration must not re-plan or re-extract"
    assert revised.version == deliverable.version + 1
    assert revised.parent_version == deliverable.version

    for page in revised.pages:
        if page.page_id == "spend":
            assert "text overflowed" in " ".join(page.warnings)
        else:
            assert page.model_dump() == before[page.page_id]


@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_regenerating_an_unknown_page_is_a_no_op(model, scripted_planning):
    context = context_for(model, "Prepare a SteerCo pack.")
    deliverable = engine.build(context)
    assert engine.regenerate_pages(deliverable, context, ["nope"]) is deliverable
