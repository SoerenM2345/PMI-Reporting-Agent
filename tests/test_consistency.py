"""P4: entity matching, the §8 check suite, and §9 conflict resolution."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agent.consistency import (
    apply_resolutions,
    critical_topic,
    critical_unresolved,
    escalate,
    registered,
    relative_delta,
    resolve_conflicts,
    run_checks,
)
from app.agent.matching import match_entities
from app.agent.data_quality import build_report
from app.extractors.base import make_source
from app.models.pmi import (
    KPI,
    BudgetItem,
    Conflict,
    ConflictEvidence,
    Decision,
    Milestone,
    PMIDataModel,
    PMIProject,
    Risk,
    Severity,
    SourceFormat,
    Status,
    Task,
)

XLSX, PPTX, IMG = SourceFormat.EXCEL, SourceFormat.POWERPOINT, SourceFormat.IMAGE


def ref(file_name, fmt, **kw):
    return make_source(file_name, fmt, **kw)


def evidence(*pairs) -> list[ConflictEvidence]:
    return [
        ConflictEvidence(source_reference=ref(f, fmt), value=v)
        for f, fmt, v in pairs
    ]


# ------------------------------------------------------------------ the suite
def test_all_four_check_families_are_present():
    """§8.1 cross-source, §8.2 mathematical, §8.3 temporal, §8.4 completeness."""
    families = {c.family for c in registered()}
    assert families == {"cross_source", "mathematical", "temporal", "completeness"}
    assert len(registered()) >= 30


def test_check_ids_are_unique():
    ids = [c.id for c in registered()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    # PMI-007/008/009 legitimately emit under one ID from several fields; the
    # registry entries themselves must still be distinct.
    assert len(set(ids)) == len(ids), f"duplicate check ids: {duplicates}"


def test_a_broken_check_does_not_sink_the_run(monkeypatch):
    """One malformed spreadsheet must not take a whole Steering Committee report down."""
    from app.agent.consistency import registry

    def explode(ctx):
        raise RuntimeError("boom")

    broken = registry.Check(id="X-999", family="temporal", title="Broken",
                            kind="issue", default_severity=Severity.LOW, fn=explode)
    monkeypatch.setattr(registry, "_REGISTRY", registry._REGISTRY + [broken])

    model = PMIDataModel(tasks=[Task(task_id="T1", title="Fine",
                                     source_references=[ref("a.xlsx", XLSX)])])
    results = run_checks(model)

    assert any("X-999" in f for f in results.failed_checks)
    assert any("X-999" in w for w in model.warnings)  # surfaced, not swallowed


# ------------------------------------------------------------------- matching
def test_the_same_milestone_under_different_names_is_matched():
    """Without this, the deck and the tracker hold two unrelated milestones and the
    date disagreement between them is never noticed."""
    model = PMIDataModel(milestones=[
        Milestone(milestone_id="M1", name="ERP go-live",
                  planned_date=date(2026, 9, 15),
                  source_references=[ref("plan.xlsx", XLSX)]),
        Milestone(milestone_id="M2", name="ERP Go Live",
                  planned_date=date(2026, 9, 30),
                  source_references=[ref("steerco.pptx", PPTX)]),
    ])
    groups = match_entities(model)
    cross = [g for g in groups.milestones if g.is_cross_source]

    assert len(cross) == 1
    assert len(cross[0].members) == 2


def test_genuinely_different_items_are_not_merged():
    """A false merge silently destroys one source's value — worse than a missed match."""
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Migrate payroll to new provider",
             source_references=[ref("a.xlsx", XLSX)]),
        Task(task_id="T2", title="Migrate CRM to new provider",
             source_references=[ref("b.pptx", PPTX)]),
    ])
    groups = match_entities(model)
    assert not [g for g in groups.tasks if g.is_cross_source]


# ------------------------------------------------------ §9 severity escalation
def test_the_82_vs_75_case_escalates_on_topic_not_magnitude():
    """The spec's own worked example (§8, §20).

    9% delta. A magnitude-only rule ranks this "medium", auto-resolves it, and the
    user is never asked — but §20 step 9 says the system MUST ask. It is the *topic*
    (overall progress) that makes it critical.
    """
    claims = evidence(("plan.xlsx", XLSX, "82"), ("steerco.pptx", PPTX, "75"))

    assert relative_delta(claims) < 20.0          # would not escalate on size
    assert critical_topic("Overall Progress")     # ...but the topic is on §9's list
    assert escalate("Overall Progress", claims, Severity.MEDIUM) is Severity.CRITICAL


def test_a_routine_topic_with_a_small_delta_stays_auto_resolvable():
    claims = evidence(("a.xlsx", XLSX, "40"), ("b.pptx", PPTX, "42"))
    assert escalate("Update the intranet page", claims, Severity.MEDIUM) is Severity.MEDIUM


def test_a_large_delta_escalates_even_on_a_routine_topic():
    claims = evidence(("a.xlsx", XLSX, "20"), ("b.pptx", PPTX, "80"))  # 300%
    assert escalate("Update the intranet page", claims, Severity.MEDIUM) is Severity.CRITICAL


@pytest.mark.parametrize("key", [
    "Overall Progress", "Day 1 readiness", "ERP go-live date", "Total budget",
    "Synergy realization", "TSA exit", "GDPR compliance milestone",
])
def test_every_topic_on_the_spec_critical_list_is_recognised(key):
    assert critical_topic(key) is not None, f"§9 lists {key!r} as critical"


# ---------------------------------------------------------- §8.1 cross-source
def test_a_milestone_date_conflict_is_detected_with_full_provenance():
    model = PMIDataModel(milestones=[
        Milestone(milestone_id="M1", name="ERP go-live", is_go_live=True,
                  planned_date=date(2026, 9, 15),
                  source_references=[ref("plan.xlsx", XLSX, sheet_name="Milestones",
                                         cell_range="A4:F4")]),
        Milestone(milestone_id="M2", name="ERP go-live", is_go_live=True,
                  planned_date=date(2026, 9, 30),
                  source_references=[ref("steerco.pptx", PPTX, slide_number=7)]),
    ])
    conflict = next(c for c in run_checks(model).conflicts if c.check_id == "PMI-006")

    assert conflict.severity is Severity.CRITICAL       # go-live is on §9's list
    assert conflict.values == {"plan.xlsx": "2026-09-15",
                               "steerco.pptx": "2026-09-30"}
    # The user is told exactly where to look, not merely which file disagrees.
    cites = [e.source_reference.cite() for e in conflict.evidence]
    assert any("sheet 'Milestones'!A4:F4" in c for c in cites)
    assert any("slide 7" in c for c in cites)


def test_a_source_that_says_nothing_is_not_disagreeing():
    """A file with an Unknown status is silent, not in conflict."""
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Payroll cutover", status=Status.IN_PROGRESS,
             source_references=[ref("a.xlsx", XLSX)]),
        Task(task_id="T2", title="Payroll cutover", status=Status.UNKNOWN,
             source_references=[ref("b.pptx", PPTX)]),
    ])
    assert not [c for c in run_checks(model).conflicts if c.check_id == "PMI-003"]


# --------------------------------------------------------------- §8.3 temporal
def test_a_day_1_task_scheduled_after_day_1_is_critical():
    day_1 = date(2026, 6, 15)
    model = PMIDataModel(
        project=PMIProject(project_id="p1", day_1_date=day_1),
        tasks=[Task(task_id="T1", title="Day 1 payroll readiness",
                    is_day_1_critical=True, due_date=day_1 + timedelta(days=10),
                    source_references=[ref("a.xlsx", XLSX)])],
    )
    issue = next(i for i in run_checks(model).issues if i.check_id == "TIME-004")
    assert issue.severity is Severity.CRITICAL


def test_a_task_due_before_it_starts_is_flagged():
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Impossible task",
             start_date=date(2026, 5, 1), due_date=date(2026, 4, 1),
             source_references=[ref("a.xlsx", XLSX)])
    ])
    assert any(i.check_id == "TIME-001" for i in run_checks(model).issues)


# ----------------------------------------------------------- §8.4 completeness
def test_an_unmitigated_critical_risk_is_the_headline_finding():
    model = PMIDataModel(risks=[
        Risk(risk_id="R1", title="Regulatory approval may lapse",
             probability=5, impact=5, risk_score=25, status=Status.IN_PROGRESS,
             source_references=[ref("risks.xlsx", XLSX)])
    ])
    issue = next(i for i in run_checks(model).issues if i.check_id == "COMP-002")
    assert issue.severity is Severity.CRITICAL
    assert "no mitigation action" in issue.message


def test_an_open_decision_with_no_deadline_is_flagged():
    model = PMIDataModel(decisions=[
        Decision(decision_id="C1", title="Approve the TSA extension",
                 status=Status.NOT_STARTED,
                 source_references=[ref("minutes.docx", SourceFormat.WORD)])
    ])
    assert any(i.check_id == "COMP-004" for i in run_checks(model).issues)


# ------------------------------------------------------------ §8.2 mathematical
def test_a_total_that_does_not_match_its_parts_is_flagged():
    model = PMIDataModel(budget=[
        BudgetItem(budget_item_id="B1", category="Advisors", budget=1000.0,
                   source_references=[ref("fin.xlsx", XLSX)]),
        BudgetItem(budget_item_id="B2", category="Technology", budget=2000.0,
                   source_references=[ref("fin.xlsx", XLSX)]),
        BudgetItem(budget_item_id="B3", category="Total", budget=5000.0,
                   source_references=[ref("fin.xlsx", XLSX)]),
    ])
    issue = next(i for i in run_checks(model).issues if i.check_id == "MATH-010")
    assert issue.severity is Severity.HIGH
    assert issue.corrected_value == "3,000"


def test_progress_above_100_percent_is_impossible():
    task = Task(task_id="T1", title="Overachiever",
                source_references=[ref("a.xlsx", XLSX)])
    object.__setattr__(task, "progress_percentage", 130.0)  # bypass the field validator
    model = PMIDataModel(tasks=[task])
    assert any(i.check_id == "MATH-001" for i in run_checks(model).issues)


# ------------------------------------------------------------- §9 resolution
def _progress_conflict():
    model = PMIDataModel(kpis=[
        KPI(kpi_id="K1", name="Overall Progress", current_value=82.0,
            source_references=[ref("plan.xlsx", XLSX)]),
        KPI(kpi_id="K2", name="Overall Progress", current_value=75.0,
            source_references=[ref("steerco.pptx", PPTX)]),
    ])
    model.conflicts = run_checks(model).conflicts
    return model


def test_mode_b_priority_lets_excel_beat_powerpoint():
    model = _progress_conflict()
    resolve_conflicts(model.conflicts, strategy="priority")
    conflict = model.conflicts[0]

    assert conflict.resolved_value == "82"
    assert conflict.resolved_from == "plan.xlsx"
    assert conflict.resolution == "source_priority"


def test_mode_c_hybrid_leaves_the_critical_conflict_for_a_human():
    """§20 step 9: 'The system asks the user to resolve the progress conflict.'"""
    model = _progress_conflict()
    resolve_conflicts(model.conflicts, strategy="hybrid")
    conflict = model.conflicts[0]

    assert conflict.resolved_value is None
    assert conflict.requires_user_input is True
    assert critical_unresolved(model) == [conflict]


def test_mode_c_still_auto_resolves_the_routine_stuff():
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Refresh the intranet page", owner="Anna",
             source_references=[ref("plan.xlsx", XLSX)]),
        Task(task_id="T2", title="Refresh the intranet page", owner="Jonas",
             source_references=[ref("steerco.pptx", PPTX)]),
    ])
    model.conflicts = run_checks(model).conflicts
    resolve_conflicts(model.conflicts, strategy="hybrid")

    owner_conflict = next(c for c in model.conflicts if c.field == "owner")
    assert owner_conflict.resolved_value == "Anna"   # Excel outranks PowerPoint
    assert owner_conflict.resolution == "source_priority"


def test_the_user_can_pick_a_source(monkeypatch):
    model = _progress_conflict()
    conflict_id = model.conflicts[0].conflict_id

    resolve_conflicts(model.conflicts, strategy="hybrid",
                      user_choices={conflict_id: "plan.xlsx"})

    assert model.conflicts[0].resolved_value == "82"
    assert model.conflicts[0].resolution == "user"


def test_the_user_can_supply_a_value_neither_file_contains():
    """§9 Mode A asks 'Which value should be used?', not 'which file do you prefer'.
    When both sources are stale, picking the least-wrong one is not a resolution."""
    model = _progress_conflict()
    conflict_id = model.conflicts[0].conflict_id

    resolve_conflicts(model.conflicts, strategy="hybrid",
                      user_choices={conflict_id: {"value": "80"}})
    apply_resolutions(model)

    assert model.conflicts[0].resolved_value == "80"
    assert model.conflicts[0].resolution == "user_value"
    # ...and it reaches the actual data, not just the conflicts slide.
    assert all(k.current_value == 80.0 for k in model.kpis)


def test_resolutions_are_written_back_into_the_data():
    """A conflict resolved only on the conflicts slide is not resolved: the body of
    the deck would still show whichever value happened to be extracted first."""
    model = _progress_conflict()
    resolve_conflicts(model.conflicts, strategy="priority")
    apply_resolutions(model)

    assert {k.current_value for k in model.kpis} == {82.0}


def test_an_image_never_outranks_a_spreadsheet():
    """§9: images are the least-trusted source (§21.14)."""
    model = PMIDataModel(kpis=[
        KPI(kpi_id="K1", name="Open critical risks", current_value=5.0,
            source_references=[ref("tracker.xlsx", XLSX)]),
        KPI(kpi_id="K2", name="Open critical risks", current_value=2.0,
            source_references=[ref("dashboard.png", IMG, extraction_confidence=0.85)]),
    ])
    model.conflicts = run_checks(model).conflicts
    resolve_conflicts(model.conflicts, strategy="priority")

    assert model.conflicts[0].resolved_from == "tracker.xlsx"


def test_a_resolved_duplicate_is_reported_once_from_the_selected_source():
    model = PMIDataModel(kpis=[
        KPI(kpi_id="K1", name="Overall Progress", current_value=82,
            source_references=[ref("tracker.xlsx", XLSX)]),
        KPI(kpi_id="K2", name="Overall Progress", current_value=75,
            source_references=[ref("steerco.pptx", PPTX)]),
    ])
    conflict = Conflict(
        entity_type="kpi", entity_key="Overall Progress", field="current_value",
        evidence=[
            ConflictEvidence(source_reference=ref("tracker.xlsx", XLSX), value="82"),
            ConflictEvidence(source_reference=ref("steerco.pptx", PPTX), value="75"),
        ], resolved_value="82", resolved_from="tracker.xlsx", resolution="user",
    )
    model.conflicts = [conflict]

    apply_resolutions(model)

    assert len(model.kpis) == 1
    assert model.kpis[0].current_value == 82
    assert model.kpis[0].source_files == ["tracker.xlsx"]


# ---------------------------------------------------------------- data quality
def test_the_score_drops_when_a_file_could_not_be_read():
    """A file we could not open is a hole of unknown size — the run must not present
    itself as clean (§21.17)."""
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Fine", owner="Anna", due_date=date(2030, 1, 1),
             source_references=[ref("a.xlsx", XLSX)])
    ])
    clean = build_report(model)
    broken = build_report(model, failed_files=["scan.pdf"])

    assert clean.score > broken.score
    assert broken.score <= 60.0
    assert broken.failed_files == ["scan.pdf"]


def test_an_unresolved_conflict_makes_the_report_untrustworthy():
    model = _progress_conflict()
    resolve_conflicts(model.conflicts, strategy="hybrid")  # critical -> left open
    report = build_report(model)

    assert report.conflicts_unresolved == 1
    assert report.is_trustworthy is False
