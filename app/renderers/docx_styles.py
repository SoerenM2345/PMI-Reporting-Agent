"""Define the Word styles the renderer uses, from the brand system.

A `.docx` template would be the natural home for these, but shipping a second
binary asset means it drifts from the PowerPoint master with nothing to catch it.
Defining them here means Word, PowerPoint, HTML and PDF all read the same
measured tokens.

The fiddly parts, both of which fail silently if skipped:

* **A font has to be set three times.** `w:ascii` alone leaves East-Asian and
  complex-script runs on Word's default, so a document that looks right in
  English changes typeface the moment it contains a curly quote Word decides is
  "complex". `_font` sets all three.
* **`keep_with_next` on headings and captions is not cosmetic.** Without it Word
  will happily leave a heading as the last line of a page, or a figure caption
  orphaned from its figure on the next.
"""
from __future__ import annotations

import logging
from typing import Optional

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.templates.brand_system import BrandSystem

log = logging.getLogger("pmi.renderers.docx_styles")

#: Style names this module guarantees exist after `install`.
TITLE = "PMI Title"
SUBTITLE = "PMI Subtitle"
GOVERNING = "PMI Governing"
H1 = "PMI Heading 1"
H2 = "PMI Heading 2"
H3 = "PMI Heading 3"
BODY = "PMI Body"
BULLET = "PMI Bullet"
CAPTION = "PMI Caption"
CALLOUT = "PMI Callout"
QUOTE = "PMI Quote"
TABLE_HEADER = "PMI Table Header"
TABLE_BODY = "PMI Table Body"
SOURCE_NOTE = "PMI Source Note"
KPI_VALUE = "PMI KPI Value"
KPI_LABEL = "PMI KPI Label"
META = "PMI Meta"


def install(document, brand: BrandSystem) -> None:
    """Define every style the renderer references. Idempotent."""
    font = brand.font_minor or "Aptos"

    _paragraph(document, TITLE, font, brand.font("cover").size_pt, bold=True,
               color=brand.color("primary"), space_after=6, keep_with_next=True)
    _paragraph(document, SUBTITLE, font, brand.font("subtitle").size_pt,
               color=brand.color("muted"), space_after=18)
    _paragraph(document, META, font, brand.font("caption").size_pt,
               color=brand.color("muted"), space_after=4)
    _paragraph(document, GOVERNING, font, brand.font("h1").size_pt, bold=True,
               color=brand.color("deep"), space_before=12, space_after=12,
               left_indent=14, border_left=brand.color("emphasis"))

    _paragraph(document, H1, font, brand.font("h1").size_pt, bold=True,
               color=brand.color("text"), space_before=18, space_after=6,
               keep_with_next=True, outline_level=0)
    _paragraph(document, H2, font, brand.font("h2").size_pt, bold=True,
               color=brand.color("text"), space_before=14, space_after=4,
               keep_with_next=True, outline_level=1)
    _paragraph(document, H3, font, brand.font("h3").size_pt, bold=True,
               color=brand.color("muted"), space_before=10, space_after=4,
               keep_with_next=True, outline_level=2)

    _paragraph(document, BODY, font, brand.font("body").size_pt,
               color=brand.color("text"), space_after=8, line_spacing=1.15)
    _paragraph(document, BULLET, font, brand.font("body").size_pt,
               color=brand.color("text"), space_after=4, left_indent=18)
    _paragraph(document, CAPTION, font, brand.font("caption").size_pt,
               color=brand.color("muted"), italic=True, space_before=4,
               space_after=10)
    _paragraph(document, CALLOUT, font, brand.font("small").size_pt,
               color=brand.color("text"), space_before=8, space_after=10,
               left_indent=14, border_left=brand.color("rag_amber"),
               shading=brand.color("surface_alt"))
    _paragraph(document, QUOTE, font, brand.font("display").size_pt * 0.6,
               bold=True, color=brand.color("deep"), space_before=14,
               space_after=14, left_indent=14,
               border_left=brand.color("emphasis"))

    _paragraph(document, TABLE_HEADER, font, brand.font("small").size_pt,
               bold=True, color=brand.color("text_inverse"), space_after=0)
    _paragraph(document, TABLE_BODY, font, brand.font("small").size_pt,
               color=brand.color("text"), space_after=0)
    _paragraph(document, SOURCE_NOTE, font, 6.0,
               color="#A6A6A6", italic=True, space_before=3,
               space_after=8)
    _paragraph(document, KPI_VALUE, font, brand.font("kpi").size_pt * 0.6,
               bold=True, color=brand.color("primary"), space_after=0)
    _paragraph(document, KPI_LABEL, font, brand.font("label").size_pt,
               color=brand.color("muted"), space_after=0)

    _set_default_font(document, font, brand)


def _paragraph(document, name: str, font: str, size_pt: float, *,
               bold: bool = False, italic: bool = False,
               color: str = "#222222", space_before: float = 0,
               space_after: float = 0, line_spacing: Optional[float] = None,
               left_indent: float = 0, keep_with_next: bool = False,
               border_left: Optional[str] = None,
               shading: Optional[str] = None,
               outline_level: Optional[int] = None):
    from docx.enum.style import WD_STYLE_TYPE

    styles = document.styles
    try:
        style = styles[name]
    except KeyError:
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)

    style.font.name = font
    style.font.size = Pt(size_pt)
    style.font.bold = bold
    style.font.italic = italic
    style.font.color.rgb = _rgb(color)
    _font(style.element, font)

    fmt = style.paragraph_format
    fmt.space_before = Pt(space_before)
    fmt.space_after = Pt(space_after)
    if line_spacing is not None:
        fmt.line_spacing = line_spacing
    if left_indent:
        fmt.left_indent = Pt(left_indent)
    fmt.keep_with_next = keep_with_next
    fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT

    if border_left:
        _border_left(style.element, border_left)
    if shading:
        _shading(style.element, shading)
    if outline_level is not None:
        # Outline level is what a TOC field collects. Without it, a real
        # `TOC` field finds nothing and the document opens with an empty
        # contents page.
        _outline_level(style.element, outline_level)
    return style


def _font(element, font: str) -> None:
    """Set ascii, hAnsi, eastAsia and cs, so no run escapes the typeface."""
    rpr = element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attribute), font)


def _border_left(element, color: str) -> None:
    ppr = element.get_or_add_pPr()
    borders = ppr.makeelement(qn("w:pBdr"), {})
    left = borders.makeelement(qn("w:left"), {})
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")             # eighths of a point
    left.set(qn("w:space"), "6")
    left.set(qn("w:color"), color.lstrip("#"))
    borders.append(left)
    ppr.append(borders)


def _shading(element, color: str) -> None:
    ppr = element.get_or_add_pPr()
    shading = ppr.makeelement(qn("w:shd"), {})
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), color.lstrip("#"))
    ppr.append(shading)


def _outline_level(element, level: int) -> None:
    ppr = element.get_or_add_pPr()
    outline = ppr.makeelement(qn("w:outlineLvl"), {})
    outline.set(qn("w:val"), str(level))
    ppr.append(outline)


def _set_default_font(document, font: str, brand: BrandSystem) -> None:
    """Make the brand font the document default, so stray runs inherit it."""
    try:
        normal = document.styles["Normal"]
    except KeyError:
        return
    normal.font.name = font
    normal.font.size = Pt(brand.font("body").size_pt)
    _font(normal.element, font)


def shade_cell(cell, color: str) -> None:
    """Fill a table cell. The template defines no table styles to inherit."""
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.makeelement(qn("w:shd"), {})
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), color.lstrip("#"))
    properties.append(shading)


def repeat_header_row(row) -> None:
    """Mark a row as a header so it repeats on every page the table spans."""
    properties = row._tr.get_or_add_trPr()
    header = properties.makeelement(qn("w:tblHeader"), {})
    header.set(qn("w:val"), "true")
    properties.append(header)


def cannot_split(row) -> None:
    """Keep a row's cells on one page rather than breaking mid-row."""
    properties = row._tr.get_or_add_trPr()
    properties.append(properties.makeelement(qn("w:cantSplit"), {}))


def _rgb(color: str) -> RGBColor:
    value = color.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


rgb = _rgb
