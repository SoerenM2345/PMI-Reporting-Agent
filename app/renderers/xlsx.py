"""Render a `Deliverable` as an Excel workbook.

Each page becomes a sheet, with tables, bullets, and KPI tiles rendered in order.
The formatting — frozen headers, conditional formats, currency and percent formats,
readable widths — comes from the xlsx_dashboard module's style definitions.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import xlsxwriter

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
from app.renderers.common import RenderResult, MeasuredBox
from app.report.format import NOT_REPORTED

log = logging.getLogger("pmi.renderers.xlsx")


def render(deliverable: Deliverable, context: GenerationContext,
           out_dir: Path) -> RenderResult:
    """Render the deliverable as an Excel workbook."""
    from app.generators import xlsx_dashboard as style

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / naming.output_name(deliverable, context, "xlsx")

    workbook = xlsxwriter.Workbook(str(path))
    formats = style._formats(workbook)

    # Group pages by sheet (each page becomes a sheet)
    used_names: set[str] = set()
    for page in deliverable.pages:
        _render_sheet(workbook, formats, page, deliverable, context, used_names)

    workbook.close()
    log.info("rendered %s (%d sheets)", path.name, len(deliverable.pages) - 1)

    return RenderResult(path=path, page_count=len(deliverable.pages),
                        warnings=list(deliverable.warnings))


#: Excel forbids these in a sheet name, wherever they fall in the title.
_INVALID_SHEET_CHARS = str.maketrans({c: " " for c in "[]:*?/\\"})


def _sheet_name(title: str, used_names: set[str]) -> str:
    """A title that survives Excel's sheet-name rules and stays unique.

    A page titled "Financial Status: synergies and savings" crashes
    `xlsxwriter` outright — `:` alone is illegal, before truncation is even a
    concern. Two pages that only differ after character 31 would otherwise
    collide once cut down, which `xlsxwriter` also rejects.
    """
    cleaned = " ".join(title.translate(_INVALID_SHEET_CHARS).split()) or "Sheet"
    base = cleaned[:31]
    name = base
    suffix = 2
    while name in used_names:
        tail = f" ({suffix})"
        name = base[:31 - len(tail)] + tail
        suffix += 1
    used_names.add(name)
    return name


def _render_sheet(workbook, formats, page, deliverable: Deliverable,
                   context: GenerationContext = None,
                   used_names: Optional[set] = None) -> None:
    """Render one page as a worksheet."""
    sheet = workbook.add_worksheet(_sheet_name(page.title, used_names
                                               if used_names is not None else set()))
    sheet.set_column(0, 0, 44)
    sheet.set_column(1, 4, 18)
    sheet.hide_gridlines(2)

    row = [0]  # Mutable list to track current row

    # Page title
    if page.title:
        sheet.write(row[0], 0, page.title, formats["title"])
        row[0] += 2

    # Write document metadata on cover page
    if page.purpose == "cover":
        if context and context.company_names.as_phrase():
            sheet.write(row[0], 0, context.company_names.as_phrase(), formats["muted"])
            row[0] += 1
        if deliverable.subtitle:
            sheet.write(row[0], 0, deliverable.subtitle, formats["muted"])
            row[0] += 1
        if deliverable.governing_message:
            sheet.write(row[0], 0, deliverable.governing_message, formats["wrap"])
            row[0] += 2

    # Render elements on the page
    for element in page.elements:
        if isinstance(element, TextElement):
            _render_text(sheet, row, element, formats)
        elif isinstance(element, BulletsElement):
            _render_bullets(sheet, row, element, formats)
        elif isinstance(element, KpiRowElement):
            _render_kpi_row(sheet, row, element, deliverable, formats)
        elif isinstance(element, TableElement):
            _render_table(sheet, row, element, deliverable, formats)

    # Write source note if present
    if page.source_note:
        sheet.write(row[0], 0, page.source_note, formats.get("muted", formats["wrap"]))
        row[0] += 2


def _render_text(sheet, row: list[int], element: TextElement, formats) -> None:
    """Render a text element."""
    if element.text:
        style_key = element.role
        fmt = formats.get(style_key, formats["cell"])
        sheet.write(row[0], 0, element.text, fmt)
        row[0] += 2


def _render_bullets(sheet, row: list[int], element: BulletsElement, formats) -> None:
    """Render bullet points."""
    if element.items:
        if element.items:
            sheet.write(row[0], 0, "Summary", formats["header"])
            row[0] += 1
            for item in element.items:
                sheet.write(row[0], 0, f"• {item}", formats["wrap"])
                row[0] += 1
            row[0] += 1


def _render_kpi_row(sheet, row: list[int], element: KpiRowElement,
                     deliverable: Deliverable, formats) -> None:
    """Render KPI tiles as rows."""
    if element.tiles:
        sheet.write(row[0], 0, "Key Figures", formats["header"])
        sheet.write(row[0], 1, "Value", formats["header"])
        row[0] += 1

        for tile in element.tiles:
            sheet.write(row[0], 0, tile.label, formats["label"])
            value = tile.display or NOT_REPORTED
            _write_figure(sheet, row[0], 1, value, formats)
            row[0] += 1
        row[0] += 1


def _render_table(sheet, row: list[int], element: TableElement,
                   deliverable: Deliverable, formats) -> None:
    """Render a table element."""
    table_spec = deliverable.specs.tables.get(element.spec_id)
    if table_spec is None or not table_spec.rows:
        return

    from app.generators import xlsx_dashboard as style

    # Write table title if present
    if element.caption:
        sheet.write(row[0], 0, element.caption, formats["header"])
        row[0] += 1

    # Write column headers
    headers = [col.header for col in table_spec.columns]
    for col_idx, header in enumerate(headers):
        sheet.write(row[0], col_idx, header, formats["header"])
    row[0] += 1

    # Write data rows
    for table_row in table_spec.displayed_rows:
        for col_idx, cell in enumerate(table_row):
            col_spec = table_spec.columns[col_idx] if col_idx < len(table_spec.columns) else None
            cell_value = _get_cell_value(cell, col_spec)
            sheet.write(row[0], col_idx, cell_value, formats.get("cell", formats["wrap"]))
        row[0] += 1

    row[0] += 1


def _get_cell_value(cell, col_spec):
    """Extract the appropriate value for a cell based on column type."""
    if cell.text == NOT_REPORTED:
        return NOT_REPORTED

    if col_spec and col_spec.kind in ("percent", "currency", "number"):
        number = _as_number(cell)
        if number is not None:
            return number

    return cell.text


def _as_number(cell) -> Optional[float]:
    """Convert cell value to float."""
    if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        return float(cell.value)
    try:
        return float(str(cell.text).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _write_figure(sheet, row: int, column: int, value: str, formats) -> None:
    """Write a number or text figure to a cell."""
    if value == NOT_REPORTED:
        sheet.write(row, column, NOT_REPORTED, formats["muted"])
        return
    try:
        sheet.write_number(row, column, float(value), formats["number"])
    except (TypeError, ValueError):
        sheet.write(row, column, value, formats["cell"])
