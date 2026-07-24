"""P1: the standardized PMI data model and the deterministic calculations (§6, §7, §11)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agent.calculations import recompute_derived
from app.agent.standardize import standardize
from app.extractors.base import make_source, parse_number, parse_percent
from app.models.pmi import (
    BudgetItem,
    PMIDataModel,
    Risk,
    Severity,
    SourceFormat,
    Status,
    Synergy,
    Task,
    normalize_workstream,
    source_priority,
)

XLSX = SourceFormat.EXCEL


def ref(file_name: str = "tracker.xlsx", fmt: SourceFormat = XLSX, **kw):
    return make_source(file_name, fmt, **kw)


# ------------------------------------------------------------------ §7 taxonomy
def test_status_uses_the_spec_word_but_the_old_name_still_resolves():
    """The taxonomy says "Completed"; v1 code said "done". Both must work."""
    assert Status.DONE is Status.COMPLETED
    assert Status.COMPLETED.value == "completed"
    assert Status.COMPLETED.is_open is False
    assert Status.AT_RISK.is_open is True


def test_overdue_is_not_a_status():
    """§8.2 checks for an "overdue task marked Green" — which is only possible if
    overdue is derived from dates, not read from the tracker's own status column."""
    assert not hasattr(Status, "OVERDUE")


def test_workstream_normalization_keeps_unknown_labels_verbatim():
    assert normalize_workstream("IT") == "Information Technology"
    assert normalize_workstream("  hr ") == "Human Resources"
    assert normalize_workstream("SteerCo Prep") == "SteerCo Prep"  # not force-fitted
    assert normalize_workstream(None) is None


def test_images_are_the_least_trusted_source():
    p = source_priority()
    assert p[SourceFormat.IMAGE] > p[SourceFormat.POWERPOINT] > p[SourceFormat.EXCEL]


# -------------------------------------------------------------- parse_number bug
@pytest.mark.parametrize(("text", "expected"), [
    ("1,234", 1234.0),        # was returning 1.234 — the bug
    ("1,234.56", 1234.56),    # English
    ("1.234,56", 1234.56),    # German
    ("1.234.567", 1234567.0), # German grouping
    ("1,5", 1.5),             # German decimal
    ("0.82", 0.82),
    ("€ 3,000", 3000.0),
    ("(1.234)", -1234.0),     # accounting negative
    ("n/a", None),
])
def test_parse_number_handles_both_locales(text, expected):
    assert parse_number(text) == expected


def test_parse_percent_normalizes_fractions():
    assert parse_percent("82%") == 82
    assert parse_percent(0.75) == 75
    assert parse_percent(45) == 45


# ------------------------------------------------------------- §6.5 risk scoring
def test_risk_score_is_probability_times_impact():
    model = PMIDataModel(risks=[
        Risk(risk_id="R1", title="ERP slip", probability=4, impact=5,
             source_references=[ref()])
    ])
    model, issues = recompute_derived(model)

    assert model.risks[0].risk_score == 20
    assert model.risks[0].rating is Severity.CRITICAL
    assert not issues


def test_a_reported_risk_score_that_disagrees_is_corrected_and_flagged():
    """§11: the source is not the authority on its own arithmetic."""
    model = PMIDataModel(risks=[
        Risk(risk_id="R1", title="Payroll", probability=3, impact=3, risk_score=12,
             source_references=[ref()])
    ])
    model, issues = recompute_derived(model)

    assert model.risks[0].risk_score == 9          # computed value wins
    assert [i.check_id for i in issues] == ["MATH-007"]
    assert issues[0].reported_value == "12"
    assert issues[0].corrected_value == "9"


def test_a_missing_factor_is_never_invented():
    """§7: 'The agent must never silently invent missing PMI information.'

    A register that gives only "High impact" gets impact=4 and NO score — we do not
    fabricate a likelihood so that a number can be printed.
    """
    model = PMIDataModel(risks=[
        Risk(risk_id="R1", title="Attrition", impact=4, source_references=[ref()])
    ])
    model, _ = recompute_derived(model)
    risk = model.risks[0]

    assert risk.probability is None
    assert risk.risk_score is None
    assert risk.is_fully_scored is False
    # ...but it must still read as High, not Low, on the deck.
    assert risk.rating is Severity.HIGH


def test_a_critical_rating_does_not_get_downgraded_to_high():
    """Regression guard: multiplying in a median likelihood would band Critical (5)
    as 15 -> HIGH, quietly demoting the worst risk in the register."""
    risk = Risk(risk_id="R1", title="Regulatory block", impact=5,
                source_references=[ref()])
    assert risk.rating is Severity.CRITICAL


# ------------------------------------------------------------ §6.9 budget variance
def test_budget_variance_is_budget_minus_forecast():
    model = PMIDataModel(budget=[
        BudgetItem(budget_item_id="B1", category="Advisors", budget=1000.0,
                   forecast=1250.0, source_references=[ref()])
    ])
    model, issues = recompute_derived(model)

    assert model.budget[0].variance == -250.0        # over budget
    assert model.budget[0].variance_percentage == -25.0
    assert not issues


def test_a_wrong_reported_variance_is_corrected_and_flagged():
    model = PMIDataModel(budget=[
        BudgetItem(budget_item_id="B1", category="Advisors", budget=1000.0,
                   forecast=1250.0, variance=300.0, source_references=[ref()])
    ])
    model, issues = recompute_derived(model)

    assert model.budget[0].variance == -250.0
    assert [i.check_id for i in issues] == ["MATH-003"]
    assert issues[0].severity is Severity.HIGH


# --------------------------------------------------------------- §6.3 overdue
def test_overdue_is_derived_and_an_overdue_green_task_is_flagged():
    """§8.2: 'Overdue task marked Green'."""
    yesterday = date.today() - timedelta(days=1)
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Payroll cutover", due_date=yesterday,
             status=Status.IN_PROGRESS, source_references=[ref()])
    ])
    model, issues = recompute_derived(model)

    assert model.tasks[0].is_overdue is True
    assert "MATH-006" in {i.check_id for i in issues}


def test_a_completed_task_is_never_overdue():
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Kickoff", due_date=date(2020, 1, 1),
             status=Status.COMPLETED, completion_date=date(2020, 1, 1),
             source_references=[ref()])
    ])
    model, _ = recompute_derived(model)
    assert model.tasks[0].is_overdue is False


# ------------------------------------------------------------- §6.10 synergies
def test_realized_above_target_is_reported_not_silently_accepted():
    model = PMIDataModel(synergies=[
        Synergy(synergy_id="S1", title="Procurement", target_value=1_000_000.0,
                realized_value=1_400_000.0, source_references=[ref()])
    ])
    model, issues = recompute_derived(model)

    assert model.synergies[0].remaining_value == -400_000.0
    assert "MATH-008" in {i.check_id for i in issues}


# ----------------------------------------------------------------- §21.17 honesty
def test_an_unparseable_row_is_reported_not_swallowed():
    """The bug this replaces: `except Exception: continue` dropped bad rows silently,
    so a tracker with a broken column lost every row and nobody knew."""
    records = [
        {"type": "task", "title": "Good row", "source": ref()},
        {"type": "task", "title": "", "source": ref()},          # no title -> unbuildable
        {"type": "risk", "title": "Fine", "source": ref()},
    ]
    model = standardize(records, ["tracker.xlsx"])

    assert len(model.tasks) == 1
    assert len(model.risks) == 1
    assert len(model.warnings) == 1
    assert "could not standardize task" in model.warnings[0]
    assert "tracker.xlsx" in model.warnings[0]


def test_overall_progress_is_none_not_zero_when_nothing_is_known():
    """A project with no progress data is not a project at 0% (§7)."""
    model = PMIDataModel(tasks=[
        Task(task_id="T1", title="Unknown progress", source_references=[ref()])
    ])
    assert model.overall_progress() is None


# -------------------------------------------------------------- §6.14 provenance
def test_source_reference_carries_structured_provenance():
    r = ref("plan.xlsx", XLSX, sheet_name="Workplan", cell_range="B7")
    assert r.location == "sheet 'Workplan'!B7"
    assert r.extraction_confidence == 1.0
    assert r.is_low_confidence is False


def test_low_confidence_is_surfaced_for_review():
    """§5.6: 'Low-confidence findings should be shown to the user for review.'"""
    shaky = ref("whiteboard.jpg", SourceFormat.IMAGE, extraction_confidence=0.35)
    model = PMIDataModel(risks=[
        Risk(risk_id="R1", title="Read off a photo", source_references=[shaky])
    ])

    items = model.low_confidence_items()
    assert items == [("risk", "Read off a photo", 0.35)]
