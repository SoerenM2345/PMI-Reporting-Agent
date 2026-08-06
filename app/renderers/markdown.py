"""Render a `Deliverable` as Markdown — the editable draft and the chat preview.

Markdown is the one format a user *edits*, so this is deliberately lossless in
the direction that matters: every heading, figure and table cell the reader will
see in the deck appears here as text, because the draft is the promise and the
deck has to keep it.

Charts and diagrams cannot be Markdown, so they are represented by their
**caption and their insight** — the sentence the chart exists to show — rather
than by a `Chart: <name>` placeholder. That placeholder was the old system's most
visible failure: it told the reader a chart existed and showed them nothing.
Here the text says what the chart says, and the rendered formats carry the chart.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.context.schemas import GenerationContext
from app.deliverable.model import (
    BulletsElement,
    ChartElement,
    Deliverable,
    DiagramElement,
    ImageElement,
    KpiRowElement,
    PageDesign,
    TableElement,
    TextElement,
)
from app.renderers import naming
from app.renderers.common import MeasuredBox, RenderResult

log = logging.getLogger("pmi.renderers.markdown")


def render(deliverable: Deliverable, context: GenerationContext,
           out_dir: Path) -> RenderResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / naming.output_name(deliverable, context, "md")
    path.write_text(to_markdown(deliverable, context), encoding="utf-8")
    return RenderResult(
        path=path, page_count=len(deliverable.pages),
        element_boxes=[MeasuredBox(page_id=p.page_id, name="page",
                                   text=p.text_content())
                       for p in deliverable.pages],
        warnings=list(deliverable.warnings))


def to_markdown(deliverable: Deliverable,
                context: Optional[GenerationContext] = None) -> str:
    parts = [f"# {deliverable.title}"]
    if deliverable.subtitle:
        parts.append(f"*{deliverable.subtitle}*")

    meta = " · ".join(p for p in (deliverable.audience_label,
                                 context.reporting_period if context else "")
                      if p)
    if meta:
        parts.append(meta)
    if deliverable.governing_message:
        parts.append(f"> {deliverable.governing_message}")
    if deliverable.executive_takeaway:
        parts.append(deliverable.executive_takeaway)
    for page in deliverable.pages:
        if page.purpose == "cover":
            continue
        parts.append(section_markdown(page, deliverable))

    appendix = _appendix(deliverable, context)
    if appendix:
        parts.append(appendix)
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"


def section_markdown(page: PageDesign, deliverable: Deliverable) -> str:
    """One page as a Markdown section. This is what a `DraftSection` holds."""
    parts = [f"## {page.title or page.page_id}"]
    if page.subtitle:
        parts.append(f"*{page.subtitle}*")

    for element in page.elements:
        rendered = _element(element, deliverable)
        if rendered:
            parts.append(rendered)

    if page.source_note:
        parts.append(f"<sub>{page.source_note}</sub>")
    for warning in page.warnings:
        parts.append(f"<sub>⚠ {warning}</sub>")
    return "\n\n".join(parts)


def _element(element, deliverable: Deliverable) -> str:
    if isinstance(element, TextElement):
        if not element.text:
            return ""
        if element.role == "callout":
            return f"> **{element.text}**"
        if element.role == "quote":
            return f"> {element.text}"
        return element.text

    if isinstance(element, BulletsElement):
        return "\n".join(f"- {item}" for item in element.items)

    if isinstance(element, KpiRowElement):
        if not element.tiles:
            return ""
        header = " | ".join(_escape(t.label) for t in element.tiles)
        divider = " | ".join("---" for _ in element.tiles)
        values = " | ".join(f"**{_escape(t.display)}**" for t in element.tiles)
        return f"| {header} |\n| {divider} |\n| {values} |"

    if isinstance(element, TableElement):
        spec = deliverable.specs.tables.get(element.spec_id)
        return _table(spec) if spec is not None else ""

    if isinstance(element, ChartElement):
        spec = deliverable.specs.charts.get(element.spec_id)
        if spec is None:
            return ""
        # What the chart shows, in words — not a placeholder claiming a chart
        # the reader cannot see.
        lines = [f"**{spec.title}**" if spec.title else ""]
        if spec.insight:
            lines.append(spec.insight)
        lines.append(_chart_table(spec))
        if spec.caption:
            lines.append(f"<sub>{spec.caption}</sub>")
        return "\n\n".join(line for line in lines if line)

    if isinstance(element, DiagramElement):
        spec = deliverable.specs.diagrams.get(element.spec_id)
        if spec is None:
            return ""
        lines = [f"**{spec.title}**" if spec.title else ""]
        if spec.insight:
            lines.append(spec.insight)
        steps = " → ".join(node.label for node in spec.nodes if node.label)
        if steps:
            lines.append(steps)
        if spec.caption:
            lines.append(f"<sub>{spec.caption}</sub>")
        return "\n\n".join(line for line in lines if line)

    if isinstance(element, ImageElement) and element.alt:
        return f"![{_escape(element.alt)}]({element.image_ref})"
    return ""


def _table(spec) -> str:
    if not spec.columns or not spec.rows:
        return ""
    header = " | ".join(_escape(c.header) for c in spec.columns)
    divider = " | ".join(
        "---:" if c.kind in ("number", "currency", "percent") else "---"
        for c in spec.columns)
    lines = [f"| {header} |", f"| {divider} |"]
    for index, row in enumerate(spec.displayed_rows):
        cells = []
        for cell in row[:len(spec.columns)]:
            text = _escape(cell.text)
            cells.append(f"**{text}**" if index in spec.emphasis_rows else text)
        lines.append("| " + " | ".join(cells) + " |")
    out = "\n".join(lines)
    if spec.has_note:
        out += f"\n\n<sub>{spec.note()}</sub>"
    return out


def _chart_table(spec) -> str:
    """A chart's own data, so the draft states every figure the chart plots."""
    if not spec.series:
        return ""
    categories = spec.categories or [p.label for p in spec.all_points()]
    header = " | ".join(["", *(_escape(s.name) for s in spec.series)])
    divider = " | ".join(["---", *("---:" for _ in spec.series)])
    lines = [f"|{header} |", f"| {divider} |"]
    for index, category in enumerate(categories):
        cells = [_escape(str(category))]
        for series in spec.series:
            point = series.points[index] if index < len(series.points) else None
            cells.append(_escape(point.display) if point else "")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _appendix(deliverable: Deliverable,
              context: Optional[GenerationContext]) -> str:
    parts = ["## Sources and methodology"]
    files = context.evidence.projected_from_files if context else []
    if files:
        parts.append("<sub>Sources read: " + "; ".join(files) + "</sub>")
    conflicts = context.unresolved_critical_conflicts if context else []
    if conflicts:
        claims = "\n".join(
            f"- {c.entity_key} ({c.field}): "
            + "; ".join(f"{k} says {v}" for k, v in c.values.items())
            for c in conflicts)
        parts.append("**Unresolved disagreements between sources**\n"
                     "These figures are disputed; neither value should be "
                     f"treated as agreed.\n{claims}")
    if deliverable.notes:
        parts.append("**Limitations**\n"
                     + "\n".join(f"- {note}" for note in deliverable.notes))
    if deliverable.warnings:
        parts.append("**What the system could not do**\n"
                     + "\n".join(f"- {w}" for w in deliverable.warnings[:12]))
    return "\n\n".join(parts) if len(parts) > 1 else ""


def _escape(text: str) -> str:
    """A pipe in a value would otherwise split a table cell in two."""
    return str(text or "").replace("|", "\\|").replace("\n", " ")
