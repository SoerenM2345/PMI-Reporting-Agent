"""The evidence layer (`app/evidence/`).

What these pin down is the claim the whole redesign rests on: that moving from
"the report is shaped like the data model" to "the report is shaped like the
argument" costs nothing in traceability. Every figure still knows which cell of
which sheet it came from, every disagreement survives, and nothing a report was
asked for can vanish without being stated.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agent.calculations import recompute_derived
from app.agent.consistency import run_checks
from app.agent.standardize import derive_workstreams
from app.evidence import projection, provenance
from app.evidence.model import EvidenceIndex, EvidenceItem
from app.extractors.base import make_source
from app.models.pmi import (
    BudgetItem,
    Conflict,
    Milestone,
    PMIDataModel,
    PMIProject,
    Risk,
    Severity,
    SourceFormat,
    Status,
    Synergy,
    Task,
)
from app.models.quality import ConflictEvidence

XLSX, PNG = SourceFormat.EXCEL, SourceFormat.IMAGE


@pytest.fixture
def model() -> PMIDataModel:
    """The shapes that matter: an unmitigated critical risk read off a
    screenshot, an overdue task, a slipped milestone, an over-budget line."""
    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan", cell_range="A7")
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
                       actual=900.0, forecast=1250.0, currency="EUR",
                       source_references=[xlsx]),
        ],
        synergies=[
            Synergy(synergy_id="S1", title="Procurement consolidation",
                    target_value=1_000_000.0, realized_value=400_000.0,
                    currency="EUR", source_references=[xlsx]),
        ],
    )
    built, issues = recompute_derived(built, built.project.reporting_date)
    built.validation_issues.extend(issues)
    derive_workstreams(built)
    return built


@pytest.fixture
def index(model) -> EvidenceIndex:
    return projection.project(model)


# ---------------------------------------------------------------- provenance
def test_projection_holds_the_very_same_source_objects(model, index):
    """The one thing that must not be lost in translation.

    Rebuilding a `SourceReference` field by field is the obvious way to write
    the projection, and it silently drops `image_region`, `extraction_method`
    and everything `needs_review` depends on — so a figure read out of a
    screenshot stops looking like one. Identity, not equality.
    """
    risk = index.get("ev:risk:R1")
    assert risk is not None
    assert risk.sources[0] is model.risks[0].source_references[0]

    task = index.get("ev:task:T1")
    assert task.sources[0] is model.tasks[0].source_references[0]
    assert task.sources[0].cell_range == "A7"
    assert task.sources[0].location == "sheet 'Workplan'!A7"


def test_an_image_read_stays_flagged_for_review(index):
    risk = index.get("ev:risk:R1")
    assert risk.confidence == pytest.approx(0.35)
    assert risk.needs_review is True
    assert "dashboard.png" in risk.cite()

    task = index.get("ev:task:T1")
    assert task.needs_review is False


def test_every_item_can_cite_itself(index):
    for item in index:
        assert item.cite(), f"{item.evidence_id} cannot say where it came from"


# ----------------------------------------------------------------- entities
def test_each_collection_becomes_addressable_evidence(index):
    assert index.get("ev:task:T1").kind == "task"
    assert index.get("ev:milestone:M1").kind == "milestone"
    assert index.get("ev:budget:B1").kind == "budget"
    assert index.get("ev:synergy:S1").kind == "synergy"
    assert index.kinds["task"] == 2


def test_statements_are_authored_by_python_and_are_honest(index):
    task = index.get("ev:task:T2")
    assert "Day 1 building access" in task.statement
    assert "no owner recorded" in task.statement          # not "owner: None"
    assert "Day 1 critical" in task.statement

    risk = index.get("ev:risk:R1")
    assert "No mitigation is recorded." in risk.statement
    assert "scored 20" in risk.statement                  # probability x impact


def test_facets_are_promoted_for_ranking_and_filtering(index):
    task = index.get("ev:task:T1")
    assert task.owner == "Anna Schmidt"
    assert task.workstream == "Finance"
    assert task.status == "in_progress"
    assert task.due == date.today() - timedelta(days=3)

    risk = index.get("ev:risk:R1")
    assert risk.severity == "critical"                    # banded from score 20


def test_the_full_entity_stays_reachable_through_payload(index):
    """A renderer needing a field the projection did not promote must not have
    to go back to the data model — that is how two sources of truth start."""
    risk = index.get("ev:risk:R1")
    assert risk.payload["probability"] == 4 and risk.payload["impact"] == 5
    assert risk.payload["mitigation_action"] is None


def test_a_missing_value_is_not_reported_never_zero(index):
    milestone = index.get("ev:milestone:M1")
    assert milestone.value is None
    assert milestone.display == "Not Reported"
    assert "0" not in milestone.display


# -------------------------------------------------------------------- facts
def test_computed_facts_become_evidence_with_a_derivation(index):
    variance = index.get("ev:fact:budget.variance")
    assert variance is not None
    assert variance.origin == "computed_value"
    assert variance.value == pytest.approx(-250.0)
    assert variance.derivation.formula == "budget − (forecast or actual)"
    assert variance.derivation.operation == "budget.variance"


def test_a_derived_figure_cites_what_it_was_derived_from(index):
    """Not one file, arbitrarily. A variance came from arithmetic over budget
    lines, so it cites those lines' sources — and nothing else."""
    variance = index.get("ev:fact:budget.variance")
    assert variance.derivation.input_evidence_ids == ["ev:budget:B1"]
    assert variance.source_files == ["tracker.xlsx"]
    assert "dashboard.png" not in variance.source_files

    progress = index.get("ev:fact:progress.overall")
    assert set(progress.derivation.input_evidence_ids) >= {"ev:task:T1", "ev:task:T2"}


def test_computed_values_are_quotable_facts(index):
    variance = index.get("ev:fact:budget.variance")
    assert variance.is_computed_value and variance.is_quotable_fact
    assert variance.confidence == 1.0


# ---------------------------------------------------------------- conflicts
def test_a_conflict_attaches_to_what_it_contests_and_also_stands_alone(model):
    """Both, not either.

    Attaching alone loses a conflict whose entity was never projected; standing
    alone loses the link that lets a page mark the figure as disputed.
    """
    model.conflicts.append(Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[
            ConflictEvidence(source_reference=make_source("tracker.xlsx", XLSX),
                             value="2026-09-15"),
            ConflictEvidence(source_reference=make_source("weekly.pptx",
                                                         SourceFormat.POWERPOINT,
                                                         slide_number=4),
                             value="2026-10-01"),
        ],
    ))
    index = projection.project(model)
    conflict_id = model.conflicts[0].conflict_id

    standalone = index.get(f"ev:conflict:{conflict_id}")
    assert standalone is not None and standalone.kind == "conflict"
    assert "2026-09-15" in standalone.statement and "2026-10-01" in standalone.statement
    assert "unresolved" in standalone.statement
    assert {r.file_name for r in standalone.sources} == {"tracker.xlsx", "weekly.pptx"}

    milestone = index.get("ev:milestone:M1")
    assert milestone.is_contested
    assert conflict_id in milestone.conflict_ids


def test_a_conflict_matching_nothing_is_still_evidence(model):
    """Otherwise a disagreement about an entity we failed to extract disappears
    — which is the one class of bad news the system exists to surface."""
    model.conflicts.append(Conflict(
        check_id="PMI-009", entity_type="kpi", entity_key="Customer churn",
        field="current_value", severity=Severity.HIGH,
        evidence=[ConflictEvidence(
            source_reference=make_source("board.pptx", SourceFormat.POWERPOINT),
            value="4%")],
    ))
    index = projection.project(model)
    assert index.get(f"ev:conflict:{model.conflicts[0].conflict_id}") is not None
    assert not index.of_kind("kpi")


def test_unresolved_critical_conflicts_are_must_include(model):
    model.conflicts.append(Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX), value="x")],
    ))
    index = projection.project(model)
    required = index.must_include()
    assert f"ev:conflict:{model.conflicts[0].conflict_id}" in required


def test_an_unmitigated_critical_risk_is_must_include(index):
    assert "ev:risk:R1" in index.must_include()


def test_a_resolved_conflict_says_so_and_is_not_forced(model):
    conflict = Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX), value="2026-09-15")],
        resolved_value="2026-09-15", resolved_from="tracker.xlsx",
        resolution="user",
    )
    model.conflicts.append(conflict)
    index = projection.project(model)
    item = index.get(f"ev:conflict:{conflict.conflict_id}")
    assert "Resolved to 2026-09-15" in item.statement
    assert item.evidence_id not in index.must_include()


def test_real_consistency_checks_project_cleanly(model):
    """The registry's own output, not a hand-built conflict."""
    results = run_checks(model)
    model.conflicts.extend(results.conflicts)
    model.validation_issues.extend(results.issues)
    index = projection.project(model)
    for conflict in results.conflicts:
        assert index.get(f"ev:conflict:{conflict.conflict_id}") is not None
    assert len(index.by_origin("quality_issue")) >= 1


# ---------------------------------------------------------------- absences
def test_an_empty_collection_states_its_absence(index):
    """Rather than contributing nothing, which reads as "no problem here"."""
    absent = index.get("ev:absence:decision")
    assert absent is not None
    assert absent.is_absence
    assert "No source in this project records any decision" in absent.statement


def test_a_requested_topic_nothing_covers_becomes_a_stated_gap(model):
    index = projection.project(
        model, requested_topics=["TSA exit readiness", "Budget vs actual"])

    gap = index.get("ev:absence:tsa-exit-readiness")
    assert gap is not None
    assert "TSA exit readiness" in gap.statement
    assert "no uploaded source" in gap.statement

    # ...but a topic the project does cover must not be declared missing.
    assert index.get("ev:absence:budget-vs-actual") is None


def test_absence_licenses_no_figures(model):
    """"We have nothing on this" must never widen what may be stated."""
    index = projection.project(model, requested_topics=["Headcount reduction of 250"])
    corpus = index.numeric_corpus()
    assert "250" not in corpus


# ------------------------------------------------------------------- corpus
def test_the_numeric_corpus_is_what_the_guard_will_allow(index):
    from app.report import guard

    corpus = index.numeric_corpus()
    assert "1000" in corpus                # the budget line
    assert "60" in corpus                  # task progress
    assert "-250" in corpus                # the computed variance
    assert "9999" not in corpus

    assert guard.check_text("Spend is EUR 1,000 against a variance of -250.",
                            corpus) == []
    assert guard.check_text("Spend is EUR 9,999.", corpus) == ["9999"]


# -------------------------------------------------------------- user inputs
def test_user_knowledge_becomes_evidence_and_an_assumption_stays_one(model):
    index = projection.project(model, user_facts=[
        ("user_confirmed", "MedAxis SE is integrating NordCare GmbH."),
        ("user_assumption", "Headcount synergies land in Q4."),
    ])
    fact = index.get("ev:user_fact:001")
    assert fact.origin == "user_confirmed" and fact.is_quotable_fact

    assumption = index.get("ev:assumption:002")
    assert assumption.origin == "user_assumption"
    assert assumption.is_quotable_fact is False, "an assumption is not a fact"


# --------------------------------------------------------------- page notes
def test_a_page_note_names_its_sources_and_its_caveats(index):
    items = index.resolve(["ev:risk:R1", "ev:budget:B1"])
    note = provenance.source_note(items)
    assert "dashboard.png" in note and "tracker.xlsx" in note
    assert "read from an image" in note
    assert provenance.confidence_band(items) == "low"


def test_confidence_is_the_weakest_link_not_the_average(index):
    """Averaging lets four solid numbers launder one that came out of a photo."""
    solid = index.resolve(["ev:task:T1", "ev:budget:B1"])
    assert provenance.confidence_band(solid) == "high"
    assert provenance.confidence_band(solid + index.resolve(["ev:risk:R1"])) == "low"


def test_a_derivation_can_explain_itself(index):
    note = provenance.derivation_note(index.get("ev:fact:budget.variance"))
    assert "budget − (forecast or actual)" in note


# ------------------------------------------------------------------- index
def test_unknown_ids_are_reportable_not_silently_dropped(index):
    assert index.resolve(["ev:task:T1", "ev:task:NOPE"]) == [index.get("ev:task:T1")]
    assert index.unknown(["ev:task:T1", "ev:task:NOPE"]) == ["ev:task:NOPE"]


def test_a_duplicate_id_keeps_the_first(index):
    before = index.get("ev:task:T1")
    index.add(EvidenceItem(evidence_id="ev:task:T1", kind="task",
                           origin="normalized_value", label="impostor"))
    assert index.get("ev:task:T1") is before


def test_the_one_line_form_carries_the_flags_a_planner_needs(index):
    line = index.get("ev:risk:R1").one_line()
    assert "ev:risk:R1" in line and "GDPR retention breach" in line
    assert "conf=0.35" in line
    assert "dashboard.png" in line
    assert "severity=critical" in line
