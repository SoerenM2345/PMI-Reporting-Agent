"""Project a `Deliverable` into the preview payload the UI already reads.

This exists to keep one promise: **what the preview says is what the artifact
says.** The session stack used to plan a `ReportContent` for the preview and,
once generation moved to the planning engine, plan a `Deliverable` for the deck —
two independent plans, so a user could approve one document and receive another.
That is the failure the whole system is built to avoid, and it is worse here than
anywhere else because it is invisible: both artifacts look right on their own.

So the preview is a *projection*, never a second plan. Every field below is read
off the same `Deliverable` the renderers consume, and the shape matches what
`app/report/render/markdown.py::render_blocks` produced, so the frontend needs no
change.

The one field that has to survive the projection is `Cell.ref`. Flattening a
table to text loses cell identity, and without identity a click in the preview
cannot become "write 12-08-2026 into milestone M1's planned date" — which is what
makes an edit reach the *data model* rather than the stored text.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

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

log = logging.getLogger("pmi.deliverable.preview")


def payload(deliverable: Deliverable, *, stale: bool = False,
            stale_reason: str = "") -> dict:
    """The whole preview, in the shape the UI reads."""
    from app.renderers.markdown import to_markdown

    return {
        "version": deliverable.version,
        "stale": stale,
        "stale_reason": stale_reason,
        "audience": deliverable.audience_label,
        "title": deliverable.title,
        "governing_message": deliverable.governing_message,
        "planned_by": deliverable.planned_by,
        "markdown": to_markdown(deliverable),
        "sections": [_section(page) for page in _content_pages(deliverable)],
        "blocks": blocks(deliverable),
        "warnings": list(deliverable.warnings),
        "formats": _formats(deliverable),
    }


def _content_pages(deliverable: Deliverable) -> list[PageDesign]:
    """The pages a reader would call sections. A cover is furniture."""
    return [page for page in deliverable.pages if page.purpose != "cover"]


def _formats(deliverable: Deliverable) -> list[str]:
    from app.renderers import registry

    primary = registry.normalize(deliverable.primary_format)
    return [primary] + [f for f in registry.supported() if f != primary]


def _section(page: PageDesign) -> dict:
    return {
        "section_id": page.page_id,
        "label": page.subtitle or page.title,
        "headline": page.title,
        "origin": "user" if page.planned_by == "user" else "planner",
        "block_kinds": [element.role for element in page.elements],
        "empty_explanation": _empty_explanation(page),
        "composition": page.composition,
        "warnings": list(page.warnings),
    }


def _empty_explanation(page: PageDesign) -> str:
    """Why a page has nothing on it, in the user's terms.

    A page with no content is a real outcome — the topic was requested and
    nothing covers it — and saying so is the point. An empty page with no
    explanation is the defect.
    """
    if page.elements:
        return ""
    if page.warnings:
        return page.warnings[0]
    return ("Nothing in this project covers this topic, so there is nothing to "
            "show here yet.")


def blocks(deliverable: Deliverable) -> list[dict]:
    """Sections and their blocks, carrying each cell's identity."""
    return [
        {
            "section_id": page.page_id,
            "label": page.subtitle or page.title,
            "headline": page.title,
            "empty_explanation": _empty_explanation(page),
            "blocks": [_block(element, deliverable)
                       for element in page.elements],
            "source_note": page.source_note,
        }
        for page in _content_pages(deliverable)
    ]


def _block(element, deliverable: Deliverable) -> dict:
    base = {"kind": _kind(element), "block_id": element.element_id,
            "title": None, "authored_by": element.authored_by,
            "emphasis": element.emphasis}

    if isinstance(element, TextElement):
        return {**base, "text": element.text, "role": element.role}
    if isinstance(element, BulletsElement):
        return {**base, "items": [{"text": item, "emphasis": "none"}
                                  for item in element.items]}
    if isinstance(element, KpiRowElement):
        return {**base, "tiles": [
            {"label": tile.label, "value": tile.display or "Not Reported",
             "emphasis": tile.emphasis, "fact_key": tile.evidence_id,
             "note": tile.note}
            for tile in element.tiles]}
    if isinstance(element, ChartElement):
        spec = deliverable.specs.charts.get(element.spec_id)
        # The caption, never a bare builder name. `Chart: Workstream Progress`
        # over empty space was the old preview's worst moment.
        return {**base, "caption": (spec.caption if spec else element.caption),
                "chart_type": spec.chart_type if spec else "",
                "insight": spec.insight if spec else "",
                "series": [s.name for s in spec.series] if spec else []}
    if isinstance(element, DiagramElement):
        spec = deliverable.specs.diagrams.get(element.spec_id)
        return {**base, "caption": (spec.caption if spec else element.caption),
                "diagram_type": spec.diagram_type if spec else "",
                "nodes": [n.label for n in spec.nodes] if spec else []}
    if isinstance(element, TableElement):
        return _table(base, element, deliverable)
    if isinstance(element, ImageElement):
        return {**base, "alt": element.alt, "caption": element.caption}
    return base


def _kind(element) -> str:
    """The block kinds the existing UI switches on."""
    return {"headline": "prose", "kicker": "prose", "body": "prose",
            "callout": "prose", "quote": "prose", "footnote": "prose",
            "source_note": "prose", "kpi_row": "tiles"}.get(
                element.role, element.role)


def _table(base: dict, element: TableElement, deliverable: Deliverable) -> dict:
    spec = deliverable.specs.tables.get(element.spec_id)
    if spec is None:
        return {**base, "derived": True, "columns": [], "rows": [],
                "note": "This table could not be built."}
    return {
        **base,
        "derived": False,
        "note": spec.truncation_note(),
        "row_limit": spec.row_limit,
        "spec_id": spec.spec_id,
        "columns": [{"header": c.header, "kind": c.kind} for c in spec.columns],
        "rows": [
            [
                {
                    "text": cell.text,
                    # Only a cell naming one model field can be written back. A
                    # computed variance carries no ref and the UI must not
                    # offer to edit it.
                    "editable": bool(cell.ref and cell.ref.field),
                    "field": cell.ref.field if cell.ref else None,
                    "emphasis": cell.emphasis,
                }
                for cell in row
            ]
            for row in spec.rows
        ],
        "caption": spec.caption,
    }


# ------------------------------------------------------------------ editing
def find_cell(deliverable: Deliverable, block_id: str, row: int,
              column: int):
    """The `(spec, cell)` a preview edit refers to, or `(None, None)`.

    `block_id` is the *element* id, which is what the payload above exposes and
    what the UI sends back — so the lookup goes element -> spec -> cell rather
    than assuming the two ids are the same.
    """
    for page in deliverable.pages:
        for element in page.elements:
            if element.element_id != block_id or not isinstance(
                    element, TableElement):
                continue
            spec = deliverable.specs.tables.get(element.spec_id)
            if spec is None:
                return None, None
            if not (0 <= row < len(spec.rows)):
                return spec, None
            cells = spec.rows[row]
            if not (0 <= column < len(cells)):
                return spec, None
            return spec, cells[column]
    return None, None


def find_text(deliverable: Deliverable, block_id: str):
    """The `(page, element)` a prose edit refers to, or `(None, None)`."""
    for page in deliverable.pages:
        for element in page.elements:
            if element.element_id == block_id and isinstance(
                    element, (TextElement, BulletsElement)):
                return page, element
    return None, None


def element_text(element) -> str:
    if isinstance(element, BulletsElement):
        return "\n".join(element.items)
    return getattr(element, "text", "")
