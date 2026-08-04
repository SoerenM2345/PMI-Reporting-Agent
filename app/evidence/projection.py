"""Project the validated PMI model into addressable, quotable evidence.

One declarative entry per collection, so adding an entity type is a table row
rather than a new branch — the same discipline `extractors/__init__.py` and the
consistency registry already use.

The rule that matters: **`sources` is assigned, never rebuilt**. Copying a
`SourceReference` field by field is the obvious way to write this and it quietly
drops `image_region`, `extraction_method` and the `needs_review` logic that
depends on them, so a figure read out of a screenshot stops looking like one.
The evidence layer holds the very same objects the entities hold.

What gets projected, beyond the entities:

* every fact `app/report/facts.py` computes, as `computed_value` with a
  `Derivation` naming what it was derived from — so a variance cites the budget
  lines behind it rather than falsely citing one file;
* every `Conflict`, both attached to the evidence it contests *and* standing
  alone, so an unmatched conflict is never lost;
* every `ValidationIssue`;
* the user's own confirmed facts, assumptions and decisions;
* and, for each empty collection and each requested topic nothing covers, an
  `absence` item — because a report that silently omits a requested section is
  worse than one that says it has nothing to say.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional, Sequence

from app.evidence.model import Derivation, EvidenceIndex, EvidenceItem
from app.models.pmi import PMIDataModel
from app.models.quality import Conflict, DataQualityReport, ValidationIssue
from app.report import format as fmt

log = logging.getLogger("pmi.evidence.projection")


@dataclass(frozen=True)
class CollectionSpec:
    """How one PMI collection becomes evidence."""

    kind: str
    attribute: str
    id_attr: str
    label_attr: str
    statement: Callable[[Any], str]
    severity_attr: Optional[str] = None
    status_attr: Optional[str] = "status"
    workstream_attr: Optional[str] = "workstream"
    owner_attr: Optional[str] = "owner"
    due_attr: Optional[str] = None
    value_attr: Optional[str] = None
    unit: Optional[str] = None
    search_fields: tuple[str, ...] = ()


def _s(value: Any) -> str:
    """An enum, date or scalar as display text; empty for missing."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return fmt.date_str(value)
    return str(getattr(value, "value", value))


def _pct(value: Optional[float]) -> str:
    return f"{value:.0f}%" if value is not None else fmt.NOT_REPORTED


# --------------------------------------------------------------- statements
def _workstream_statement(w) -> str:
    return (f"Workstream {w.name} is {_s(w.status) or 'not reported'} at "
            f"{_pct(w.progress_percentage)} progress"
            + (f", led by {w.lead}." if w.lead else "."))


def _task_statement(t) -> str:
    parts = [f"Task '{t.title}' is {_s(t.status) or 'not reported'}"]
    if t.progress_percentage is not None:
        parts.append(f"at {_pct(t.progress_percentage)}")
    if t.due_date:
        parts.append(f"due {fmt.date_str(t.due_date)}")
    parts.append(f"owned by {t.owner}" if t.owner else "with no owner recorded")
    if t.is_overdue:
        parts.append("and is overdue")
    if t.is_day_1_critical:
        parts.append("(Day 1 critical)")
    return " ".join(parts) + "."


def _milestone_statement(m) -> str:
    planned = fmt.date_str(m.planned_date) if m.planned_date else "no planned date"
    actual = m.actual_date or m.forecast_date
    tail = f", now {fmt.date_str(actual)}" if actual else ""
    delay = (f" — {m.delay_days} days late" if m.delay_days else "")
    return f"Milestone '{m.name}' was planned for {planned}{tail}{delay}."


def _risk_statement(r) -> str:
    # A risk has no severity field of its own — the programme scores it as
    # probability x impact, so quote the score rather than invent a band.
    score = f", scored {r.risk_score:g}" if r.risk_score is not None else ""
    owner = f" Owned by {r.owner}." if r.owner else " No owner is recorded."
    mitigation = (f" Mitigation: {r.mitigation_action}." if r.mitigation_action
                  else " No mitigation is recorded.")
    return (f"Risk '{r.title}' is {_s(r.status) or 'not reported'}{score}."
            f"{owner}{mitigation}")


def _issue_statement(i) -> str:
    owner = f" Owned by {i.owner}." if i.owner else " No owner is recorded."
    action = (f" Resolution: {i.resolution_action}." if i.resolution_action else "")
    return (f"Issue '{i.title}' is {_s(i.severity) or 'unrated'} severity and "
            f"{_s(i.status) or 'not reported'}.{owner}{action}")


def _dependency_statement(d) -> str:
    return (f"{d.providing_workstream or 'An unnamed workstream'} must deliver "
            f"'{d.description}' to {d.receiving_workstream or 'an unnamed workstream'}"
            + (f" by {fmt.date_str(d.required_date)}" if d.required_date else "")
            + f"; status {_s(d.status) or 'not reported'}.")


def _decision_statement(d) -> str:
    body = _s(d.decision_body)
    if not body or body.casefold() == "unknown":
        body = "an unnamed decision body"
    when = f" by {fmt.date_str(d.decision_deadline)}" if d.decision_deadline else ""
    rec = f" Recommended: {d.recommended_option}." if d.recommended_option else ""
    return f"'{d.title}' requires a decision from {body}{when}.{rec}"


def _budget_statement(b) -> str:
    unit = b.currency or ""
    def money(v):
        return f"{unit} {fmt.num(v)}".strip() if v is not None else fmt.NOT_REPORTED
    return (f"Budget line '{b.category}': budget {money(b.budget)}, "
            f"actual {money(b.actual)}, forecast {money(b.forecast)}, "
            f"variance {money(b.variance)}.")


def _synergy_statement(s) -> str:
    unit = s.currency or ""
    def money(v):
        return f"{unit} {fmt.num(v)}".strip() if v is not None else fmt.NOT_REPORTED
    return (f"Synergy '{s.title}' targets {money(s.target_value)} and has realized "
            f"{money(s.realized_value)}; status {_s(s.status) or 'not reported'}.")


def _kpi_statement(k) -> str:
    unit = f" {k.unit}" if k.unit else ""
    current = f"{fmt.num(k.current_value)}{unit}" if k.current_value is not None \
        else fmt.NOT_REPORTED
    target = f"{fmt.num(k.target_value)}{unit}" if k.target_value is not None \
        else fmt.NOT_REPORTED
    return f"KPI '{k.name}' is at {current} against a target of {target}."


def _meeting_statement(m) -> str:
    when = fmt.date_str(m.meeting_date) if m.meeting_date else "an unrecorded date"
    return (f"{_s(m.meeting_type) or 'A governance meeting'} on {when} recorded "
            f"{len(m.decisions)} decision(s) and {len(m.actions)} action(s).")


def _status_update_statement(u) -> str:
    return (f"Status update for {u.workstream or 'the programme'} "
            f"({u.reporting_period or 'period not stated'}): "
            f"{_s(u.overall_status) or 'no status'} at "
            f"{_pct(u.progress_percentage)}.")


#: The registry. One row per collection; no branch anywhere else knows a kind.
COLLECTIONS: tuple[CollectionSpec, ...] = (
    CollectionSpec("workstream", "workstreams", "workstream_id", "name",
                   _workstream_statement, owner_attr="lead",
                   workstream_attr="name", value_attr="progress_percentage",
                   unit="%", search_fields=("summary", "lead", "sponsor")),
    CollectionSpec("task", "tasks", "task_id", "title", _task_statement,
                   due_attr="due_date", value_attr="progress_percentage", unit="%",
                   search_fields=("description", "owner", "workstream", "priority")),
    CollectionSpec("milestone", "milestones", "milestone_id", "name",
                   _milestone_statement, due_attr="planned_date",
                   search_fields=("description", "owner", "workstream")),
    CollectionSpec("risk", "risks", "risk_id", "title", _risk_statement,
                   severity_attr="_severity_band", due_attr="mitigation_due_date",
                   value_attr="risk_score",
                   search_fields=("description", "category", "owner",
                                  "workstream", "mitigation_action")),
    CollectionSpec("issue", "issues", "issue_id", "title", _issue_statement,
                   severity_attr="severity", due_attr="due_date",
                   search_fields=("description", "owner", "workstream",
                                  "resolution_action")),
    CollectionSpec("dependency", "dependencies", "dependency_id", "description",
                   _dependency_statement, due_attr="required_date",
                   workstream_attr="providing_workstream",
                   search_fields=("receiving_workstream", "impact_if_delayed", "owner")),
    CollectionSpec("decision", "decisions", "decision_id", "title",
                   _decision_statement, owner_attr="decision_owner",
                   due_attr="decision_deadline", workstream_attr=None,
                   search_fields=("description", "decision_body",
                                  "recommended_option", "impact")),
    CollectionSpec("budget", "budget", "budget_item_id", "category",
                   _budget_statement, status_attr=None, owner_attr=None,
                   value_attr="variance",
                   search_fields=("standard_category", "workstream",
                                  "currency", "reporting_period")),
    CollectionSpec("synergy", "synergies", "synergy_id", "title",
                   _synergy_statement, due_attr="planned_realization_date",
                   value_attr="realized_value",
                   search_fields=("description", "synergy_type", "owner",
                                  "workstream", "currency")),
    CollectionSpec("kpi", "kpis", "kpi_id", "name", _kpi_statement,
                   owner_attr=None, value_attr="current_value",
                   search_fields=("description", "workstream", "unit", "trend")),
    CollectionSpec("meeting", "meetings", "meeting_id", "meeting_type",
                   _meeting_statement, status_attr=None, owner_attr=None,
                   workstream_attr=None, due_attr="meeting_date",
                   search_fields=("participants", "agenda", "decisions", "actions")),
    CollectionSpec("status_update", "status_updates", "status_update_id",
                   "workstream", _status_update_statement,
                   status_attr="overall_status", owner_attr=None,
                   search_fields=("reporting_period", "achievements", "comments")),
)

#: Kinds whose absence is worth stating even when nobody asked about them. A
#: programme with no recorded decisions is a finding; one with no KPIs usually
#: is not.
_ABSENCE_WORTH_STATING = ("risk", "milestone", "decision", "budget",
                          "synergy", "dependency")


def project(model: PMIDataModel, *,
            quality: Optional[DataQualityReport] = None,
            user_facts: Sequence[tuple[str, str]] = (),
            user_values: Sequence[Any] = (),
            requested_topics: Sequence[str] = ()) -> EvidenceIndex:
    """Everything a deliverable may draw on, addressable by id.

    `user_facts` is a sequence of `(origin, statement)` where origin is
    `user_confirmed`, `user_assumption` or `project_context` — the context
    builder supplies it, so this module needs no knowledge of either store.

    `user_values` is the same knowledge still attached to its entity and field
    (`context.schemas.UserFact`). It is separate because a sentence cannot be
    compared with anything: without the entity link there was no way to notice
    that a user fact and an entity item stated different values for the same
    field, and both sat in the index as equally factual.
    """
    index = EvidenceIndex(projected_from_files=list(model.source_files))

    for spec in COLLECTIONS:
        for entity in getattr(model, spec.attribute, []) or []:
            index.add(_entity_item(spec, entity))

    _project_facts(index, model, quality)
    _project_conflicts(index, model.conflicts)
    _project_issues(index, model.validation_issues)
    _project_user_facts(index, user_facts)
    _project_user_values(index, user_values)
    _project_absences(index, model, requested_topics)

    log.info("projected %d evidence items from %d files: %s", len(index),
             len(index.projected_from_files), index.kinds)
    return index


# ------------------------------------------------------------------ entities
def _entity_item(spec: CollectionSpec, entity: Any) -> EvidenceItem:
    entity_id = str(getattr(entity, spec.id_attr, "") or "")
    label = str(getattr(entity, spec.label_attr, "") or entity_id or spec.kind)
    payload = entity.model_dump(mode="json")

    value = getattr(entity, spec.value_attr, None) if spec.value_attr else None
    unit = spec.unit or getattr(entity, "currency", None) or getattr(entity, "unit", None)

    item = EvidenceItem(
        evidence_id=f"ev:{spec.kind}:{entity_id}",
        kind=spec.kind,
        # Enums, dates and currencies have all been normalized by
        # `standardize.py` before this point, so nothing here is verbatim.
        origin="normalized_value",
        label=label,
        statement=spec.statement(entity),
        value=value,
        display=_display(value, unit),
        unit=unit if unit != getattr(entity, "currency", None) else None,
        currency=getattr(entity, "currency", None),
        period=getattr(entity, "reporting_period", None),
        entity_type=spec.kind,
        entity_id=entity_id,
        workstream=_attr(entity, spec.workstream_attr),
        owner=_attr(entity, spec.owner_attr),
        severity=_severity(entity, spec),
        status=_attr(entity, spec.status_attr),
        due=getattr(entity, spec.due_attr, None) if spec.due_attr else None,
        # The same objects, not a reconstruction. See the module docstring.
        sources=entity.source_references,
        payload=payload,
    )
    item.search_text = _search_text(item, entity, spec)
    return item


def _attr(entity: Any, name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _s(getattr(entity, name, None)) or None


def _severity(entity: Any, spec: CollectionSpec) -> Optional[str]:
    """A risk has no severity field — it has probability x impact.

    `risk_score` is the programme's own scale, so band it rather than inventing
    a severity the source never stated.
    """
    if spec.severity_attr == "_severity_band":
        score = getattr(entity, "risk_score", None)
        if score is None:
            return None
        return ("critical" if score >= 16 else "high" if score >= 12
                else "medium" if score >= 6 else "low")
    return _attr(entity, spec.severity_attr)


def _display(value: Any, unit: Optional[str]) -> str:
    if value is None:
        return fmt.NOT_REPORTED
    if isinstance(value, (int, float)):
        text = fmt.num(value)
        if unit == "%":
            return f"{text}%"
        return f"{unit} {text}".strip() if unit else text
    return str(value)


def _search_text(item: EvidenceItem, entity: Any, spec: CollectionSpec) -> str:
    parts = [item.label, item.statement, spec.kind]
    for field in spec.search_fields:
        value = getattr(entity, field, None)
        if isinstance(value, (list, tuple)):
            parts.extend(_s(v) for v in value)
        else:
            parts.append(_s(value))
    parts.extend(ref.file_name for ref in item.sources)
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------- facts
def _project_facts(index: EvidenceIndex, model: PMIDataModel,
                   quality: Optional[DataQualityReport]) -> None:
    """Every derived figure, citing what it was derived *from*.

    A budget variance that cited one file would be lying: it came from arithmetic
    over several lines. So the sources are the union of the contributing
    entities' references and the derivation names the inputs by evidence id.
    """
    from app.report.facts import build_facts

    table = build_facts(model, quality)
    for key, fact in table.values.items():
        contributors = _contributors(index, key)
        sources: list = []
        seen: set[int] = set()
        for contributor in contributors:
            for ref in contributor.sources:
                if id(ref) not in seen:
                    seen.add(id(ref))
                    sources.append(ref)

        item = EvidenceItem(
            evidence_id=f"ev:fact:{key}",
            kind="fact",
            origin="computed_value",
            label=fact.label,
            statement=f"{fact.label}: {fact.display}.",
            value=fact.value,
            display=fact.display,
            unit=_fact_unit(key),
            sources=sources,
            derivation=Derivation(
                operation=key,
                input_evidence_ids=[c.evidence_id for c in contributors][:40],
                formula=_FACT_FORMULAS.get(key, ""),
            ),
        )
        item.search_text = f"{fact.label} {fact.display} {key.replace('.', ' ')}"
        index.add(item)


#: Which evidence kinds feed each computed fact. Explicit rather than inferred:
#: a wrong guess here would make a figure cite a file it did not come from.
_FACT_CONTRIBUTORS: dict[str, tuple[str, ...]] = {
    "progress.overall": ("task", "workstream"),
    "status.overall": ("risk", "task", "workstream"),
    "risk.open_critical": ("risk",),
    "tasks.overdue": ("task",),
    "day1.readiness": ("task", "milestone"),
    "day1.total": ("task", "milestone"),
    "budget.total": ("budget",),
    "budget.actual": ("budget",),
    "budget.forecast": ("budget",),
    "budget.variance": ("budget",),
    "synergy.target": ("synergy",),
    "synergy.realized": ("synergy",),
    "synergy.realization_pct": ("synergy",),
}

_FACT_FORMULAS: dict[str, str] = {
    "budget.variance": "budget − (forecast or actual)",
    "synergy.realization_pct": "realized ÷ target × 100",
    "progress.overall": "mean of reported task progress",
    "day1.readiness": "completed Day 1 items ÷ all Day 1 items",
}

_FACT_UNITS: dict[str, str] = {
    "progress.overall": "%", "synergy.realization_pct": "%",
    "quality.score": "%", "day1.readiness": "count",
}


def _fact_unit(key: str) -> Optional[str]:
    return _FACT_UNITS.get(key)


def _contributors(index: EvidenceIndex, fact_key: str) -> list[EvidenceItem]:
    kinds = _FACT_CONTRIBUTORS.get(fact_key)
    return index.of_kind(*kinds) if kinds else []


# ----------------------------------------------------------------- conflicts
def _project_conflicts(index: EvidenceIndex,
                       conflicts: Sequence[Conflict]) -> None:
    """Attach each conflict to what it contests, and keep it as a finding.

    Both, not either. Attaching alone loses a conflict whose entity was never
    projected; standing alone loses the link that lets a page say "this figure
    is disputed" beside the figure.
    """
    for conflict in conflicts:
        conflict_sources = [e.source_reference for e in conflict.evidence]
        if conflict.is_resolved:
            selected = [e.source_reference for e in conflict.evidence
                        if e.file_name == conflict.resolved_from]
            conflict_sources = selected[:1]
        item = EvidenceItem(
            evidence_id=f"ev:conflict:{conflict.conflict_id}",
            kind="conflict",
            origin="conflict",
            label=f"{conflict.entity_key} — {conflict.field}",
            statement=_conflict_statement(conflict),
            display=conflict.resolved_value or "unresolved",
            entity_type=conflict.entity_type,
            severity=_s(conflict.severity),
            status="resolved" if conflict.is_resolved else "open",
            sources=conflict_sources,
            payload={
                **conflict.model_dump(mode="json"),
                "requires_user_input": conflict.requires_user_input,
                "critical": conflict.critical,
            },
        )
        item.search_text = (f"{conflict.entity_key} {conflict.field} conflict "
                            f"disagreement {item.statement}")
        index.add(item)

        for target in _matching(index, conflict):
            if conflict.conflict_id not in target.conflict_ids:
                target.conflict_ids.append(conflict.conflict_id)


def _conflict_statement(conflict: Conflict) -> str:
    if conflict.is_resolved:
        return (f"Resolved to {conflict.resolved_value}: "
                f"{conflict.entity_key} ({conflict.field})"
                + (f" from {conflict.resolved_from}." if conflict.resolved_from else "."))
    claims = "; ".join(f"{name} says {value}"
                       for name, value in conflict.values.items())
    return (f"Sources disagree about {conflict.entity_key} ({conflict.field}): "
            f"{claims}. This is unresolved.")


def _matching(index: EvidenceIndex, conflict: Conflict) -> list[EvidenceItem]:
    """Evidence a conflict contests: same kind, matching label or id."""
    key = _normalize(conflict.entity_key)
    if not key:
        return []
    hits = []
    for item in index.of_kind(conflict.entity_type):
        if _normalize(item.label) == key or _normalize(item.entity_id or "") == key:
            hits.append(item)
    return hits


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()


# -------------------------------------------------------------------- issues
def _project_issues(index: EvidenceIndex,
                    issues: Sequence[ValidationIssue]) -> None:
    for issue in issues:
        item = EvidenceItem(
            evidence_id=f"ev:issue:{issue.issue_id or issue.check_id}",
            kind="quality_issue",
            origin="quality_issue",
            label=issue.entity_label or issue.entity_type,
            statement=issue.message,
            display=issue.corrected_value or "",
            entity_type=issue.entity_type,
            entity_id=issue.entity_id,
            severity=_s(issue.severity),
            sources=list(getattr(issue, "source_references", []) or []),
            payload=issue.model_dump(mode="json"),
        )
        item.search_text = f"{issue.check_id} {issue.family} {issue.message}"
        index.add(item)

        for target in index.of_kind(issue.entity_type):
            if issue.entity_id and target.entity_id == issue.entity_id:
                target.issue_ids.append(item.evidence_id)


# --------------------------------------------------------------- user inputs
def _project_user_facts(index: EvidenceIndex,
                        user_facts: Sequence[tuple[str, str]]) -> None:
    """The user's own knowledge. An assumption is never promoted to a fact."""
    for order, (origin, statement) in enumerate(user_facts, start=1):
        kind = {"user_confirmed": "user_fact", "user_assumption": "assumption",
                "project_context": "context"}.get(origin, "user_fact")
        item = EvidenceItem(
            evidence_id=f"ev:{kind}:{order:03d}",
            kind=kind,
            origin="user_confirmed" if origin == "project_context" else origin,  # type: ignore[arg-type]
            label=statement[:80],
            statement=statement,
        )
        item.search_text = statement
        index.add(item)


def _project_user_values(index: EvidenceIndex, values: Sequence[Any]) -> None:
    """The user's corrections, linked to the entity they correct.

    Two properties the sentence-only projection could not have:

    * **Comparable.** Carrying `entity_type`/`field`/`value` means the item can
      be checked against the entity item for the same thing. Where they still
      disagree — a correction that failed to replay, say — the disagreement is
      recorded rather than left for BM25 to arbitrate between two "facts".
    * **Undroppable.** A value the user personally supplied is added to the
      must-include set, so retrieval cannot rank their own correction out of the
      document they asked for.
    """
    for order, fact in enumerate(values, start=1):
        label = getattr(fact, "label", "") or ""
        field = getattr(fact, "field", "") or ""
        if not field:
            continue
        entity_type = getattr(fact, "entity_type", "") or ""
        item = EvidenceItem(
            evidence_id=f"ev:user_value:{_slug(entity_type)}:{_slug(label)}:{_slug(field)}"
                        if label else f"ev:user_value:{order:03d}",
            kind="user_value",
            origin="user_confirmed",
            label=f"{label or entity_type}: {field.replace('_', ' ')}",
            statement=fact.as_statement(),
            value=getattr(fact, "value", None),
            display=str(getattr(fact, "value", "") or ""),
            entity_type=entity_type or None,
            payload={"field": field, "label": label,
                     "old_value": getattr(fact, "old_value", None)},
        )
        item.search_text = " ".join(filter(None, [label, field, item.display,
                                                  item.statement]))
        index.add(item)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")[:40] or "x"


# ------------------------------------------------------------------ absences
def _project_absences(index: EvidenceIndex, model: PMIDataModel,
                      requested_topics: Sequence[str]) -> None:
    """State what is missing, so a page can cite the gap instead of vanishing."""
    for spec in COLLECTIONS:
        if spec.kind not in _ABSENCE_WORTH_STATING:
            continue
        if getattr(model, spec.attribute, None):
            continue
        item = EvidenceItem(
            evidence_id=f"ev:absence:{spec.kind}",
            kind="absence",
            origin="absence",
            label=f"No {spec.kind} data",
            statement=(f"No source in this project records any {spec.kind} "
                       f"information."),
        )
        item.search_text = f"{spec.kind} missing absent no data not reported"
        index.add(item)

    for topic in requested_topics:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.casefold()).strip("-")
        if not slug or index.get(f"ev:absence:{slug}"):
            continue
        if _covered(index, topic):
            continue
        item = EvidenceItem(
            evidence_id=f"ev:absence:{slug}",
            kind="absence",
            origin="absence",
            label=f"Nothing covers “{topic}”",
            statement=(f"The request asked for “{topic}”, and no uploaded source "
                       f"or recorded fact covers it."),
        )
        item.search_text = f"{topic} missing absent requested not covered"
        index.add(item)


def _covered(index: EvidenceIndex, topic: str) -> bool:
    """Whether any single piece of evidence plausibly speaks to a requested topic.

    Requires a *majority* of the topic's content words on one item, matched as
    whole words. Matching on any one word is too generous to be useful: "TSA
    exit readiness" then counts as covered because a Day 1 *readiness* figure
    exists, and the report never says it has nothing on TSA exit.

    Erring toward "absent" is still the safer direction — a spurious gap note is
    visible and correctable, a missing one is neither.
    """
    words = {w for w in _normalize(topic).split() if len(w) > 3}
    if not words:
        return True
    # A one- or two-word topic must match in full; longer ones may lose a word
    # to phrasing ("cash flow impact" vs "cash flow"), but never more than 40%.
    needed = len(words) if len(words) <= 2 else max(2, math.ceil(len(words) * 0.6))
    for item in index.items.values():
        if item.is_absence:
            continue
        haystack = set(_normalize(item.search_text).split())
        if len(words & haystack) >= needed:
            return True
    return False
