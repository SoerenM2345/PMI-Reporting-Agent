"""Fill a `ChartRequest` with values read from evidence.

This function is the structural guarantee that a chart cannot contain an
invented number. The model said *which* records to plot and *which field* of
each to read; every figure that ends up in the spec was read here, in Python,
from the evidence index — and carries the `evidence_id` it came from.

The rule about missing values is enforced at the point of reading, not later: a
record with no figure for a series produces a `DataPoint` with `value=None`, and
nothing downstream is permitted to turn that into a zero. "Nobody reported this"
and "this is nil" are different claims and the second one is often much worse
news than the first.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional, Sequence

from app.evidence.model import EvidenceIndex, EvidenceItem
from app.report import format as fmt
from app.visualizations.specs import (
    Annotation,
    AxisSpec,
    ChartRequest,
    ChartSeries,
    ChartSpec,
    DataPoint,
    DiagramEdge,
    DiagramNode,
    DiagramRequest,
    DiagramSpec,
    MatrixAxes,
    NATIVE_PPTX_TYPES,
    SeriesRequest,
)

log = logging.getLogger("pmi.visualizations.builder")

#: Fields a series may read, mapped to how they are read. Anything else is
#: rejected rather than pulled out of the payload by name: an open `getattr`
#: over model-supplied strings is how a chart ends up plotting an id.
_VALUE_FIELDS: dict[str, str] = {
    "value": "value",
    "budget": "budget",
    "actual": "actual",
    "committed": "committed",
    "forecast": "forecast",
    "variance": "variance",
    "variance_percentage": "variance_percentage",
    "target_value": "target_value",
    "realized_value": "realized_value",
    "forecast_value": "forecast_value",
    "remaining_value": "remaining_value",
    "baseline": "baseline",
    "risk_score": "risk_score",
    "probability": "probability",
    "impact": "impact",
    "progress_percentage": "progress_percentage",
    "current_value": "current_value",
    "previous_value": "previous_value",
    "delay_days": "delay_days",
}

_CATEGORY_FIELDS = ("label", "workstream", "owner", "status", "severity",
                    "period", "category")


def build_chart(request: ChartRequest, evidence: EvidenceIndex) -> ChartSpec:
    """Resolve a chart request against evidence. Never raises; records instead."""
    warnings: list[str] = []
    items = evidence.resolve(request.evidence_ids)
    unknown = evidence.unknown(request.evidence_ids)
    if unknown:
        warnings.append(f"{len(unknown)} evidence id(s) in this chart do not "
                        f"exist and were dropped: {', '.join(unknown[:3])}.")

    series_requests = request.series or [SeriesRequest(name=request.title or "Value")]
    ordered = _order(items, request, series_requests)
    categories = [_category(item, request.category_field) for item in ordered]

    series: list[ChartSeries] = []
    for series_request in series_requests:
        field = _VALUE_FIELDS.get(series_request.value_field)
        if field is None:
            warnings.append(
                f"Series {series_request.name!r} asked for an unknown field "
                f"{series_request.value_field!r}; it was dropped.")
            continue
        points = [_point(item, field, _category(item, request.category_field))
                  for item in ordered]
        unit, currency, period = _series_meta(ordered, field)
        series.append(ChartSeries(
            name=series_request.name, points=points, unit=unit,
            currency=currency, period=period,
            kind_override=series_request.kind_override,
        ))

    unit = next((s.unit for s in series if s.unit), None)
    currency = next((s.currency for s in series if s.currency), None)
    is_percentage = unit == "%"

    spec = ChartSpec(
        spec_id=request.spec_id or "chart",
        chart_type=request.chart_type,
        title=request.title,
        insight=request.insight,
        series=series,
        categories=categories,
        category_axis=AxisSpec(title=_axis_title(request.category_field)),
        value_axis=AxisSpec(unit=unit, currency=currency,
                            is_percentage=is_percentage,
                            title=_value_axis_title(unit, currency)),
        annotations=[_annotation(a, evidence) for a in request.annotations],
        legend=request.legend if len(series) > 1 else "none",
        data_labels=request.data_labels,
        caption=request.caption or request.insight or request.title,
        alt_text=request.alt_text or _alt_text(request, categories, series),
        evidence_ids=[i.evidence_id for i in ordered],
        render_as_image=request.chart_type not in NATIVE_PPTX_TYPES,
        warnings=warnings,
    )
    _annotate_provenance(spec, ordered)
    return spec


def _order(items: Sequence[EvidenceItem], request: ChartRequest,
           series_requests: Sequence[SeriesRequest]) -> list[EvidenceItem]:
    if request.sort == "none":
        return list(items)
    if request.sort == "category":
        return sorted(items, key=lambda i: _category(i, request.category_field))
    if request.sort == "chronological":
        # Missing dates sort last: an undated record has no place on a timeline
        # and pretending it is the earliest would misread the sequence.
        return sorted(items, key=lambda i: (i.due is None, i.due or date.max))

    field = _VALUE_FIELDS.get(series_requests[0].value_field, "value")
    reverse = request.sort == "value_desc"

    def key(item: EvidenceItem):
        value = _read(item, field)
        # Missing values sort last either way — never as a zero at one end.
        return (value is None, -(value or 0.0) if reverse else (value or 0.0))

    return sorted(items, key=key)


def _category(item: EvidenceItem, field: str) -> str:
    if field not in _CATEGORY_FIELDS:
        field = "label"
    if field == "label":
        return item.label or item.entity_id or item.evidence_id
    if field == "category":
        return str(item.payload.get("category") or item.label)
    return str(getattr(item, field, None) or fmt.NOT_REPORTED)


def _point(item: EvidenceItem, field: str, label: str) -> DataPoint:
    value = _read(item, field)
    unit = _unit_for(item, field)
    return DataPoint(
        label=label,
        value=value,
        evidence_id=item.evidence_id,
        display=_display(value, unit, item.currency),
        emphasis=_emphasis(item, value),
        note=_note(item, value),
    )


def _read(item: EvidenceItem, field: str) -> Optional[float]:
    """The number, or `None`. Never a zero standing in for a gap."""
    raw = item.value if field == "value" else item.payload.get(field)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _unit_for(item: EvidenceItem, field: str) -> Optional[str]:
    if field in ("progress_percentage", "variance_percentage"):
        return "%"
    if field in ("risk_score", "probability", "impact", "delay_days"):
        return None
    if field == "value":
        return item.unit
    return item.currency


def _display(value: Optional[float], unit: Optional[str],
             currency: Optional[str]) -> str:
    if value is None:
        return fmt.NOT_REPORTED
    text = fmt.num(value)
    if unit == "%":
        return f"{text}%"
    if currency and unit != "%":
        return f"{currency} {text}"
    return f"{unit} {text}".strip() if unit else text


def _emphasis(item: EvidenceItem, value: Optional[float]) -> str:
    if value is None:
        return "muted"
    if item.is_contested:
        return "warn"
    if item.severity in ("critical", "high"):
        return "bad"
    return "none"


def _note(item: EvidenceItem, value: Optional[float]) -> str:
    if value is None:
        return "not reported"
    if item.is_contested:
        return "sources disagree"
    if item.needs_review:
        return "read from an image"
    return ""


def _series_meta(items: Sequence[EvidenceItem],
                 field: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    units = {_unit_for(i, field) for i in items}
    currencies = {i.currency for i in items if i.currency}
    periods = {i.period for i in items if i.period}
    return (
        next(iter(units)) if len(units) == 1 else None,
        next(iter(currencies)) if len(currencies) == 1 else
        (next(iter(sorted(currencies))) if currencies else None),
        next(iter(periods)) if len(periods) == 1 else None,
    )


def _axis_title(field: str) -> str:
    return {"workstream": "Workstream", "owner": "Owner", "status": "Status",
            "severity": "Severity", "period": "Period"}.get(field, "")


def _value_axis_title(unit: Optional[str], currency: Optional[str]) -> str:
    if unit == "%":
        return "Per cent"
    if currency:
        return currency
    return unit or ""


def _alt_text(request: ChartRequest, categories: Sequence[str],
              series: Sequence[ChartSeries]) -> str:
    """A real description, because a chart nobody can read is not accessible."""
    names = ", ".join(s.name for s in series) or "one series"
    return (f"{request.chart_type.replace('_', ' ')} chart, {names} across "
            f"{len(categories)} categories. {request.insight}").strip()


def _annotation(request, evidence: EvidenceIndex) -> Annotation:
    item = evidence.get(request.anchor_evidence_id) if request.anchor_evidence_id \
        else None
    value = None
    if item is not None and isinstance(item.value, (int, float)):
        value = float(item.value)
    return Annotation(text=request.text, kind=request.kind, value=value,
                      evidence_id=request.anchor_evidence_id)


def _annotate_provenance(spec: ChartSpec, items: Sequence[EvidenceItem]) -> None:
    from app.evidence import provenance

    spec.source_note = provenance.source_note(items)
    if any(i.needs_review for i in items):
        spec.caption = (spec.caption.rstrip(".")
                        + ". Includes figures read from an image; confirm before "
                          "circulation.")
    contested = [i for i in items if i.is_contested]
    if contested:
        spec.caption = (spec.caption.rstrip(".")
                        + f". {len(contested)} value(s) shown here are disputed "
                          f"between sources.")


# ============================================================== diagrams
def build_diagram(request: DiagramRequest, evidence: EvidenceIndex) -> DiagramSpec:
    """Resolve a diagram request. Dates and deltas come from evidence."""
    warnings: list[str] = []
    unknown = evidence.unknown(
        [n.evidence_id for n in request.nodes if n.evidence_id]
        + list(request.evidence_ids))
    if unknown:
        warnings.append(f"{len(unknown)} evidence id(s) in this diagram do not "
                        f"exist: {', '.join(unknown[:3])}.")

    nodes: list[DiagramNode] = []
    for node_request in request.nodes:
        item = evidence.get(node_request.evidence_id) if node_request.evidence_id \
            else None
        nodes.append(DiagramNode(
            node_id=node_request.node_id or f"n{len(nodes) + 1}",
            label=node_request.label or (item.label if item else ""),
            sublabel=node_request.sublabel or _sublabel(item),
            parent_id=node_request.parent_id,
            evidence_id=node_request.evidence_id,
            status=node_request.status if node_request.status != "none"
            else _status_of(item),
            row=node_request.row,
            column=node_request.column,
            at=_when(item),
            value=float(item.value) if item is not None
            and isinstance(item.value, (int, float)) else None,
        ))

    # A diagram whose nodes were not enumerated can still be derived from the
    # evidence it names — a timeline of milestones needs no node list.
    if not nodes and request.evidence_ids:
        nodes = _nodes_from_evidence(evidence, request)

    spec = DiagramSpec(
        spec_id=request.spec_id or "diagram",
        diagram_type=request.diagram_type,
        title=request.title,
        insight=request.insight,
        nodes=nodes,
        edges=[DiagramEdge(from_id=e.from_id, to_id=e.to_id, label=e.label,
                           style=e.style) for e in request.edges],
        axes=(MatrixAxes(x_label=request.x_axis_label, y_label=request.y_axis_label)
              if request.diagram_type in ("risk_matrix", "two_by_two") else None),
        caption=request.caption or request.insight or request.title,
        alt_text=request.alt_text or _diagram_alt(request, nodes),
        evidence_ids=[n.evidence_id for n in nodes if n.evidence_id]
        or list(request.evidence_ids),
        warnings=warnings,
    )
    from app.evidence import provenance

    spec.source_note = provenance.source_note(
        evidence.resolve(spec.evidence_ids))
    return spec


def _nodes_from_evidence(evidence: EvidenceIndex,
                         request: DiagramRequest) -> list[DiagramNode]:
    nodes: list[DiagramNode] = []
    for order, item in enumerate(evidence.resolve(request.evidence_ids), start=1):
        nodes.append(DiagramNode(
            node_id=f"n{order}", label=item.label, sublabel=_sublabel(item),
            evidence_id=item.evidence_id, status=_status_of(item),
            at=_when(item),
            value=float(item.value) if isinstance(item.value, (int, float))
            else None,
            row=_matrix_axis(item, "impact"),
            column=_matrix_axis(item, "probability"),
        ))
    return nodes


def _matrix_axis(item: EvidenceItem, field: str) -> Optional[int]:
    raw = item.payload.get(field)
    return int(raw) if isinstance(raw, (int, float)) else None


def _sublabel(item: Optional[EvidenceItem]) -> str:
    if item is None:
        return ""
    if item.display and item.display != fmt.NOT_REPORTED:
        return item.display
    return item.owner or item.workstream or ""


def _status_of(item: Optional[EvidenceItem]) -> str:
    if item is None:
        return "none"
    if item.is_contested:
        return "warn"
    if item.severity in ("critical", "high"):
        return "bad"
    if item.status in ("completed",):
        return "good"
    if item.status in ("blocked", "at_risk"):
        return "bad"
    if item.status in ("not_started",):
        return "muted"
    return "none"


def _when(item: Optional[EvidenceItem]) -> Optional[str]:
    if item is None:
        return None
    for candidate in (item.due, item.as_of):
        if isinstance(candidate, (date, datetime)):
            return candidate.isoformat()[:10]
    for field in ("planned_date", "forecast_date", "actual_date", "due_date",
                  "required_date", "decision_deadline"):
        raw: Any = item.payload.get(field)
        if isinstance(raw, str) and len(raw) >= 10:
            return raw[:10]
    return None


def _diagram_alt(request: DiagramRequest, nodes: Sequence[DiagramNode]) -> str:
    return (f"{request.diagram_type.replace('_', ' ')} with {len(nodes)} "
            f"elements. {request.insight}").strip()
