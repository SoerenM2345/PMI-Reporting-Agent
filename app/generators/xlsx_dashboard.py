"""Excel workbook styling (spec §13). XlsxWriter; the output is an editable .xlsx.

**What a sheet contains is decided in `app/report/planner.py`** and drawn by
`app/report/render/xlsx.py`. What lives here is the *look*: the palette, the cell
formats, and `_sheet`, which applies every §13 quality requirement — filters,
frozen headers, conditional formatting, consistent DD-MM-YYYY dates, currency
formats, readable widths — to one table.

That split is new and it is the point. This module used to walk `PMIDataModel`
itself, so the workbook was the one format that did not render the approved
content: a figure the user corrected in the preview reached the deck and not the
spreadsheet, and nothing in the system compared them.

Where a value is unknown it is written as "Not Reported", never as 0 or blank (§7). A
zero is a claim; a blank is a bug report. Neither is the truth.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.models.pmi import Audience, DataQualityReport, PMIDataModel
from app.report import brand
from app.report.format import NOT_REPORTED

log = logging.getLogger("pmi.xlsx")

# Shared RAG green with the charts, dashboard and UI (via `brand`); the pale
# fills below are cell backgrounds specific to a spreadsheet and stay local.
GREEN = brand.RAG_GREEN
LIGHT_GREEN = "#C8E6C9"
AMBER = "#FFF3CD"
RED = "#F8D7DA"
GREY = brand.RAG_GREY
DARK = "#1A1A1A"


def generate(
    model: PMIDataModel,
    audience: Audience,
    bullets: list[str],
    out_dir: Path,
    quality: Optional[DataQualityReport] = None,
) -> Path:
    """Build the workbook from a data model, for callers that have no plan.

    A thin shim: it plans the content and hands it to the renderer, so there is
    exactly one description of what a sheet contains. This module used to walk
    `PMIDataModel` itself, which made the workbook the one format that could
    contradict the preview the user had already approved — and nothing in the
    system could notice, because nothing compared them.
    """
    from app.report.planner import plan
    from app.report.render import xlsx as renderer

    content = plan(model, audience, bullets=bullets, quality=quality)
    return renderer.render(content, out_dir, model)


# ================================================================== plumbing
def _sheet(
    workbook, fmt, name: str, headers: list[str], rows: list[list],
    *,
    percent_columns: list[int] | None = None,
    currency_columns: list[int] | None = None,
    negative_columns: list[int] | None = None,
    rag_column: int | None = None,
    flag_columns: list[int] | None = None,
) -> None:
    """One sheet, with every §13 quality requirement applied."""
    sheet = workbook.add_worksheet(name[:31])
    percent_columns = percent_columns or []
    currency_columns = currency_columns or []
    negative_columns = negative_columns or []
    flag_columns = flag_columns or []

    for column, heading in enumerate(headers):
        width = max(12, min(len(heading) + 6, 46))
        if column == 1:
            width = 48  # the title column
        sheet.set_column(column, column, width)
        sheet.write(0, column, heading, fmt["header"])

    source_columns = {
        index for index, heading in enumerate(headers)
        if heading.strip().casefold() in {"source", "sources", "read from", "from"}
    }

    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            if value == NOT_REPORTED:
                sheet.write(r, c, NOT_REPORTED, fmt["muted"])
            elif c in percent_columns and isinstance(value, (int, float)):
                sheet.write_number(r, c, value / 100, fmt["percent"])
            elif c in currency_columns and isinstance(value, (int, float)):
                style = fmt["currency_bad"] if (c in negative_columns and value < 0) \
                    else fmt["currency"]
                sheet.write_number(r, c, value, style)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                sheet.write_number(r, c, value, fmt["number"])
            elif c in flag_columns and value == "YES":
                sheet.write(r, c, value, fmt["bad"])
            else:
                sheet.write(r, c, "" if value is None else str(value),
                            fmt["source"] if c in source_columns else fmt["cell"])

    last_row, last_column = max(len(rows), 1), len(headers) - 1

    # §13 quality requirements
    sheet.autofilter(0, 0, last_row, last_column)
    sheet.freeze_panes(1, 0)

    if rag_column is not None:
        for text, style in (
            ("At Risk", "amber"), ("Blocked", "bad"), ("Overdue", "bad"),
            ("Critical", "bad"), ("High", "bad"),
            ("Completed", "good"), ("In Progress", "good"), ("Low", "good"),
        ):
            sheet.conditional_format(1, rag_column, last_row, rag_column, {
                "type": "text", "criteria": "containing", "value": text,
                "format": fmt[style],
            })

    for column in negative_columns:
        sheet.conditional_format(1, column, last_row, column, {
            "type": "cell", "criteria": "<", "value": 0, "format": fmt["bad"],
        })


def _formats(workbook) -> dict:
    return {
        "title": workbook.add_format({"bold": True, "font_size": 18,
                                      "font_color": DARK}),
        "header": workbook.add_format({
            "bold": True, "bg_color": GREEN, "font_color": "white",
            "border": 1, "text_wrap": True, "valign": "vcenter",
        }),
        "cell": workbook.add_format({"border": 1, "valign": "top",
                                     "text_wrap": True}),
        "wrap": workbook.add_format({"text_wrap": True, "valign": "top"}),
        "label": workbook.add_format({"bold": True}),
        "muted": workbook.add_format({"font_color": GREY, "italic": True,
                                      "border": 1}),
        "source": workbook.add_format({"font_color": "#A6A6A6",
                                       "font_size": 7, "italic": True,
                                       "border": 1, "valign": "top",
                                       "text_wrap": True}),
        "number": workbook.add_format({"border": 1, "num_format": "#,##0.##"}),
        # §13: "Consistent date formats" — DD-MM-YYYY, per §7.
        "date": workbook.add_format({"border": 1, "num_format": "dd-mm-yyyy"}),
        "percent": workbook.add_format({"border": 1, "num_format": "0%"}),
        "currency": workbook.add_format({"border": 1, "num_format": "#,##0"}),
        "currency_bad": workbook.add_format({
            "border": 1, "num_format": "#,##0", "bg_color": RED, "font_color": "#7F1D1D",
        }),
        "good": workbook.add_format({"bg_color": LIGHT_GREEN, "border": 1}),
        "amber": workbook.add_format({"bg_color": AMBER, "border": 1}),
        "warn": workbook.add_format({"bg_color": AMBER, "border": 1,
                                     "text_wrap": True, "valign": "top"}),
        "bad": workbook.add_format({"bg_color": RED, "border": 1,
                                    "text_wrap": True, "valign": "top"}),
    }
