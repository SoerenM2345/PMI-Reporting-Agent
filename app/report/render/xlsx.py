"""Render a `ReportContent` as the §13 workbook.

The workbook was the one format that did not read the approved content: it
walked `PMIDataModel` itself, so a figure the user corrected in the preview
appeared in the deck and not in the spreadsheet, and nothing in the system could
notice. Everything now comes from the same planned object, which is the only
reason "what the preview says is what the deck says" can extend to "…and what
the workbook says".

This draws; it does not decide. Which sheets exist, what they are called and
which rows they hold were settled by `planner._workbook_sections`. The
formatting — autofilter, frozen headers, conditional formats, DD-MM-YYYY dates,
currency and percent formats, readable widths — stays here, because none of it
changes when the content does. It is reused from `generators/xlsx_dashboard.py`
rather than copied.

Where a value is unknown it is written as "Not Reported", never as 0 or blank
(§7). A zero is a claim; a blank is a bug report. Neither is the truth.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import xlsxwriter

from app.report.content import ReportContent, Section
from app.report.format import NOT_REPORTED

log = logging.getLogger("pmi.render.xlsx")


def render(content: ReportContent, out_dir: Path, model=None) -> Path:
    """Write the workbook. `model` is unused — kept for renderer symmetry."""
    from app.generators import xlsx_dashboard as style

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (
        f"PMI_Dashboard_{content.audience.value}_{date.today().isoformat()}.xlsx"
    )

    workbook = xlsxwriter.Workbook(str(path))
    formats = style._formats(workbook)

    sheets = [s for s in content.sections if s.section_id.startswith("sheet.")]
    if not sheets:
        # Content planned before the workbook sections existed. An empty
        # workbook would be a silent lie about the data; say so on a sheet.
        _explain_empty(workbook, formats, content)
    for section in sheets:
        _render_sheet(workbook, formats, section, content, style)

    workbook.close()
    log.info("wrote %s (%d sheets)", path.name, max(len(sheets), 1))
    return path


def _render_sheet(workbook, formats, section: Section, content, style) -> None:
    if section.section_id == "sheet.executive":
        _dashboard_sheet(workbook, formats, section, content)
        return
    if section.section_id == "sheet.data_quality":
        _quality_sheet(workbook, formats, section, content)
        return

    table = next((b for b in section.blocks if b.kind == "table"), None)
    if table is None or not table.rows:
        return

    style._sheet(
        workbook, formats, section.label,
        [column.header for column in table.columns],
        [[_cell_value(cell, table.columns, index)
          for index, cell in enumerate(row)] for row in table.rows],
        percent_columns=_indexes(table.columns, "percent"),
        currency_columns=_indexes(table.columns, "currency"),
        negative_columns=[i for i, c in enumerate(table.columns)
                          if c.negative_is_bad],
        rag_column=next((i for i, c in enumerate(table.columns) if c.rag), None),
        flag_columns=_indexes(table.columns, "flag"),
    )


def _indexes(columns, kind: str) -> list[int]:
    return [index for index, column in enumerate(columns) if column.kind == kind]


def _cell_value(cell, columns, index: int):
    """The value `_sheet` should write.

    Numeric columns get a real number so the sheet sorts, charts and totals
    correctly; everything else gets the text the planner already formatted, so
    the workbook and the preview say the same words. "Not Reported" passes
    through untouched — `_sheet` styles it as the absence it is.
    """
    if cell.text == NOT_REPORTED:
        return NOT_REPORTED
    column = columns[index] if index < len(columns) else None
    if column is not None and column.kind in ("percent", "currency", "number"):
        number = _as_number(cell)
        if number is not None:
            return number
    return cell.text


def _as_number(cell) -> Optional[float]:
    if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        return float(cell.value)
    try:
        return float(str(cell.text).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- sheet 1
def _dashboard_sheet(workbook, formats, section: Section, content) -> None:
    """§13.1. Prose and figures rather than a table, so it is laid out by hand."""
    sheet = workbook.add_worksheet(section.label[:31])
    sheet.set_column(0, 0, 44)
    sheet.set_column(1, 4, 18)
    sheet.hide_gridlines(2)

    sheet.write(0, 0, content.title, formats["title"])
    sheet.write(1, 0, " · ".join(content.meta_line), formats["muted"])

    row = 3
    for block in section.blocks:
        if block.kind == "bullets":
            sheet.write(row, 0, block.title or "Summary", formats["header"])
            for item in block.items:
                row += 1
                sheet.write(row, 0, f"• {item.text}", formats["wrap"])
            row += 2
        elif block.kind == "tiles":
            sheet.write(row, 0, "Key figures", formats["header"])
            sheet.write(row, 1, "Value", formats["header"])
            for tile in block.tiles:
                row += 1
                value = (content.facts.display(tile.fact_key) if tile.fact_key
                         else (tile.value or NOT_REPORTED))
                sheet.write(row, 0, tile.label, formats["label"])
                _write_figure(sheet, row, 1, value, formats)
            row += 2


def _write_figure(sheet, row: int, column: int, value: str, formats) -> None:
    """A count writes as a number so the reader can total it; a status writes as
    text. Guessing wrong in either direction produces a cell that looks right and
    behaves wrong."""
    if value == NOT_REPORTED:
        sheet.write(row, column, NOT_REPORTED, formats["muted"])
        return
    try:
        sheet.write_number(row, column, float(value), formats["number"])
    except (TypeError, ValueError):
        sheet.write(row, column, value, formats["cell"])


# --------------------------------------------------------------- sheet 10
def _quality_sheet(workbook, formats, section: Section, content) -> None:
    """§13.10. Several stacked tables and lists on one sheet."""
    sheet = workbook.add_worksheet(section.label[:31])
    sheet.set_column(0, 0, 40)
    sheet.set_column(1, 6, 24)
    sheet.hide_gridlines(2)

    sheet.write(0, 0, "Data Quality", formats["title"])
    row = 1

    for block in section.blocks:
        if block.kind == "bullets":
            if block.title:
                sheet.write(row, 0, block.title, formats["label"])
                row += 2
            for item in block.items:
                sheet.write(row, 0, f"• {item.text}",
                            formats["warn"] if item.emphasis == "warn"
                            else formats["wrap"])
                row += 1
            row += 1

        elif block.kind == "table":
            sheet.write(row, 0, block.title or "", formats["header"])
            row += 1
            for column, header in enumerate(c.header for c in block.columns):
                sheet.write(row, column, header, formats["header"])
            for cells in block.rows:
                row += 1
                for column, cell in enumerate(cells):
                    sheet.write(row, column, cell.text,
                                formats.get(_style_for(cell.emphasis),
                                            formats["cell"]))
            row += 2


def _style_for(emphasis: str) -> str:
    return {"bad": "bad", "warn": "warn", "good": "good"}.get(emphasis, "cell")


def _explain_empty(workbook, formats, content) -> None:
    """Never return empty on failure — a workbook with no sheets at all is not a
    valid xlsx, and one with a blank sheet is a claim that there was no data."""
    sheet = workbook.add_worksheet("Data Quality")
    sheet.set_column(0, 0, 80)
    sheet.write(0, 0, content.title, formats["title"])
    sheet.write(2, 0,
                "This report was planned before the workbook sheets existed, so "
                "there is nothing to dump here. Re-plan the report and generate "
                "again.", formats["warn"])
