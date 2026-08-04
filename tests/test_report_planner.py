"""The planner and the markdown preview (`app/report/planner.py`, `render/markdown.py`).

The preview is the promise this layer makes: what the text says is what the deck
will say. So the assertions here are mostly about *fidelity and honesty* — the
audience gets the right sections, a figure that reaches the preview came from the
fact table, and a report that cannot vouch for itself says so rather than looking
clean.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agent.calculations import recompute_derived
from app.agent.data_quality import build_report
from app.agent.standardize import derive_workstreams
from app.extractors.base import make_source
from app.models.pmi import (
    Audience,
    BudgetItem,
    Dependency,
    Milestone,
    PMIDataModel,
    PMIProject,
    Risk,
    SourceFormat,
    Status,
    Synergy,
    Task,
)
from app.report.planner import plan
from app.report.render.markdown import render_markdown

XLSX, PNG = SourceFormat.EXCEL, SourceFormat.IMAGE


@pytest.fixture
def model() -> PMIDataModel:
    """A project carrying the shapes that matter: an unmitigated critical risk
    read off a screenshot, an overdue task, a slipped milestone, an over-budget
    line, and a workstream that reported nothing."""
    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan")
    image = make_source("dashboard.png", PNG, extraction_confidence=0.35)

    built = PMIDataModel(
        project=PMIProject(project_id="p1", project_name="Project Aurora",
                           reporting_date=date.today()),
        source_files=["tracker.xlsx", "dashboard.png"],
        tasks=[
            Task(task_id="T1", title="Payroll cutover", owner="Anna Schmidt",
                 workstream="Finance", due_date=date.today() - timedelta(days=3),
                 status=Status.IN_PROGRESS, progress_percentage=60.0,
                 source_references=[xlsx]),
            Task(task_id="T2", title="Day 1 building access", owner=None,
                 workstream="Operations", is_day_1_critical=True,
                 status=Status.NOT_STARTED, source_references=[xlsx]),
        ],
        milestones=[
            Milestone(milestone_id="M1", name="ERP go-live", is_go_live=True,
                      planned_date=date(2026, 9, 15),
                      forecast_date=date(2026, 9, 30),
                      status=Status.IN_PROGRESS, source_references=[xlsx]),
        ],
        risks=[
            Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                 impact=5, owner="Lisa Chen", status=Status.IN_PROGRESS,
                 source_references=[image]),
        ],
        budget=[
            BudgetItem(budget_item_id="B1", category="Advisors", budget=1000.0,
                       actual=900.0, forecast=1250.0, source_references=[xlsx]),
        ],
        synergies=[
            Synergy(synergy_id="S1", title="Procurement consolidation",
                    target_value=1_000_000.0, realized_value=400_000.0,
                    source_references=[xlsx]),
        ],
    )
    built, issues = recompute_derived(built, built.project.reporting_date)
    built.validation_issues.extend(issues)
    derive_workstreams(built)
    return built


def ids(content) -> list[str]:
    return [s.section_id for s in content.narrative()]


# ======================================================= user-defined structure
def test_a_saved_structure_can_be_edited_without_repeating_it():
    from app.report.structure import SectionSpec, StructureSpec, revise

    existing = StructureSpec(sections=[
        SectionSpec(title="Integration status"),
        SectionSpec(title="All workstreams"),
        SectionSpec(title="Milestones"),
    ]).model_dump(mode="json")

    updated = revise(
        existing,
        "Please add also 4. Budget and eliminate all workstreams part",
    )

    assert [section.title for section in updated.sections] == [
        "Integration status", "Milestones", "Budget",
    ]


def test_a_section_can_be_replaced_in_natural_language():
    """"Instead of X I would like Y" changes the topic, not just its label.

    Keeping the old ``section_id`` would put risk rows under a Budget heading,
    so the replacement deliberately returns to an unmatched section spec and is
    mapped to Budget evidence during the next plan.
    """
    from app.report.structure import SectionSpec, StructureSpec, revise

    existing = StructureSpec(sections=[
        SectionSpec(title="Headcount Integration"),
        SectionSpec(title="Employee Risks", section_id="risks.critical"),
        SectionSpec(title="Next Steps"),
    ]).model_dump(mode="json")

    updated = revise(
        existing,
        "instead of Employee Risks I would like to have Employee Budget",
    )

    assert [section.title for section in updated.sections] == [
        "Headcount Integration", "Employee Budget", "Next Steps",
    ]
    assert updated.sections[1].section_id is None


def test_a_requested_structure_replaces_the_house_deck(model):
    """§17. `DECKS` is a good default and used to be the only possible answer.

    Someone who wrote out the sections they wanted got the house template
    anyway, which reads as the tool not having listened. And because every
    format plans from this one object, the order applies to the deck, the
    workbook, the document and the preview alike.
    """
    from app.report.structure import SectionSpec, StructureSpec

    spec = StructureSpec(sections=[
        SectionSpec(title="Budget"),
        SectionSpec(title="Risks"),
        SectionSpec(title="Milestones"),
    ])
    order = ids(plan(model, Audience.EXECUTIVE, structure=spec))

    assert order[0] == "summary.executive"
    assert order[1:4] == ["finance.budget_detail", "risks.critical", "milestones"]
    # §12.5 is not a section the user chooses between — it is what the document
    # says about its own reliability, and it is always last.
    assert order[-1] == "quality.limitations"
    # The house deck's sections that were not asked for are gone.
    assert "decisions" not in order


def test_a_requested_section_with_no_data_is_stated_not_dropped(model):
    """§21.17. A reader who asked for "TSA exit" and sees no such section
    concludes there is nothing to report. Saying nothing covers it is the
    truth: nobody wrote it down."""
    from app.report.structure import SectionSpec, StructureSpec

    content = plan(model, Audience.PMO, structure=StructureSpec(sections=[
        SectionSpec(title="Risks"),
        SectionSpec(title="TSA exit readiness"),
    ]))

    requested = next(s for s in content.narrative()
                     if s.label == "TSA exit readiness")
    assert requested.blocks == []
    assert "TSA exit readiness" in requested.empty_explanation
    assert requested.origin == "user"


def test_the_limitations_section_cannot_be_structured_away(model):
    """Asking for it explicitly must not produce it twice, and not asking for
    it must not remove it."""
    from app.report.structure import SectionSpec, StructureSpec

    order = ids(plan(model, Audience.PMO, structure=StructureSpec(sections=[
        SectionSpec(title="Data quality"),
        SectionSpec(title="Risks"),
    ])))

    assert order.count("quality.limitations") == 1
    assert order[-1] == "quality.limitations"


# ============================================================ §12.1-12.4 decks
def test_a_pmo_plan_with_dependencies_renders(model):
    """The dependencies section read `from_workstream` / `to_workstream`, which
    `Dependency` has never declared — so any PMO or Workstream report whose files
    contained a dependency raised `AttributeError` out of `plan()` and reached
    the user as a bare 500 on the chat turn. No test covered the section because
    no fixture carried a dependency.
    """
    model.dependencies = [
        Dependency(dependency_id="D1",
                   description="HR data feed needed before payroll cutover",
                   providing_workstream="HR", receiving_workstream="Finance",
                   owner="Anna Schmidt", required_date=date(2026, 6, 1),
                   status=Status.IN_PROGRESS),
    ]

    for audience in (Audience.PMO, Audience.WORKSTREAM):
        content = plan(model, audience)
        section = content.section("dependencies")
        assert section is not None, f"{audience} lost its dependencies section"
        row = section.blocks[0].rows[0]
        assert [c.text for c in row][1:3] == ["HR", "Finance"]
        assert content.warnings == []


def test_one_broken_section_does_not_cost_the_whole_report(model, monkeypatch):
    """Fault isolation, the same discipline `charts.generate` already applies.

    A builder that raises used to propagate out of `plan()` and lose every other
    section with it. The gap is reported rather than swallowed — never return
    empty on failure.
    """
    import app.report.planner as planner

    def boom(_model):
        raise RuntimeError("source column vanished")

    monkeypatch.setattr(planner, "_critical_risks", boom)
    content = plan(model, Audience.EXECUTIVE)

    assert content.section("risks.critical") is None
    assert content.section("decisions") is not None
    assert any("risks.critical" in w and "source column vanished" in w
               for w in content.warnings)


def test_each_audience_gets_a_different_document(model):
    """§12.1-12.4 are not one report with a filter on it — a SteerCo wants
    decisions and an IMO wants overdue work."""
    steerco = ids(plan(model, Audience.EXECUTIVE))
    pmo = ids(plan(model, Audience.PMO))
    finance = ids(plan(model, Audience.FINANCE))

    assert "status.overall" in steerco and "status.overall" not in pmo
    assert "pmo.missing_updates" in pmo and "pmo.missing_updates" not in steerco
    assert "finance.budget_detail" in finance
    assert "finance.budget_detail" not in steerco


def test_every_report_opens_with_a_summary_and_closes_with_its_limitations(model):
    """§12.5. The limitations section is last and unconditional — a deck that
    drops it looks equally confident whether or not it should."""
    for audience in Audience:
        order = ids(plan(model, audience))
        assert order[0] == "summary.executive"
        assert order[-1] == "quality.limitations"


def test_an_absence_a_reader_would_ask_about_is_stated_not_omitted(model):
    """There are no open decisions in this project, yet the section survives.

    "No decisions are pending" is information a Steering Committee needs; a
    *missing* section is ambiguous — the reader cannot tell whether there were
    none or whether we failed to look. Contrast `risks.critical`, which is
    dropped when empty because its absence carries no such question.
    """
    content = plan(model, Audience.EXECUTIVE)
    decisions = content.section("decisions")

    assert "decisions" in ids(content)
    assert decisions.blocks == []
    assert "not recorded in any source" in decisions.empty_explanation


# ================================================== §12.5 management messages
def test_sections_are_titled_with_the_finding_not_the_topic(model):
    """"Risks" tells a reader nothing; "1 critical risk has NO mitigation"
    tells them what to do."""
    content = plan(model, Audience.EXECUTIVE)
    risks = content.section("risks.critical")

    assert "NO mitigation" in risks.headline
    assert risks.headline != risks.label


# ======================================================= honesty about quality
def test_a_figure_read_off_a_screenshot_is_disclosed(model):
    """§5.6, §21.14. The GDPR risk exists only in an image, read at 35%. A
    report that does not say so is the failure this system exists to prevent."""
    content = plan(model, Audience.EXECUTIVE)
    bullets = content.section("quality.limitations").blocks[0].items

    assert any("35%" in b.text and "GDPR" in b.text for b in bullets)
    # The deck's wording, kept verbatim: a reader scanning for "low confidence"
    # must find it in the preview and the slide alike.
    assert any("low confidence" in b.text for b in bullets)


def test_a_report_with_no_quality_assessment_refuses_to_claim_it_is_clean(model):
    """Silence is a claim we have not earned."""
    bare = PMIDataModel(project=model.project)
    section = plan(bare, Audience.EXECUTIVE).section("quality.limitations")

    assert "not assessed" in section.headline
    assert "unverified" in (section.empty_explanation or "")


def test_a_real_quality_report_is_summarised_into_the_limitations(model):
    quality = build_report(model, failed_files=[], warnings=[])
    section = plan(model, Audience.EXECUTIVE,
                   quality=quality).section("quality.limitations")

    assert section.blocks[0].items, "a quality report produced no limitations"


# =================================================================== §7 / §11
def test_unknown_figures_reach_the_preview_as_not_reported_never_as_zero():
    bare = PMIDataModel(project=PMIProject(project_id="p", project_name="Empty"))
    text = render_markdown(plan(bare, Audience.EXECUTIVE))

    assert "Not Reported" in text
    assert "| Overall progress | **0%** |" not in text


def test_the_preview_states_only_figures_the_fact_table_holds(model):
    """The point of the preview is that it and the deck make the same claims —
    so every figure in it must be traceable, not re-derived here."""
    content = plan(model, Audience.EXECUTIVE)
    corpus = content.facts.numeric_corpus()

    assert "1000" in corpus and "60" in corpus
    tiles = content.section("status.overall").blocks[0].tiles
    assert all(t.fact_key in content.facts.values for t in tiles)


# ================================================================== rendering
def test_the_preview_reads_as_a_report(model):
    text = render_markdown(plan(model, Audience.EXECUTIVE,
                                bullets=["One critical risk is unowned."]))

    assert text.startswith("# Project Aurora")
    assert "## Status at a glance" in text
    assert "One critical risk is unowned." in text
    assert "| Overall progress | **60%** |" in text


def test_the_report_carries_no_prototype_disclaimer(model):
    """A finished report must not describe itself as a prototype.

    The stamp used to be applied twice — once as `ReportContent.footer` and once
    unconditionally by the deck renderer on every slide — so it reached readers
    of every format regardless of what was planned.
    """
    content = plan(model, Audience.EXECUTIVE)

    assert content.footer == ""
    assert "Prototype output" not in render_markdown(content)


def test_a_chart_is_described_rather_than_silently_missing(model):
    text = render_markdown(plan(model, Audience.EXECUTIVE))
    assert "📊 Chart:" in text


def test_provenance_is_available_but_off_by_default(model):
    content = plan(model, Audience.EXECUTIVE)

    assert "<sub>" not in render_markdown(content)
    assert "<sub>" in render_markdown(content, show_provenance=True)


def test_a_pipe_in_a_value_cannot_break_the_table(model):
    """A task titled "A | B" would otherwise split its row into extra columns."""
    model.risks[0].title = "GDPR | retention"
    text = render_markdown(plan(model, Audience.EXECUTIVE))

    assert r"GDPR \| retention" in text


def test_an_empty_section_explains_itself(model):
    """"No critical risks" and "nobody reported the risks" are different
    claims and must not render identically."""
    quiet = model.model_copy(update={"risks": [], "conflicts": []})
    text = render_markdown(plan(quiet, Audience.EXECUTIVE))

    assert "risks.critical" not in text          # dropped entirely
    assert "> " in text                          # some section explained itself
