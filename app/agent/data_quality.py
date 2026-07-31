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
from typing import Optional

from app.models.pmi import (
    DataQualityReport,
    PMIDataModel,
    ScoreComponent,
    Severity,
)

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
    report.score, report.score_components, report.score_cap = _score(model, report)
    return report


# ---------------------------------------------------------------------- score
def _score(
    model: PMIDataModel, report: DataQualityReport
) -> tuple[float, list[ScoreComponent], Optional[float]]:
    """`(score, components, cap)` — one computation, used twice.

    The components exist so `explain()` can say *which* of the four weighted
    terms cost what, without a second implementation of the arithmetic. A score
    the system cannot account for is a number the user has to take on faith,
    which is the opposite of what this report is for.
    """
    if report.total_entities == 0:
        return 0.0, [], None

    total = report.total_entities

    # Provenance: can every figure be traced to a file? (§5)
    provenance = report.entities_with_sources / total

    # Conflicts: unresolved disagreements are the worst state to publish from —
    # the report asserts a number that two of its own sources dispute.
    if report.conflicts_total:
        conflicts = 1.0 - (report.conflicts_unresolved / report.conflicts_total)
    else:
        conflicts = 1.0

    # Completeness: weighted by severity — a missing mitigation owner on a critical
    # risk hurts more than a missing priority on a routine task.
    by_severity = Counter(i.severity for i in model.validation_issues)
    penalty = sum(_SEVERITY_PENALTY[severity] * count
                  for severity, count in by_severity.items())
    completeness = max(0.0, 1.0 - penalty / max(total, 1))

    # Confidence: how much of this came out of a picture?
    confidence = 1.0 - (report.low_confidence_entities / total)

    components = [
        _component("provenance", "Traceable to a source file", _W_PROVENANCE,
                   provenance,
                   f"{report.entities_with_sources} of {total} item(s) cite the "
                   f"file they came from"),
        _component("conflicts", "Cross-source agreement", _W_CONFLICTS, conflicts,
                   (f"{report.conflicts_unresolved} of {report.conflicts_total} "
                    f"conflict(s) are still unresolved"
                    if report.conflicts_total
                    else "no cross-source conflicts were detected")),
        _component("completeness", "Fields the files filled in", _W_COMPLETENESS,
                   completeness, _penalty_basis(by_severity, penalty, total)),
        _component("confidence", "Read at full confidence", _W_CONFIDENCE,
                   confidence,
                   (f"{report.low_confidence_entities} of {total} item(s) were "
                    f"read from an image or scan at low confidence"
                    if report.low_confidence_entities
                    else "nothing was read from an image or scan at low "
                         "confidence")),
    ]

    score = sum(c.weight * c.ratio for c in components)

    # A file we could not read at all is a hole of unknown size. Cap the score so a
    # run that silently lost a source cannot present itself as clean.
    cap = _FAILED_FILE_CAP if report.failed_files else None
    if cap is not None:
        score = min(score, cap)

    return round(max(0.0, min(score, 100.0)), 1), components, cap


_SEVERITY_PENALTY = {
    Severity.LOW: 0.5, Severity.MEDIUM: 1.0,
    Severity.HIGH: 2.0, Severity.CRITICAL: 4.0,
}

#: What a run that lost a source may claim about itself, at most.
_FAILED_FILE_CAP = 60.0


def _component(key: str, label: str, weight: float, ratio: float,
               basis: str) -> ScoreComponent:
    ratio = max(0.0, min(ratio, 1.0))
    return ScoreComponent(key=key, label=label, weight=weight, ratio=ratio,
                          earned=round(weight * ratio, 1), basis=basis)


def _penalty_basis(by_severity: Counter, penalty: float, total: int) -> str:
    if not penalty:
        return "no validation issues were raised"
    parts = ", ".join(
        f"{count} {severity.value}"
        for severity, count in sorted(by_severity.items(),
                                      key=lambda kv: -_SEVERITY_PENALTY[kv[0]])
    )
    return (f"{sum(by_severity.values())} validation issue(s) ({parts}) weigh "
            f"{penalty:g} against {total} item(s)")


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
def explain(report: DataQualityReport) -> str:
    """"Why is the score 98/100?", answered.

    Reads the components `build_report` stored, so the explanation is the score's
    own arithmetic rather than a second guess at it. A report with no components
    predates the breakdown; it says so instead of inventing one.
    """
    from app.report import chat_format as chat

    if not report.score_components:
        return chat.reply(
            f"Data quality: {report.score:.0f}/100",
            body=["This score was computed before the breakdown was recorded, so "
                  "I can't show what each part contributed."],
            action="Ask me to re-read the files and I'll be able to break it down.",
        )

    lost = [c for c in report.score_components if c.ratio < 1.0]
    rows = [
        (f"{c.label}", f"{c.earned:g} / {c.weight:g} — {c.basis}")
        for c in report.score_components
    ]

    lines = chat.key_values(rows)
    if report.score_cap is not None:
        lines.append(
            f"• **Capped at {report.score_cap:g}** because "
            f"{len(report.failed_files)} file(s) could not be read at all: "
            + ", ".join(report.failed_files) + "."
        )

    if lost:
        action = ("The cheapest points back: "
                  + _cheapest_fix(max(lost, key=lambda c: c.weight - c.earned)))
    else:
        action = "Nothing is costing points — every component scored full marks."

    return chat.reply(
        f"Data quality: {report.score:.0f}/100",
        body=lines,
        action=action,
    )


def _cheapest_fix(component: ScoreComponent) -> str:
    return {
        "provenance": "items with no source citation usually come from a format "
                      "we could only read partially — re-upload those files in "
                      "their original form.",
        "conflicts": "resolve the open conflicts; each one decided moves this "
                     "component directly.",
        "completeness": "say “fill the gaps” and I'll ask for the missing values "
                        "one at a time.",
        "confidence": "confirm or correct the figures I read from images — say "
                      "“the progress is 72%” and I'll write it in.",
    }.get(component.key, "resolve the findings above.")


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
