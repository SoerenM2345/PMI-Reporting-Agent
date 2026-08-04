"""Management-message titles for the keyless path (§12.5).

"Use clear management-message titles." A slide titled "Risks" tells a reader
nothing; one titled "2 critical risk(s) have NO mitigation action" tells them
what to do. With a model that message is the storyline's job. Without one,
something still has to say the finding rather than the topic, or the fallback
document degrades from *plain* to *useless* — a table of contents with tables
under it.

`app/report/messages.py` did this for the legacy planner, reading `PMIDataModel`
directly. These read the **evidence index** instead, because that is all a
`GenerationContext` carries and deliberately so: the planning stack never sees
the data model, which is what stops a page being planned around a figure that
never made it through validation.

Nothing here calls a model. These sentences are computed, which is why they are
allowed to contain figures at all (§11).
"""
from __future__ import annotations

import re
from typing import Callable, Optional, Sequence

from app.evidence.model import EvidenceItem, is_open_status

#: What this codebase calls a critical risk, everywhere: `PMIDataModel.
#: critical_risks()` bands HIGH with CRITICAL, and `must_include` forces both.
#: Counting only the CRITICAL band here would let the deck say "no critical
#: risks are open" while an unmitigated HIGH one sat in the appendix.
_SEVERE = ("critical", "high")


def for_section(topic: str, items: Sequence[EvidenceItem]) -> str:
    """The finding this section's evidence supports, or "" if there is none.

    Chosen by topic so that the risk section states the risk finding rather than
    whichever finding happened to be computable — a message that answers a
    different question than its section asked is worse than no message.
    """
    for pattern, writer in _WRITERS:
        if pattern.search(topic or ""):
            return writer(items)
    return _general(items)


# ------------------------------------------------------------------ writers
def _risks(items: Sequence[EvidenceItem]) -> str:
    critical = _open_of(items, ("risk", "issue"), severity=_SEVERE)
    unmitigated = [i for i in critical if not i.payload.get("mitigation_action")]
    if unmitigated:
        return (f"{len(unmitigated)} critical risk(s) have NO mitigation action — "
                f"an owner is needed now")
    if critical:
        return f"{len(critical)} critical risk(s) are open and mitigated"
    return "No critical risks are open"


def _tasks(items: Sequence[EvidenceItem]) -> str:
    overdue = _overdue(items, "task")
    if overdue:
        return f"{len(overdue)} task(s) are overdue and need re-planning"
    open_tasks = _open_of(items, ("task",))
    if open_tasks:
        return f"{len(open_tasks)} task(s) remain open"
    return ""


def _milestones(items: Sequence[EvidenceItem]) -> str:
    late = [i for i in items
            if i.kind == "milestone" and _positive(i.payload.get("delay_days"))]
    if late:
        return f"{len(late)} milestone(s) have slipped"
    overdue = _overdue(items, "milestone")
    if overdue:
        return f"{len(overdue)} milestone(s) are overdue"
    return "All milestones are on plan" if _any_of(items, "milestone") else ""


def _budget(items: Sequence[EvidenceItem]) -> str:
    over = [i for i in items
            if i.kind == "budget" and _negative(i.payload.get("variance"))]
    if over:
        return f"{len(over)} budget line(s) are over budget"
    return "Integration spend is within budget" if _any_of(items, "budget") else ""


def _workstreams(items: Sequence[EvidenceItem]) -> str:
    workstreams = [i for i in items if i.kind == "workstream"]
    silent = [i for i in workstreams
              if i.payload.get("progress_percentage") is None]
    if silent:
        return (f"{len(silent)} workstream(s) did not report this period — "
                f"progress cannot be confirmed")
    return "All workstreams are reporting progress" if workstreams else ""


def _general(items: Sequence[EvidenceItem]) -> str:
    """The document-level finding, for a summary or a status section.

    Ordered by what a reader must act on first: a disagreement about the numbers
    outranks the numbers, because until it is settled nothing built on it can be
    stated with confidence.
    """
    contested = [i for i in items if i.is_contested]
    if contested:
        return (f"Integration status cannot be stated with confidence — "
                f"{len(contested)} source conflict(s) remain unresolved")

    critical = _open_of(items, ("risk", "issue"), severity=_SEVERE)
    overdue = _overdue(items, "task")
    if critical:
        return (f"{len(critical)} critical risk(s) require management attention"
                + (f"; {len(overdue)} task(s) are overdue" if overdue else ""))
    if overdue:
        return f"{len(overdue)} task(s) are overdue and need re-planning"

    absences = [i for i in items if i.is_absence]
    if absences and not [i for i in items if not i.is_absence]:
        return "Not enough data"
    return ""


_WRITERS: tuple[tuple[re.Pattern, Callable[[Sequence[EvidenceItem]], str]], ...] = (
    (re.compile(r"\b(risk|issue)\w*\b", re.I), _risks),
    (re.compile(r"\b(milestone|timeline|date|schedule)\w*\b", re.I), _milestones),
    (re.compile(r"\b(budget|cost|financial|finance|spend|synerg)\w*\b", re.I),
     _budget),
    (re.compile(r"\bworkstream\w*\b", re.I), _workstreams),
    (re.compile(r"\b(task|activity|action|next step)\w*\b", re.I), _tasks),
)


# ------------------------------------------------------------------ helpers
def _any_of(items: Sequence[EvidenceItem], kind: str) -> bool:
    return any(i.kind == kind and not i.is_absence for i in items)


def _open_of(items: Sequence[EvidenceItem], kinds: tuple[str, ...], *,
             severity: Optional[tuple[str, ...]] = None) -> list[EvidenceItem]:
    return [i for i in items
            if i.kind in kinds and not i.is_absence
            and is_open_status(i.status)
            and (severity is None or i.severity in severity)]


def _overdue(items: Sequence[EvidenceItem], kind: str) -> list[EvidenceItem]:
    return [i for i in items
            if i.kind == kind and not i.is_absence
            and (i.status == "overdue" or i.payload.get("is_overdue") is True)]


def _positive(raw) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0


def _negative(raw) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw < 0
