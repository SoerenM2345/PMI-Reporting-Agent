"""Letting the user fill a gap the files left behind (§8.2 completeness).

A **conflict** is two sources disagreeing, and §9 already gives the user a way to
settle it: pick a source, or state the value outright. A **completeness issue**
is different — nothing disagrees, the value simply is not written down anywhere.
"8 tasks have no due date" cannot be resolved by choosing between sources,
because there is nothing to choose between. It can only be answered by the
person who knows the answer.

Until now those gaps were counted in the data-quality report and never shown, so
the one category of finding the user could actually act on was the one with no
interface at all.

What a correction is *not*: an invention. The value comes from the user and is
recorded as coming from the user, with the same provenance discipline as
anything read out of a file — so a due date typed here is traceable to a person,
never presented as something the tracker said.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional, get_args

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.models.pmi import PMIDataModel, ValidationIssue

log = logging.getLogger("pmi.corrections")

#: entity_type -> (collection attribute, id attribute)
_COLLECTIONS: dict[str, tuple[str, str]] = {
    "task": ("tasks", "task_id"),
    "milestone": ("milestones", "milestone_id"),
    "risk": ("risks", "risk_id"),
    "issue": ("issues", "issue_id"),
    "dependency": ("dependencies", "dependency_id"),
    "decision": ("decisions", "decision_id"),
    "budget": ("budget", "budget_item_id"),
    "synergy": ("synergies", "synergy_id"),
    "kpi": ("kpis", "kpi_id"),
    "workstream": ("workstreams", "workstream_id"),
}


class CorrectionResult(BaseModel):
    applied: bool
    message: str
    issue_id: str
    field: Optional[str] = None
    value: Optional[str] = None


def fillable(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """Issues a person could actually answer.

    A completeness gap names a field nobody filled in — answerable. A
    mathematical issue has already been recomputed by `calculations.py`, and a
    temporal one is a contradiction rather than a blank; neither is fixed by
    typing a value, so offering an input box would be a lie about what the user
    can change here.
    """
    return [
        issue for issue in issues
        if issue.family == "completeness"
        and issue.field
        and issue.entity_id
        and issue.entity_type in _COLLECTIONS
    ]


def apply_correction(
    model: PMIDataModel, issue: ValidationIssue, raw_value: str
) -> CorrectionResult:
    """Write `raw_value` into the entity the issue points at.

    Mutates `model` in place and returns what happened. Never raises for bad
    input — an unparseable date is reported back to the user, because the
    alternative is a 500 in the middle of a conversation.
    """
    if not issue.field or not issue.entity_id:
        return CorrectionResult(applied=False, issue_id=issue.issue_id,
                                message="This finding has no field to fill in.")

    entry = _COLLECTIONS.get(issue.entity_type)
    if entry is None:
        return CorrectionResult(
            applied=False, issue_id=issue.issue_id,
            message=f"I do not know how to edit a {issue.entity_type}.",
        )

    collection_attr, id_attr = entry
    entity = next(
        (item for item in getattr(model, collection_attr, [])
         if getattr(item, id_attr, None) == issue.entity_id),
        None,
    )
    if entity is None:
        return CorrectionResult(
            applied=False, issue_id=issue.issue_id,
            message="That item is no longer in the data — the files may have "
                    "been re-read since this was reported.",
        )

    if not hasattr(entity, issue.field):
        return CorrectionResult(
            applied=False, issue_id=issue.issue_id,
            message=f"“{issue.field}” is not a field on a {issue.entity_type}.",
        )

    try:
        value = _coerce(entity, issue.field, raw_value)
    except ValueError as exc:
        return CorrectionResult(applied=False, issue_id=issue.issue_id,
                                message=str(exc))

    setattr(entity, issue.field, value)

    # §6.14: where a value came from is part of the value. A figure supplied by
    # a person must not later read as something a file said.
    note = f"{issue.field} supplied by the user"
    if note not in model.notes:
        model.notes.append(note)

    log.info("correction applied: %s %s.%s = %r",
             issue.entity_type, issue.entity_id, issue.field, value)
    return CorrectionResult(
        applied=True, issue_id=issue.issue_id, field=issue.field,
        value=str(value),
        message=f"Recorded {issue.field.replace('_', ' ')} for "
                f"“{issue.entity_label or issue.entity_id}”.",
    )


def apply_and_persist(analysis, issue: ValidationIssue, raw_value: str) -> CorrectionResult:
    """Apply a correction, re-run the checks, re-score, and save the analysis.

    The write-back half of a correction, factored out so the two callers — the
    REST ``/api/issues/{sid}/fill`` endpoint and the chat correction flow in
    ``agent/conversation.py`` — stay byte-for-byte identical. Filling a gap makes
    the check that reported it stop reporting it, moves the quality score, and
    (because ``fingerprint`` reads entity/issue counts and the score) leaves any
    drafted report stale, so it is re-planned before it renders. Persisting here
    is what keeps the durable model — ``analysis.json`` — the single source of
    truth, whether the value arrived over HTTP or in the chat.
    """
    from app.agent.consistency import run_checks
    from app.agent.data_quality import build_report
    from app.storage import json_store

    model = analysis.data_model
    result = apply_correction(model, issue, raw_value)
    if not result.applied:
        return result

    results = run_checks(model)
    model.conflicts = results.conflicts
    model.validation_issues = results.issues
    analysis.quality_report = build_report(
        model,
        failed_files=[e.split(":", 1)[0] for e in analysis.errors],
        warnings=analysis.warnings,
    )
    json_store.save_analysis(analysis)
    return result


def _coerce(entity, field: str, raw: str) -> Any:
    """Turn the typed string into whatever the model expects.

    Inspects the **actual types** in the annotation rather than its string form.
    An earlier version matched on `str(annotation)` and asked whether it
    contained "date" but not "datetime" — which is false for every optional date
    field, because `Optional[date]` renders as `typing.Optional[datetime.date]`
    and the module path contains "datetime". The date branch never ran, and
    "not a date" was written straight into a date column: `setattr` on a Pydantic
    instance does not validate, so nothing downstream noticed until something
    tried to format it.

    `TypeAdapter` is the backstop. Even if the branches below are wrong about a
    future field, the value is validated against the declared type before it is
    written, so the model cannot end up holding something it says it cannot.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Enter a value first.")

    annotation = type(entity).model_fields[field].annotation
    permitted = set(get_args(annotation)) or {annotation}

    value: Any = raw
    if date in permitted or datetime in permitted:
        value = _parse_date(raw)
    elif float in permitted:
        try:
            value = float(raw.replace(",", "").replace("%", ""))
        except ValueError:
            raise ValueError(f"“{raw}” is not a number.")
    elif int in permitted:
        try:
            value = int(float(raw.replace(",", "")))
        except ValueError:
            raise ValueError(f"“{raw}” is not a whole number.")

    try:
        return TypeAdapter(annotation).validate_python(value)
    except ValidationError:
        raise ValueError(
            f"“{raw}” is not a valid {field.replace('_', ' ')}."
        )


def _parse_date(raw: str) -> date:
    """§7 presents dates as DD-MM-YYYY, so accept that first.

    ISO is accepted too — a consultant pasting from a tracker should not have to
    care — but DD-MM-YYYY wins on ambiguity, because that is the format the
    report itself shows them.
    """
    for pattern in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"“{raw}” is not a date I can read. Try DD-MM-YYYY.")
