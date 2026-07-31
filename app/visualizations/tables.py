"""Build a table from evidence, and keep its cells editable.

Columns are declared per evidence kind rather than derived from whatever fields
happen to be populated: a risk table whose columns change depending on which
risks were extracted is not a table anybody can compare across weeks.

Each cell carries an `EntityFieldRef` where one exists, which is what lets the
preview's inline editing write a corrected value back through to the data model.
That machinery already exists (`app/agent/corrections.py`); this keeps it wired.

Two rules inherited from the existing renderer and worth restating, because both
were hard-won:

* A missing field is "Not Reported", never blank and never zero.
* A gap that matters — an unowned critical risk, an unmitigated one — is marked
  in the cell itself, so the exception is visible in the table rather than only
  in prose beside it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional, Sequence

from app.evidence.model import EvidenceIndex, EvidenceItem
from app.report import format as fmt
from app.report.content import Cell, Column, EntityFieldRef
from app.visualizations.specs import TableSpec

log = logging.getLogger("pmi.visualizations.tables")

#: Beyond this a table stops being readable on a slide. The spec records the
#: true total so the page can say "showing 12 of 137" rather than presenting a
#: sample as the whole.
DEFAULT_ROW_LIMIT = 12

MISSING = fmt.NOT_REPORTED


@dataclass(frozen=True)
class ColumnSpec:
    header: str
    kind: str = "text"
    read: Optional[Callable[[EvidenceItem], Any]] = None
    field: Optional[str] = None
    rag: bool = False
    negative_is_bad: bool = False
    #: Text to substitute when the value is missing *and* its absence is itself
    #: the finding. "No owner" reads as a gap; "Not Reported" reads as clerical.
    missing_flag: str = ""


def _payload(field: str) -> Callable[[EvidenceItem], Any]:
    return lambda item: item.payload.get(field)


#: One column set per kind. Deliberately explicit.
COLUMNS: dict[str, tuple[ColumnSpec, ...]] = {
    "risk": (
        ColumnSpec("Risk", read=lambda i: i.label, field="title"),
        ColumnSpec("Workstream", read=lambda i: i.workstream, field="workstream"),
        ColumnSpec("Score", "number", read=_payload("risk_score"),
                   field="risk_score", rag=True),
        ColumnSpec("Owner", read=lambda i: i.owner, field="owner",
                   missing_flag="NO OWNER"),
        ColumnSpec("Mitigation", read=_payload("mitigation_action"),
                   field="mitigation_action", missing_flag="NO MITIGATION"),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "issue": (
        ColumnSpec("Issue", read=lambda i: i.label, field="title"),
        ColumnSpec("Severity", read=lambda i: i.severity, field="severity",
                   rag=True),
        ColumnSpec("Owner", read=lambda i: i.owner, field="owner",
                   missing_flag="NO OWNER"),
        ColumnSpec("Resolution", read=_payload("resolution_action"),
                   field="resolution_action", missing_flag="NO ACTION"),
        ColumnSpec("Due", "date", read=lambda i: i.due, field="due_date"),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "task": (
        ColumnSpec("Activity", read=lambda i: i.label, field="title"),
        ColumnSpec("Workstream", read=lambda i: i.workstream, field="workstream"),
        ColumnSpec("Owner", read=lambda i: i.owner, field="owner",
                   missing_flag="UNASSIGNED"),
        ColumnSpec("Due", "date", read=lambda i: i.due, field="due_date",
                   missing_flag="NO DEADLINE"),
        ColumnSpec("Progress", "percent", read=_payload("progress_percentage"),
                   field="progress_percentage"),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "milestone": (
        ColumnSpec("Milestone", read=lambda i: i.label, field="name"),
        ColumnSpec("Workstream", read=lambda i: i.workstream, field="workstream"),
        ColumnSpec("Planned", "date", read=_payload("planned_date"),
                   field="planned_date"),
        ColumnSpec("Forecast", "date", read=_payload("forecast_date"),
                   field="forecast_date"),
        ColumnSpec("Slippage", "number", read=_payload("delay_days"),
                   field="delay_days", negative_is_bad=False, rag=True),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "budget": (
        ColumnSpec("Cost line", read=lambda i: i.label, field="category"),
        ColumnSpec("Budget", "currency", read=_payload("budget"), field="budget"),
        ColumnSpec("Actual", "currency", read=_payload("actual"), field="actual"),
        ColumnSpec("Forecast", "currency", read=_payload("forecast"),
                   field="forecast"),
        ColumnSpec("Variance", "currency", read=_payload("variance"),
                   field="variance", negative_is_bad=True, rag=True),
    ),
    "synergy": (
        ColumnSpec("Initiative", read=lambda i: i.label, field="title"),
        ColumnSpec("Target", "currency", read=_payload("target_value"),
                   field="target_value"),
        ColumnSpec("Realised", "currency", read=_payload("realized_value"),
                   field="realized_value"),
        ColumnSpec("Remaining", "currency", read=_payload("remaining_value"),
                   field="remaining_value"),
        ColumnSpec("By", "date", read=_payload("planned_realization_date"),
                   field="planned_realization_date",
                   missing_flag="NO DATE"),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "decision": (
        ColumnSpec("Decision", read=lambda i: i.label, field="title"),
        ColumnSpec("Body", read=_payload("decision_body"), field="decision_body"),
        ColumnSpec("Owner", read=lambda i: i.owner, field="decision_owner",
                   missing_flag="NO OWNER"),
        ColumnSpec("Needed by", "date", read=lambda i: i.due,
                   field="decision_deadline", missing_flag="NO DEADLINE"),
        ColumnSpec("Recommendation", read=_payload("recommended_option"),
                   field="recommended_option"),
    ),
    "dependency": (
        ColumnSpec("Dependency", read=lambda i: i.label, field="description"),
        ColumnSpec("From", read=_payload("providing_workstream"),
                   field="providing_workstream"),
        ColumnSpec("To", read=_payload("receiving_workstream"),
                   field="receiving_workstream"),
        ColumnSpec("Required", "date", read=lambda i: i.due,
                   field="required_date"),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "workstream": (
        ColumnSpec("Workstream", read=lambda i: i.label, field="name"),
        ColumnSpec("Lead", read=lambda i: i.owner, field="lead",
                   missing_flag="NO LEAD"),
        ColumnSpec("Progress", "percent", read=_payload("progress_percentage"),
                   field="progress_percentage"),
        ColumnSpec("Status", read=lambda i: i.status, field="status", rag=True),
    ),
    "kpi": (
        ColumnSpec("Indicator", read=lambda i: i.label, field="name"),
        ColumnSpec("Current", "number", read=_payload("current_value"),
                   field="current_value"),
        ColumnSpec("Target", "number", read=_payload("target_value"),
                   field="target_value"),
        ColumnSpec("Trend", read=_payload("trend"), field="trend"),
    ),
    "conflict": (
        ColumnSpec("Subject", read=lambda i: i.label),
        ColumnSpec("What the sources say", read=lambda i: _claims(i)),
        ColumnSpec("Severity", read=lambda i: i.severity, rag=True),
        ColumnSpec("Resolved to", read=lambda i: i.payload.get("resolved_value"),
                   missing_flag="UNRESOLVED"),
    ),
}

#: Used when the evidence has no declared column set, or mixes kinds.
GENERIC_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("Item", read=lambda i: i.label),
    ColumnSpec("What it says", read=lambda i: i.statement),
    ColumnSpec("Value", read=lambda i: i.display),
    ColumnSpec("Source", read=lambda i: ", ".join(i.source_files) or "computed"),
)


def build_table(spec_id: str, items: Sequence[EvidenceItem], *,
                title: str = "", caption: str = "",
                row_limit: Optional[int] = DEFAULT_ROW_LIMIT) -> TableSpec:
    """A table over `items`, columns chosen by their kind."""
    usable = [i for i in items if not i.is_absence]
    columns, usable = _columns_for(usable)
    total = len(usable)
    shown = usable[:row_limit] if row_limit else usable

    rows: list[list[Cell]] = []
    emphasis_rows: list[int] = []
    for index, item in enumerate(shown):
        row = [_cell(item, column) for column in columns]
        rows.append(row)
        if item.is_contested or item.severity in ("critical", "high"):
            emphasis_rows.append(index)

    table = TableSpec(
        spec_id=spec_id,
        title=title,
        columns=[Column(header=c.header, kind=c.kind, rag=c.rag,
                        negative_is_bad=c.negative_is_bad) for c in columns],
        rows=rows,
        row_evidence_ids=[i.evidence_id for i in shown],
        total_rows=total,
        row_limit=row_limit,
        emphasis_rows=emphasis_rows,
        caption=caption or title,
        evidence_ids=[i.evidence_id for i in shown],
    )
    from app.evidence import provenance

    table.source_note = provenance.source_note(shown)
    if table.is_truncated:
        table.warnings.append(table.truncation_note())
    return table


def build_for(spec_id: str, evidence: EvidenceIndex,
              evidence_ids: Sequence[str], **kwargs) -> TableSpec:
    return build_table(spec_id, evidence.resolve(evidence_ids), **kwargs)


def _columns_for(items: Sequence[EvidenceItem]
                 ) -> tuple[tuple[ColumnSpec, ...], list[EvidenceItem]]:
    """Column set and the rows it applies to.

    Retrieval returns whatever is most relevant, which for a page about
    milestones is usually mostly milestones plus a couple of related tasks. The
    first attempt here demanded a single kind and otherwise fell back to generic
    `Item / What it says / Value / Source` columns — so a milestone page got a
    table with no dates in it, which is the wrong table.

    So: use the *dominant* kind's columns and show that kind's rows. The
    off-kind records are dropped from the table rather than flattened into
    columns that do not describe them; they are still on the page, in its prose
    and its provenance.
    """
    if not items:
        return GENERIC_COLUMNS, []

    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    dominant, count = max(counts.items(), key=lambda kv: (kv[1], kv[0]))

    columns = COLUMNS.get(dominant)
    if columns is None:
        return GENERIC_COLUMNS, list(items)
    if len(counts) == 1:
        # Homogeneous, however few rows: a one-row budget table still wants
        # budget columns.
        return columns, list(items)
    # Mixed. A genuine mixture — no kind holding even a third — has no natural
    # column set, and forcing one would mislabel most of the rows.
    if count < max(2, len(items) / 3):
        return GENERIC_COLUMNS, list(items)
    return columns, [i for i in items if i.kind == dominant]


# ---------------------------------------------------------------- internals
def _cell(item: EvidenceItem, column: ColumnSpec) -> Cell:
    raw = column.read(item) if column.read else None
    text = _format(raw, column.kind, item)

    if raw in (None, "") and column.missing_flag:
        # An absence that is itself the finding, marked where a reader scanning
        # the column will see it.
        return Cell(text=f"⚠ {column.missing_flag}", value=None, emphasis="bad",
                    ref=_ref(item, column))
    return Cell(text=text, value=raw if isinstance(raw, (int, float)) else None,
                emphasis=_emphasis(item, raw, column), ref=_ref(item, column))


def _format(raw: Any, kind: str, item: EvidenceItem) -> str:
    if raw is None or raw == "":
        return MISSING
    if kind == "date":
        if isinstance(raw, (date, datetime)):
            return fmt.date_str(raw)
        text = str(raw)
        return fmt.date_str(date.fromisoformat(text[:10])) if len(text) >= 10 \
            and text[:4].isdigit() else text
    if kind == "percent":
        return f"{fmt.num(raw)}%" if isinstance(raw, (int, float)) else str(raw)
    if kind == "currency":
        if not isinstance(raw, (int, float)):
            return str(raw)
        currency = item.currency or ""
        return f"{currency} {fmt.num(raw)}".strip()
    if kind == "number":
        return fmt.num(raw) if isinstance(raw, (int, float)) else str(raw)
    return str(getattr(raw, "value", raw))


def _emphasis(item: EvidenceItem, raw: Any, column: ColumnSpec) -> str:
    if raw is None or raw == "":
        return "muted"
    if column.negative_is_bad and isinstance(raw, (int, float)) and raw < 0:
        return "bad"
    if column.rag:
        text = str(getattr(raw, "value", raw)).casefold()
        if text in ("completed", "on_track", "low"):
            return "good"
        if text in ("at_risk", "blocked", "high", "critical"):
            return "bad"
        if text in ("in_progress", "medium"):
            return "warn"
    if item.is_contested:
        return "warn"
    return "none"


def _ref(item: EvidenceItem, column: ColumnSpec) -> Optional[EntityFieldRef]:
    """The handle that makes this cell editable and writable back to the model.

    Only for fields that exist on a real entity. A computed or aggregate cell
    has nothing to write to, and offering to edit it would be a lie.
    """
    if not column.field or not item.entity_id or not item.entity_type:
        return None
    if item.origin not in ("direct_source_value", "normalized_value"):
        return None
    return EntityFieldRef(entity_type=item.entity_type, entity_id=item.entity_id,
                         field=column.field)


def _claims(item: EvidenceItem) -> str:
    values = item.payload.get("values") or {}
    if isinstance(values, dict) and values:
        return "; ".join(f"{name}: {value}" for name, value in values.items())
    return item.statement
