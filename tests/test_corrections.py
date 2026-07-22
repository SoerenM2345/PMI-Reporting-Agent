"""Filling completeness gaps (§8.2) — `app/agent/corrections.py`.

A conflict is two sources disagreeing and §9 already lets the user settle it. A
completeness gap has no competing claim: the value was never written down, and
only the user can supply it. These were counted and never shown, so the one
category of finding a person could act on had no interface.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.agent.corrections import _coerce, apply_correction, fillable
from app.models.pmi import (
    PMIDataModel,
    Severity,
    Synergy,
    Task,
    ValidationIssue,
)


@pytest.fixture
def model() -> PMIDataModel:
    return PMIDataModel(
        tasks=[Task(task_id="T1", title="Payroll cutover")],
        synergies=[Synergy(synergy_id="S1", title="Procurement")],
    )


def _issue(entity_type, entity_id, field, family="completeness") -> ValidationIssue:
    return ValidationIssue(
        check_id="PMI-020", family=family, severity=Severity.MEDIUM,
        entity_type=entity_type, entity_id=entity_id, entity_label="thing",
        field=field, message="missing",
    )


# ============================================================== type safety
@pytest.mark.parametrize("raw", ["not a date", "31-02-2026", "", "2026"])
def test_a_date_field_refuses_anything_that_is_not_a_date(model, raw):
    """The bug this guards: `Optional[date]` stringifies as
    `typing.Optional[datetime.date]`, so a check for "date but not datetime" was
    false for *every* optional date field. The branch never ran and "not a date"
    went straight into a date column — `setattr` on a Pydantic model does not
    validate, so nothing noticed until something tried to format it."""
    issue = _issue("synergy", "S1", "planned_realization_date")
    result = apply_correction(model, issue, raw)

    assert not result.applied, f"{raw!r} was accepted into a date field"
    assert model.synergies[0].planned_realization_date is None


def test_a_real_date_is_stored_as_a_date_not_a_string(model):
    issue = _issue("synergy", "S1", "planned_realization_date")
    assert apply_correction(model, issue, "15-09-2026").applied

    stored = model.synergies[0].planned_realization_date
    assert stored == date(2026, 9, 15)
    assert isinstance(stored, date)


def test_dates_are_read_the_way_the_report_writes_them(model):
    """§7 presents DD-MM-YYYY, so that wins on ambiguity — but a consultant
    pasting ISO out of a tracker should not have to care."""
    assert _coerce(model.synergies[0], "planned_realization_date",
                   "09-03-2026") == date(2026, 3, 9)
    assert _coerce(model.synergies[0], "planned_realization_date",
                   "2026-03-09") == date(2026, 3, 9)


def test_numbers_tolerate_thousands_separators_but_not_prose(model):
    entity = model.synergies[0]
    assert _coerce(entity, "target_value", "1,250") == 1250.0
    with pytest.raises(ValueError):
        _coerce(entity, "target_value", "quite a lot")


def test_a_text_field_takes_text(model):
    issue = _issue("task", "T1", "owner")
    assert apply_correction(model, issue, "Anna Schmidt").applied
    assert model.tasks[0].owner == "Anna Schmidt"


# ================================================== what is offered as fixable
def test_only_gaps_a_person_could_answer_are_offered():
    """A recomputed arithmetic error is already fixed and a temporal
    contradiction is not a blank — offering an input box for either would be a
    lie about what the user can change."""
    issues = [
        _issue("task", "T1", "due_date"),
        _issue("task", "T1", "progress_percentage", family="mathematical"),
        _issue("milestone", "M1", "planned_date", family="temporal"),
        _issue("task", None, "owner"),            # nothing to point at
    ]
    offered = fillable(issues)

    assert [i.field for i in offered] == ["due_date"]


# ==================================================== honest failure messages
def test_editing_something_that_no_longer_exists_says_so(model):
    issue = _issue("task", "GONE", "owner")
    result = apply_correction(model, issue, "Anna")

    assert not result.applied
    assert "no longer in the data" in result.message


def test_a_rejected_value_explains_what_to_type_instead(model):
    issue = _issue("synergy", "S1", "planned_realization_date")
    result = apply_correction(model, issue, "sometime next spring")

    assert not result.applied
    assert "DD-MM-YYYY" in result.message


# ======================================================== provenance (§6.14)
def test_a_value_the_user_supplied_is_recorded_as_theirs(model):
    """It must never later read as something a tracker said."""
    apply_correction(model, _issue("task", "T1", "owner"), "Anna Schmidt")
    assert any("supplied by the user" in note for note in model.notes)
