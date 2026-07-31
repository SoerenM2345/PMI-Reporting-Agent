"""Management-message titles (§12.5).

"Use clear management-message titles." A slide titled "Risks" tells a reader
nothing. One titled "Two critical risks are unmitigated; both need an owner
today" tells them what to do. Titles are written from the data, not from the
section name — the Minto Pyramid rule the spec asks for, and the difference
between a deck that informs and one that merely reports.

These moved here verbatim from `pptx_report.py`. They were always pure
`PMIDataModel -> str`, so the deck, the document, the PDF and the text preview
can now all state the same finding instead of the deck being the only artefact
that says anything.

Nothing here calls an LLM. These sentences are computed, which is why they are
allowed to contain figures (§11).
"""
from __future__ import annotations

from app.models.pmi import PMIDataModel, Status


def status_message(model: PMIDataModel) -> str:
    progress = model.overall_progress()
    unresolved = len(model.unresolved_conflicts())
    critical = len([r for r in model.critical_risks() if r.status.is_open])
    overdue = len(model.overdue_tasks())

    if unresolved:
        return (f"Integration status cannot be stated with confidence — "
                f"{unresolved} source conflict(s) remain unresolved")
    if critical:
        return (f"{critical} critical risk(s) require management attention"
                + (f"; {overdue} task(s) are overdue" if overdue else ""))
    if progress is not None and overdue == 0:
        return f"Integration is on track at {progress:.0f}% overall progress"
    if overdue:
        return f"{overdue} task(s) are overdue and need re-planning"
    return "Integration status"


def workstream_message(model: PMIDataModel) -> str:
    silent = [w for w in model.workstreams if w.progress_percentage is None]
    behind = [w for w in model.workstreams
              if w.progress_percentage is not None and w.progress_percentage < 50]
    if silent:
        return (f"{len(silent)} workstream(s) did not report this period — "
                f"progress cannot be confirmed")
    if behind:
        return (f"{len(behind)} workstream(s) are below 50%: "
                f"{', '.join(w.name for w in behind[:3])}")
    return "All workstreams are reporting progress"


def task_message(model: PMIDataModel) -> str:
    overdue = len(model.overdue_tasks())
    blocked = sum(1 for t in model.tasks if t.status is Status.BLOCKED)
    if overdue:
        return f"{overdue} task(s) are overdue" + (f" and {blocked} blocked" if blocked else "")
    return f"{len(model.open_tasks())} of {len(model.tasks)} tasks remain open"


def risk_message(model: PMIDataModel) -> str:
    open_critical = [r for r in model.critical_risks() if r.status.is_open]
    unmitigated = [r for r in open_critical if not r.mitigation_action]
    if unmitigated:
        return (f"{len(unmitigated)} critical risk(s) have NO mitigation action — "
                f"an owner is needed now")
    if open_critical:
        return f"{len(open_critical)} critical risk(s) are open and mitigated"
    return "No critical risks are open"


def budget_message(model: PMIDataModel) -> str:
    over = [b for b in model.budget if b.variance is not None and b.variance < 0]
    if not over:
        return "Integration spend is within budget"
    total = sum(abs(b.variance) for b in over)
    currency = over[0].currency
    return (f"{len(over)} budget line(s) are over budget by {total:,.0f} {currency} "
            f"in total")


def synergy_message(model: PMIDataModel) -> str:
    targeted = [s for s in model.synergies if s.target_value]
    if not targeted:
        return "No synergy targets were reported"
    target = sum(s.target_value or 0 for s in targeted)
    realized = sum(s.realized_value or 0 for s in targeted)
    percent = realized / target * 100 if target else 0
    return (f"{percent:.0f}% of the {target:,.0f} {targeted[0].currency} synergy "
            f"target is realized")


def milestone_message(model: PMIDataModel) -> str:
    """Was inline in `_milestones`; named here so every renderer can reuse it."""
    late = [m for m in model.milestones if (m.delay_days or 0) > 0]
    return (f"{len(late)} milestone(s) have slipped" if late
            else "All milestones are on plan")


def status_at_a_glance(model: PMIDataModel) -> str:
    """Was inline in `_overall_status`."""
    if not model.workstreams:
        return "Status at a glance"
    reporting = len([w for w in model.workstreams
                     if w.progress_percentage is not None])
    return (f"Status at a glance — {reporting} of {len(model.workstreams)} "
            f"workstream(s) reporting")
