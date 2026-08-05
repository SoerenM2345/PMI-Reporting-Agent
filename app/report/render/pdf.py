"""PDF rendering via `fpdf2`.

Chosen over the alternatives for one reason: it is pure Python. WeasyPrint needs
cairo and pango, which turns a `pip install` into a system-package problem
inside a slim container; reportlab means hand-rolling layout anyway. fpdf2
handles text, tables and images with no native dependencies, which keeps
`docker compose up` a single step.

PDF matters here because it is the format that renders identically for a
recipient with no Office licence — the one artefact you can be sure a board
member can open.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fpdf import FPDF

from app.report.content import ReportContent, Section

log = logging.getLogger("pmi.render.pdf")

INK = (26, 26, 26)
MUTED = (117, 117, 117)
LINE = (228, 228, 228)
_COLOUR = {"bad": (198, 40, 40), "warn": (249, 168, 37),
           "good": (46, 125, 50), "muted": MUTED}


class _Report(FPDF):
    def __init__(self, footer_text: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._footer_text = footer_text
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self) -> None:
        if not self._footer_text:
            return
        self.set_y(-14)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 4, _ascii(self._footer_text), align="C")
        self.set_y(-9)
        self.cell(0, 4, f"Page {self.page_no()}", align="C")


def render(content: ReportContent, out_dir: Path) -> Path:
    pdf = _Report(content.footer)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, _ascii(content.title))

    if content.subtitle:
        _muted_line(pdf, content.subtitle, size=11)
    if content.meta_line:
        _muted_line(pdf, " · ".join(content.meta_line), size=8)
    pdf.ln(3)

    for section in content.narrative():
        pdf.add_page()
        _section(pdf, section, content)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"PMI_Report_{content.audience.value}_{date.today().isoformat()}.pdf"
    pdf.output(str(path))
    log.info("wrote %s (%d pages)", path.name, pdf.page_no())
    return path


def _section(pdf: FPDF, section: Section, content: ReportContent) -> None:
    if pdf.get_y() > 240:
        pdf.add_page()

    pdf.ln(3)
    pdf.set_draw_color(*LINE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 6, _ascii(section.headline))
    _muted_line(pdf, section.label, size=8)
    pdf.ln(1)

    rendered = False
    for block in section.blocks:
        if _block(pdf, block, content):
            rendered = True

    if not rendered and section.empty_explanation:
        _muted_line(pdf, section.empty_explanation, size=9, italic=True)


def _block(pdf: FPDF, block, content: ReportContent) -> bool:
    if block.kind == "prose":
        if block.title:
            _bold_line(pdf, block.title)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 5, _ascii(block.text))
        return True

    if block.kind == "bullets":
        if not block.items:
            return False
        if block.title:
            _bold_line(pdf, block.title)
        for item in block.items:
            pdf.set_x(pdf.l_margin)
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*_COLOUR.get(item.emphasis, INK))
            pdf.multi_cell(0, 5, _ascii(f"-  {item.text}"))
        pdf.set_text_color(*INK)
        return True

    if block.kind == "tiles":
        if not block.tiles:
            return False
        # Three across, matching the deck's grid. Row origin is tracked
        # explicitly: `cell` does not advance y, so reading get_y() per tile
        # would make each one drift a little further down the page.
        width = (pdf.w - pdf.l_margin - pdf.r_margin) / 3
        row_top = pdf.get_y()
        for index, tile in enumerate(block.tiles):
            if index and index % 3 == 0:
                row_top += 13
            value = (content.facts.display(tile.fact_key)
                     if tile.fact_key else (tile.value or "Not Reported"))
            x = pdf.l_margin + width * (index % 3)

            pdf.set_xy(x, row_top)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*MUTED)
            pdf.cell(width, 4, _ascii(tile.label))

            pdf.set_xy(x, row_top + 4)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*_COLOUR.get(tile.emphasis, INK))
            pdf.cell(width, 6, _ascii(value))

        pdf.set_xy(pdf.l_margin, row_top + 15)
        pdf.set_text_color(*INK)
        return True

    if block.kind == "table":
        return _table(pdf, block)

    if block.kind == "chart":
        caption = block.caption or block.builder.replace("_", " ").title()
        _muted_line(pdf, f"Chart: {caption} — see the deck.", size=9, italic=True)
        return True

    return False


def _table(pdf: FPDF, block) -> bool:
    if block.is_derived:
        entity = block.query.entity if block.query else "rows"
        _muted_line(pdf, f"Full {entity} listing — included in the Excel dashboard.",
                    size=9, italic=True)
        return True
    if not block.rows:
        return False

    if block.title:
        _bold_line(pdf, block.title)

    usable = pdf.w - pdf.l_margin - pdf.r_margin
    width = usable / max(len(block.columns), 1)

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*INK)
    for column in block.columns:
        pdf.cell(width, 5, _ascii(column.header)[:26], border="B")
    pdf.ln(5)

    limit = block.row_limit or len(block.rows)
    for row in block.rows[:limit]:
        if pdf.get_y() > 260:
            pdf.add_page()
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "", 7)
        for index in range(len(block.columns)):
            cell = row[index] if index < len(row) else None
            text = _ascii(cell.text) if cell else ""
            pdf.set_text_color(*_COLOUR.get(cell.emphasis if cell else "none", INK))
            # Truncated rather than wrapped: a status table that reflows into
            # ragged multi-line rows is harder to scan than one that elides.
            pdf.cell(width, 4.5, text[:26])
        pdf.ln(4.5)

    pdf.set_text_color(*INK)
    if block.note:
        _muted_line(pdf, block.note, size=8, italic=True)
    return True


def _bold_line(pdf: FPDF, text: str) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5, _ascii(text))


def _muted_line(pdf: FPDF, text: str, *, size: int, italic: bool = False) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "I" if italic else "", size)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.5, _ascii(text))
    pdf.set_text_color(*INK)


def _ascii(text: str) -> str:
    """The core PDF fonts are Latin-1 only.

    The report legitimately contains typographic characters — the ⚠ used to
    flag an unowned risk, curly quotes, en dashes. Passing those to a Latin-1
    font raises, so they are transliterated rather than dropped: "!" still reads
    as a warning, whereas a silently missing glyph would quietly delete the
    thing that made the row worth looking at.
    """
    replacements = {
        "⚠": "!", "—": "-", "–": "-", "•": "-", "“": '"', "”": '"',
        "‘": "'", "’": "'", "…": "...", "→": "->", "·": "-", "📊": "",
        "❗": "!", "≥": ">=", "≤": "<=",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode("latin-1", "replace").decode("latin-1")
