"""Data-quality scoring and reporting (spec §10 node 20, §13 sheet 10, §18.19).

The score is a blunt instrument and is meant to be: its job is to stop a user
presenting a deck built from three conflicting files and a blurry screenshot as
though it were a clean set of accounts.

Deliberately, the score goes *down* for things that are not the data's fault — an
LLM that fell back to templates, an image we could not read, a file that failed to
parse. From the reader's point of view those are identical to missing data: the
report is thinner than it looks, and they should know before they act on it (§21.17).
"""
from __future__ import annotations

from collections import Counter

from app.models.pmi import DataQualityReport, PMIDataModel, Severity

#: Weights sum to 100. Provenance is worth the most because an untraceable figure is
#: the one that gets a consultant into trouble in the room.
_W_PROVENANCE = 30.0
_W_CONFLICTS = 25.0
_W_COMPLETENESS = 25.0
_W_CONFIDENCE = 20.0


def build_report(
    model: PMIDataModel,
    *,
    failed_files: list[str] | None = None,
    warnings: list[str] | None = None,
) -> DataQualityReport:
    total = model.entity_count()
    with_sources = _count_with_sources(model)
    low_confidence = len(model.low_confidence_items())

    conflicts = model.conflicts
    auto = sum(1 for c in conflicts if c.resolution == "source_priority")
    manual = sum(1 for c in conflicts if c.resolution in ("user", "user_value"))
    unresolved = sum(1 for c in conflicts if not c.is_resolved)

    issues = model.validation_issues
    by_family = Counter(i.family for i in issues)

    report = DataQualityReport(
        total_entities=total,
        entities_with_sources=with_sources,
        low_confidence_entities=low_confidence,
        conflicts_total=len(conflicts),
        conflicts_auto_resolved=auto,
        conflicts_user_resolved=manual,
        conflicts_unresolved=unresolved,
        issues_by_family=dict(by_family),
        missing_fields=_missing_fields(model),
        failed_files=list(failed_files or []),
        warnings=list(warnings or []) + list(model.warnings),
    )
    report.score = _score(model, report)
    return report


# ---------------------------------------------------------------------- score
def _score(model: PMIDataModel, report: DataQualityReport) -> float:
    if report.total_entities == 0:
        return 0.0

    # Provenance: can every figure be traced to a file? (§5)
    provenance = report.entities_with_sources / report.total_entities

    # Conflicts: unresolved disagreements are the worst state to publish from —
    # the report asserts a number that two of its own sources dispute.
    if report.conflicts_total:
        conflicts = 1.0 - (report.conflicts_unresolved / report.conflicts_total)
    else:
        conflicts = 1.0

    # Completeness: weighted by severity — a missing mitigation owner on a critical
    # risk hurts more than a missing priority on a routine task.
    penalty = sum(
        {Severity.LOW: 0.5, Severity.MEDIUM: 1.0,
         Severity.HIGH: 2.0, Severity.CRITICAL: 4.0}[i.severity]
        for i in model.validation_issues
    )
    completeness = max(0.0, 1.0 - penalty / max(report.total_entities, 1))

    # Confidence: how much of this came out of a picture?
    confidence = 1.0 - (report.low_confidence_entities / report.total_entities)

    score = (
        _W_PROVENANCE * provenance
        + _W_CONFLICTS * conflicts
        + _W_COMPLETENESS * completeness
        + _W_CONFIDENCE * confidence
    )

    # A file we could not read at all is a hole of unknown size. Cap the score so a
    # run that silently lost a source cannot present itself as clean.
    if report.failed_files:
        score = min(score, 60.0)

    return round(max(0.0, min(score, 100.0)), 1)


def _count_with_sources(model: PMIDataModel) -> int:
    collections = (
        model.workstreams, model.tasks, model.milestones, model.risks, model.issues,
        model.dependencies, model.decisions, model.budget, model.synergies,
        model.kpis, model.meetings, model.status_updates,
    )
    return sum(1 for items in collections for i in items if i.source_references)


def _missing_fields(model: PMIDataModel) -> list[str]:
    """Human-readable summary of the gaps, for the report's front page."""
    out: list[str] = []

    def note(count: int, text: str) -> None:
        if count:
            out.append(f"{count} {text}")

    note(sum(1 for t in model.tasks if not t.owner), "task(s) with no owner")
    note(sum(1 for t in model.tasks if t.due_date is None), "task(s) with no due date")
    note(sum(1 for r in model.risks if not r.is_fully_scored),
         "risk(s) missing a probability or impact, so no score could be computed")
    note(sum(1 for r in model.risks if r.status.is_open and not r.mitigation_action),
         "open risk(s) with no mitigation action")
    note(sum(1 for b in model.budget if b.forecast is None),
         "budget line(s) with no forecast")
    note(sum(1 for s in model.synergies if s.planned_realization_date is None),
         "synergy/synergies with no realization date")
    note(sum(1 for d in model.decisions if d.status.is_open and not d.decision_deadline),
         "open decision(s) with no deadline")

    return out


# ------------------------------------------------------------------- narrative
def summarize(report: DataQualityReport) -> list[str]:
    """Plain-English caveats for the deck's data-quality slide (§12.5)."""
    lines: list[str] = []

    lines.append(
        f"Data-quality score: {report.score:.0f}/100 "
        f"({report.total_entities} items from "
        f"{report.entities_with_sources} traceable source reference(s))."
    )

    if report.failed_files:
        lines.append(
            f"{len(report.failed_files)} file(s) could NOT be read and are missing "
            f"from this report entirely: {', '.join(report.failed_files)}."
        )

    if report.conflicts_unresolved:
        lines.append(
            f"{report.conflicts_unresolved} cross-source conflict(s) are UNRESOLVED — "
            f"the figures shown are one source's view, not an agreed position."
        )
    elif report.conflicts_total:
        lines.append(
            f"{report.conflicts_total} cross-source conflict(s) were detected and "
            f"resolved ({report.conflicts_auto_resolved} by source priority, "
            f"{report.conflicts_user_resolved} by the user)."
        )

    if report.low_confidence_entities:
        lines.append(
            f"{report.low_confidence_entities} item(s) were read from images or scans "
            f"at low confidence and should be verified against the source system."
        )

    for family, count in sorted(report.issues_by_family.items()):
        lines.append(f"{count} {family.replace('_', ' ')} issue(s) detected.")

    if report.missing_fields:
        lines.append("Gaps: " + "; ".join(report.missing_fields) + ".")

    return lines
