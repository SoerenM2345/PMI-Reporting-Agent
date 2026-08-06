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
            stale_reason: str = "", source_files: Optional[list[str]] = None,
            conflicts: Optional[list[dict]] = None) -> dict:
    """The whole preview, in the shape the UI reads."""
    from app.renderers.markdown import to_markdown

    from app.deliverable import workflow

    selected_format = workflow.normalize_format(deliverable.primary_format)
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
        "formats": list(workflow.FORMAT_LABELS),
        "selected_format": selected_format,
        "format_preview": format_preview(
            deliverable, selected_format or "powerpoint",
            source_files=source_files or [], conflicts=conflicts or []),
        "source_use_constraints": [item.model_dump(mode="json")
                                   for item in deliverable.source_use_constraints],
        "review_question": (
            f"Generate the {workflow.FORMAT_LABELS.get(selected_format or '', selected_format or 'file')} "
            "now with this content, or change the layout, text, titles, "
            "copywriting, language, or anything else?"
        ),
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
        "purpose": page.purpose,
        "is_divider": page.purpose == "divider",
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
            "purpose": page.purpose,
            "is_divider": page.purpose == "divider",
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
                "title": spec.title if spec else None,
                "subtitle": spec.subtitle if spec else "",
                "insight": spec.insight if spec else "",
                "categories": list(spec.categories) if spec else [],
                "series": [_chart_series(series) for series in spec.series]
                          if spec else [],
                "category_axis": spec.category_axis.model_dump(mode="json")
                                 if spec else {},
                "value_axis": spec.value_axis.model_dump(mode="json")
                              if spec else {},
                "legend": spec.legend if spec else "none",
                "data_labels": spec.data_labels if spec else "none",
                "annotations": [a.model_dump(mode="json")
                                for a in spec.annotations] if spec else [],
                "source_note": spec.source_note if spec else "",
                "intended_message": spec.insight if spec else ""}
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


def _chart_series(series) -> dict:
    return {
        "name": series.name,
        "unit": series.unit,
        "currency": series.currency,
        "period": series.period,
        "kind_override": series.kind_override,
        "points": [point.model_dump(mode="json") for point in series.points],
    }


def format_preview(deliverable: Deliverable, selected_format: str, *,
                   source_files: Optional[list[str]] = None,
                   conflicts: Optional[list[dict]] = None) -> dict:
    """A complete, format-aware review description from the stored plan."""
    pages = [_format_page(page, deliverable, selected_format)
             for page in deliverable.pages]
    if selected_format in ("pdf", "word"):
        pages = _document_furniture(
            pages, deliverable, source_files or [], conflicts or [])
    common = {
        "format": selected_format,
        "title": deliverable.title,
        "subtitle": deliverable.subtitle,
        "governing_message": deliverable.governing_message,
        "pages": pages,
    }
    if selected_format == "html":
        common["layout"] = {
            "header": "Branded masthead with report title, subtitle, audience and reporting period",
            "navigation": "Sticky contents navigation linking to each report section",
            "content": "Responsive section cards in the approved order, using each page composition",
            "tables": "Responsive tables with horizontal scrolling on narrow screens",
            "visuals": "Inline charts and diagrams generated from the approved specifications",
            "interactions": ["section navigation", "responsive layout", "source-note disclosure"],
            "responsive": "Multi-column compositions collapse to one column on small screens",
            "footer": "Report identity, source notes and generation metadata",
        }
    if selected_format == "chart":
        common["charts"] = [
            _block(element, deliverable)
            for page in deliverable.pages for element in page.elements
            if isinstance(element, ChartElement)
        ]
    return common


def _document_furniture(pages: list[dict], deliverable: Deliverable,
                        source_files: list[str], conflicts: list[dict]) -> list[dict]:
    """The TOC and methodology pages the Word/PDF renderers always add."""
    output = list(pages)
    content_pages = [page for page in pages if page["purpose"] != "cover"]
    if len(content_pages) >= 3:
        entries = [f"{page['title'] or page['page_id']} — planned page {index + 3}"
                   for index, page in enumerate(content_pages)]
        contents = {
            "number": 0, "label": "Page", "page_id": "document-contents",
            "purpose": "contents", "is_divider": False,
            "layout": "Table of contents", "composition": "single",
            "title": "Contents", "subtitle": "",
            "content": [{
                "kind": "bullets", "block_id": "document-contents.items",
                "title": None, "authored_by": "python", "emphasis": "none",
                "items": [{"text": entry, "emphasis": "none"}
                          for entry in entries],
            }],
            "speaker_notes": "", "source_note": "", "warnings": [],
        }
        cover_index = next((index for index, page in enumerate(output)
                            if page["purpose"] == "cover"), -1)
        output.insert(cover_index + 1, contents)

    methodology_items = list(source_files) or ["No files were read for this document."]
    for conflict in conflicts:
        values = "; ".join(f"{name} says {value}"
                           for name, value in conflict.get("values", {}).items())
        methodology_items.append(
            f"Unresolved: {conflict.get('entity_key', 'source disagreement')} "
            f"({conflict.get('field', 'value')}): {values}")
    methodology_items.extend(deliverable.notes)
    methodology_items.extend(deliverable.warnings[:15])
    output.append({
        "number": 0, "label": "Page", "page_id": "sources-and-methodology",
        "purpose": "appendix", "is_divider": False,
        "layout": "Sources and methodology", "composition": "single",
        "title": "Sources and methodology", "subtitle": "Sources read, unresolved disagreements, and limitations",
        "content": [{
            "kind": "bullets", "block_id": "sources-and-methodology.items",
            "title": None, "authored_by": "python", "emphasis": "none",
            "items": [{"text": item, "emphasis": "none"}
                      for item in methodology_items],
        }],
        "speaker_notes": "", "source_note": "", "warnings": [],
    })
    for index, page in enumerate(output, start=1):
        page["number"] = index
    return output


def _format_page(page: PageDesign, deliverable: Deliverable,
                 selected_format: str) -> dict:
    label = ("Slide" if selected_format == "powerpoint"
             else "Page" if selected_format in ("pdf", "word")
             else "Section")
    return {
        "number": page.index + 1,
        "label": label,
        "page_id": page.page_id,
        "purpose": page.purpose,
        "is_divider": page.purpose == "divider",
        "layout": page.layout_name or page.composition,
        "composition": page.composition,
        "title": page.title,
        "subtitle": page.subtitle,
        "content": [_block(element, deliverable) for element in page.elements],
        "speaker_notes": page.speaker_notes,
        "source_note": page.source_note,
        "warnings": list(page.warnings),
    }


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
        "note": spec.note(),
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
            for row in spec.displayed_rows
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
