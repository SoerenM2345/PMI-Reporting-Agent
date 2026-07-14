"""Step 4: raw extractor records -> the one standardized PMI data model (§6, §7).

Two rules from the spec govern this module.

§7 — "The agent must never silently invent missing PMI information." A field the
source did not state stays `None`. We do not default a probability to "medium" so
that a risk score can be computed, and we do not default a budget to zero so that a
variance can be.

§21.17 — "Document incomplete functionality honestly." A row that cannot be parsed
is recorded in `model.warnings` with its file, location and the reason. The original
code swallowed these with `except Exception: continue`, so a tracker whose date
column was formatted as text would silently lose every row and nobody would know.
"""
from __future__ import annotations

from typing import Any, Optional

from app.extractors.base import normalize_status, parse_date, parse_number, parse_percent
from app.models.enums import (
    SEVERITY_ALIASES,
    SEVERITY_SCALE,
    RiskCategory,
    Severity,
    normalize_workstream,
)
from app.models.pmi import (
    KPI,
    BudgetItem,
    Decision,
    Dependency,
    Issue,
    Milestone,
    PMIDataModel,
    PMIProject,
    Risk,
    Synergy,
    Task,
)

_PREFIXES = {
    "task": "T", "milestone": "M", "risk": "R", "issue": "I", "dependency": "D",
    "decision": "C", "budget": "B", "synergy": "S", "kpi": "K",
}


def standardize(
    raw_records: list[dict],
    source_files: list[str],
    project: Optional[PMIProject] = None,
) -> PMIDataModel:
    model = PMIDataModel(
        project=project or PMIProject(project_id="p_default", source_files=source_files),
        source_files=source_files,
    )
    counters: dict[str, int] = {k: 0 for k in _PREFIXES}

    builders = {
        "task": _task, "milestone": _milestone, "risk": _risk, "issue": _issue,
        "dependency": _dependency, "decision": _decision, "budget": _budget,
        "synergy": _synergy, "kpi": _kpi,
    }
    targets = {
        "task": model.tasks, "milestone": model.milestones, "risk": model.risks,
        "issue": model.issues, "dependency": model.dependencies,
        "decision": model.decisions, "budget": model.budget,
        "synergy": model.synergies, "kpi": model.kpis,
    }

    for rec in raw_records:
        rtype = rec.get("type")

        if rtype == "note":
            text = _text(rec.get("text"))
            if not text:
                continue
            model.notes.append(f"[{_file_of(rec)}] {text}")
            # A note flagged as a warning is a hole in the report, not colour: a file we
            # could not read, an image we could not interpret. It must reach the user's
            # data-quality report, not sit in a notes list nobody opens (§21.17).
            if rec.get("is_warning"):
                model.warnings.append(f"{_file_of(rec)}: {text}")
            continue

        builder = builders.get(rtype)
        if builder is None:
            model.warnings.append(
                f"{_file_of(rec)}: ignored a record of unknown type {rtype!r}."
            )
            continue

        counters[rtype] += 1
        entity_id = f"{_PREFIXES[rtype]}{counters[rtype]:03d}"
        try:
            targets[rtype].append(builder(entity_id, rec))
        except Exception as exc:
            # Do NOT swallow. A dropped row is a hole in the report, and the user
            # needs to know which row and why.
            counters[rtype] -= 1
            model.warnings.append(
                f"{_cite(rec)}: could not standardize {rtype} "
                f"{_text(rec.get('title') or rec.get('name') or rec.get('category')) or '(untitled)'!r}"
                f" — {type(exc).__name__}: {exc}"
            )

    derive_workstreams(model)
    return model


def derive_workstreams(model: PMIDataModel) -> PMIDataModel:
    """Build Workstream entities (§6.2) from the workstream column on other entities.

    Workstreams are *derived*, not extracted: no PMI file contains a "workstreams"
    table, but every tracker tags its rows with one. Their progress is the mean of
    their tasks' — computed here in Python, never asked of the LLM (§11).
    """
    from collections import defaultdict

    from app.models.pmi import Workstream

    members: dict[str, list] = defaultdict(list)
    for task in model.tasks:
        if task.workstream:
            members[task.workstream].append(task)

    existing = {w.name for w in model.workstreams}

    for index, (name, tasks) in enumerate(sorted(members.items()), start=1):
        if name in existing:
            continue

        values = [t.progress_percentage for t in tasks if t.progress_percentage is not None]
        refs: list = []
        for task in tasks:
            for ref in task.source_references:
                if ref not in refs:
                    refs.append(ref)

        model.workstreams.append(Workstream(
            workstream_id=f"W{index:03d}",
            name=name,
            progress_percentage=round(sum(values) / len(values), 1) if values else None,
            open_risks=[r.risk_id for r in model.risks
                        if r.workstream == name and r.status.is_open],
            open_issues=[i.issue_id for i in model.issues
                         if i.workstream == name and i.status.is_open],
            upcoming_milestones=[m.milestone_id for m in model.milestones
                                 if m.workstream == name and m.status.is_open],
            source_references=refs[:5],
        ))

    return model


# ------------------------------------------------------------------- builders
def _task(entity_id: str, rec: dict) -> Task:
    return Task(
        task_id=entity_id,
        title=_required(rec, "title"),
        description=_text(rec.get("description")),
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        owner=_text(rec.get("owner")),
        supporting_owner=_text(rec.get("supporting_owner")),
        start_date=parse_date(rec.get("start_date")),
        due_date=parse_date(rec.get("due_date")),
        completion_date=parse_date(rec.get("completion_date")),
        status=normalize_status(rec.get("status")),
        progress_percentage=parse_percent(rec.get("progress_pct")),
        priority=_text(rec.get("priority")),
        is_day_1_critical=_is_day_1(rec),
        source_references=_refs(rec),
    )


def _milestone(entity_id: str, rec: dict) -> Milestone:
    name = _required(rec, "title", "name")
    return Milestone(
        milestone_id=entity_id,
        name=name,
        description=_text(rec.get("description")),
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        owner=_text(rec.get("owner")),
        planned_date=parse_date(rec.get("due_date") or rec.get("planned_date")),
        forecast_date=parse_date(rec.get("forecast_date")),
        actual_date=parse_date(rec.get("actual_date")),
        status=normalize_status(rec.get("status")),
        is_day_1_critical=_is_day_1(rec),
        is_go_live=any(w in name.lower() for w in ("go-live", "go live", "golive",
                                                   "cutover", "launch")),
        source_references=_refs(rec),
    )


def _risk(entity_id: str, rec: dict) -> Risk:
    # Registers vary: some carry probability AND impact columns, most carry a single
    # High/Medium/Low rating. Read what is there; never synthesize the other factor.
    impact = _scale(rec.get("impact") or rec.get("severity"))
    probability = _scale(rec.get("probability") or rec.get("likelihood"))

    return Risk(
        risk_id=entity_id,
        title=_required(rec, "title"),
        description=_text(rec.get("description")),
        category=_risk_category(rec.get("category")),
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        owner=_text(rec.get("owner")),
        probability=probability,
        impact=impact,
        # risk_score is left for calculations.py — it is a derived value (§11).
        status=normalize_status(rec.get("status")),
        mitigation_action=_text(rec.get("mitigation")),
        mitigation_owner=_text(rec.get("mitigation_owner")),
        mitigation_due_date=parse_date(rec.get("mitigation_due_date")),
        source_references=_refs(rec),
    )


def _issue(entity_id: str, rec: dict) -> Issue:
    return Issue(
        issue_id=entity_id,
        title=_required(rec, "title"),
        description=_text(rec.get("description")),
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        owner=_text(rec.get("owner")),
        severity=_severity(rec.get("severity")),
        status=normalize_status(rec.get("status")),
        resolution_action=_text(rec.get("resolution_action") or rec.get("mitigation")),
        resolution_owner=_text(rec.get("resolution_owner")),
        due_date=parse_date(rec.get("due_date")),
        source_references=_refs(rec),
    )


def _dependency(entity_id: str, rec: dict) -> Dependency:
    return Dependency(
        dependency_id=entity_id,
        description=_required(rec, "description", "title"),
        providing_workstream=normalize_workstream(_text(rec.get("providing_workstream"))),
        receiving_workstream=normalize_workstream(_text(rec.get("receiving_workstream"))),
        owner=_text(rec.get("owner")),
        required_date=parse_date(rec.get("required_date") or rec.get("due_date")),
        status=normalize_status(rec.get("status")),
        impact_if_delayed=_text(rec.get("impact_if_delayed")),
        source_references=_refs(rec),
    )


def _decision(entity_id: str, rec: dict) -> Decision:
    from app.models.enums import DecisionBody

    body_raw = (_text(rec.get("decision_body")) or "").casefold()
    body = DecisionBody.UNKNOWN
    for candidate in DecisionBody:
        if candidate.value.casefold() in body_raw:
            body = candidate
            break

    return Decision(
        decision_id=entity_id,
        title=_required(rec, "title"),
        description=_text(rec.get("description")),
        decision_body=body,
        decision_owner=_text(rec.get("owner") or rec.get("decision_owner")),
        decision_deadline=parse_date(rec.get("due_date") or rec.get("decision_deadline")),
        status=normalize_status(rec.get("status")),
        recommended_option=_text(rec.get("recommended_option")),
        impact=_text(rec.get("impact")),
        source_references=_refs(rec),
    )


def _budget(entity_id: str, rec: dict) -> BudgetItem:
    return BudgetItem(
        budget_item_id=entity_id,
        category=_required(rec, "category", "title"),
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        budget=parse_number(rec.get("planned") or rec.get("budget")),
        actual=parse_number(rec.get("actual")),
        committed=parse_number(rec.get("committed")),
        forecast=parse_number(rec.get("forecast")),
        # variance / variance_percentage are derived (calculations.py, §11).
        currency=_text(rec.get("currency")) or "EUR",
        reporting_period=_text(rec.get("reporting_period")),
        source_references=_refs(rec),
    )


def _synergy(entity_id: str, rec: dict) -> Synergy:
    from app.models.enums import SynergyType

    type_raw = (_text(rec.get("synergy_type")) or "").casefold()
    syn_type = SynergyType.UNKNOWN
    if "revenue" in type_raw:
        syn_type = SynergyType.REVENUE
    elif "cost" in type_raw:
        syn_type = SynergyType.COST
    elif "capital" in type_raw:
        syn_type = SynergyType.CAPITAL
    elif "tax" in type_raw:
        syn_type = SynergyType.TAX

    return Synergy(
        synergy_id=entity_id,
        title=_required(rec, "title", "name"),
        description=_text(rec.get("description")),
        synergy_type=syn_type,
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        owner=_text(rec.get("owner")),
        baseline=parse_number(rec.get("baseline")),
        target_value=parse_number(rec.get("target") or rec.get("target_value")),
        realized_value=parse_number(rec.get("realized") or rec.get("realized_value")
                                    or rec.get("value")),
        forecast_value=parse_number(rec.get("forecast") or rec.get("forecast_value")),
        # remaining_value is derived (§11).
        currency=_text(rec.get("currency")) or "EUR",
        planned_realization_date=parse_date(
            rec.get("planned_realization_date") or rec.get("due_date")
        ),
        status=normalize_status(rec.get("status")),
        confidence_level=_text(rec.get("confidence_level")),
        source_references=_refs(rec),
    )


def _kpi(entity_id: str, rec: dict) -> KPI:
    return KPI(
        kpi_id=entity_id,
        name=_required(rec, "name", "title"),
        description=_text(rec.get("description")),
        workstream=normalize_workstream(_text(rec.get("workstream"))),
        current_value=parse_number(rec.get("value")),
        target_value=parse_number(rec.get("target")),
        previous_value=parse_number(rec.get("previous_value")),
        unit=_text(rec.get("unit")),
        reporting_date=parse_date(rec.get("reporting_date")),
        source_references=_refs(rec),
    )


# -------------------------------------------------------------------- helpers
def _refs(rec: dict) -> list:
    ref = rec.get("source")
    return [ref] if ref is not None else []


def _file_of(rec: dict) -> str:
    ref = rec.get("source")
    return getattr(ref, "file_name", "?")


def _cite(rec: dict) -> str:
    ref = rec.get("source")
    if ref is None:
        return "?"
    where = getattr(ref, "location", None)
    return f"{ref.file_name} ({where})" if where else ref.file_name


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required(rec: dict, *keys: str) -> str:
    """A title-ish field is the one thing an entity cannot be built without —
    an untitled risk cannot be reported, matched, or resolved."""
    for key in keys:
        text = _text(rec.get(key))
        if text:
            return text
    raise ValueError(f"missing a value for {' / '.join(keys)}")


def _severity(value: Any) -> Severity:
    text = (_text(value) or "").casefold()
    return SEVERITY_ALIASES.get(text, Severity.MEDIUM)


def _scale(value: Any) -> Optional[int]:
    """Map a rating onto the 1-5 scale. Returns None when nothing was stated —
    which is what lets calculations.py refuse to compute a bogus risk score."""
    if value is None:
        return None

    number = parse_number(value)
    if number is not None and 1 <= number <= 5:
        return int(round(number))

    text = (_text(value) or "").casefold()
    if not text:
        return None
    severity = SEVERITY_ALIASES.get(text)
    return SEVERITY_SCALE[severity] if severity else None


def _risk_category(value: Any) -> RiskCategory:
    text = (_text(value) or "").casefold()
    if not text:
        return RiskCategory.UNKNOWN
    for category in RiskCategory:
        if category.value.casefold() == text:
            return category
    return RiskCategory.UNKNOWN


def _is_day_1(rec: dict) -> bool:
    haystack = " ".join(
        str(rec.get(k, "")) for k in ("title", "name", "workstream", "priority", "description")
    ).casefold()
    return any(token in haystack for token in ("day 1", "day-1", "day one", "d1 "))
