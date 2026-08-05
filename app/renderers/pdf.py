"""Render a `Deliverable` as a designed PDF, on ReportLab platypus.

What this replaces was fpdf2 with the Helvetica core fonts, table cells
truncated to 26 characters with no wrapping, page breaks decided by
`if get_y() > 240`, an `_ascii()` pass that transliterated ⚠ to `!` because the
core fonts are Latin-1 — and, where a chart should have been, the sentence
`Chart: Workstream Progress — see the deck.`

Platypus was chosen over a headless browser or WeasyPrint because this image is
deliberately slim and neither cairo/pango nor Chromium is present, and over
staying on fpdf2 because a designed report needs tables that split across pages
with repeated headers, figures kept with their captions, a two-pass table of
contents and exact text measurement — all of which platypus ships and all of
which would otherwise be several hundred lines of hand-written flowable
framework.

Two things worth knowing:

* **Fonts.** Aptos is a Microsoft font and is usually absent from a Linux build
  host. The renderer looks for it, falls back to the `DejaVuSans` that ships
  inside matplotlib (guaranteed present, since matplotlib is a dependency), and
  **records a warning naming the substitution.** Full Unicode either way, so the
  transliteration hack is gone.
* **`multiBuild`, not `build`.** A table of contents needs the page numbers from
  a first pass to lay out the second.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

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
from app.templates.brand_system import BrandSystem
from app.visualizations import charts as chart_render
from app.visualizations import diagrams as diagram_render

log = logging.getLogger("pmi.renderers.pdf")

MARGIN = 0.85 * inch
FOOTER_HEIGHT = 0.55 * inch
FIGURE_WIDTH = 6.0 * inch

_REGISTERED: dict[str, str] = {}


# ==================================================================== fonts
def register_fonts(brand: BrandSystem) -> tuple[str, str, list[str]]:
    """`(regular, bold, warnings)`. Never Helvetica-core-only again.

    Registration is cached per process, but the **warning is not**: which font a
    document was typeset in is a property of that document, and a reader of the
    second PDF of the day is no less entitled to know it was not the brand's.
    """
    wanted = brand.font_minor or "Aptos"

    if wanted in _REGISTERED:
        regular = _REGISTERED[wanted]
        return regular, _REGISTERED.get(f"{wanted}-Bold", regular), \
            _substitution_warning(wanted, regular)

    warnings: list[str] = []
    for regular, bold in _font_candidates(wanted):
        try:
            pdfmetrics.registerFont(TTFont(regular.stem, str(regular)))
            bold_name = regular.stem
            if bold is not None and bold.is_file():
                pdfmetrics.registerFont(TTFont(bold.stem, str(bold)))
                bold_name = bold.stem
            pdfmetrics.registerFontFamily(regular.stem, normal=regular.stem,
                                          bold=bold_name, italic=regular.stem,
                                          boldItalic=bold_name)
            _REGISTERED[wanted] = regular.stem
            _REGISTERED[f"{wanted}-Bold"] = bold_name
            return (regular.stem, bold_name,
                    warnings + _substitution_warning(wanted, regular.stem))
        except Exception as exc:                               # noqa: BLE001
            log.debug("could not register %s (%s)", regular, exc)

    warnings.append("No embeddable font was found; the PDF falls back to a core "
                    "font and non-Latin characters may not render.")
    return "Helvetica", "Helvetica-Bold", warnings


def _substitution_warning(wanted: str, actual: str) -> list[str]:
    if wanted.casefold().replace(" ", "") in actual.casefold().replace(" ", ""):
        return []
    return [f"{wanted} is not installed on this machine, so the PDF is typeset "
            f"in {actual} instead. The deck and the Word document still request "
            f"{wanted} and will use it on a reader's machine."]


def _font_candidates(wanted: str) -> list[tuple[Path, Optional[Path]]]:
    """The brand font where installed, then matplotlib's bundled DejaVuSans."""
    candidates: list[tuple[Path, Optional[Path]]] = []
    directories = [Path("/System/Library/Fonts"), Path("/Library/Fonts"),
                   Path.home() / "Library/Fonts",
                   Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                   Path.home() / ".fonts"]
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob(f"{wanted}*.ttf")):
            if "bold" in path.stem.casefold() or "italic" in path.stem.casefold():
                continue
            bold = next(iter(sorted(path.parent.glob(f"{wanted}*Bold*.ttf"))), None)
            candidates.append((path, bold))

    try:
        import matplotlib

        bundled = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
        regular = bundled / "DejaVuSans.ttf"
        if regular.is_file():
            candidates.append((regular, bundled / "DejaVuSans-Bold.ttf"))
    except Exception:                                          # noqa: BLE001
        pass
    return candidates


# ================================================================ rendering
def render(deliverable: Deliverable, context: GenerationContext,
           out_dir: Path) -> RenderResult:
    brand: BrandSystem = context.brand_system or _fallback_brand()
    regular, bold, warnings = register_fonts(brand)
    sheet = _styles(brand, regular, bold)

    out_dir.mkdir(parents=True, exist_ok=True)
    assets = out_dir / "assets"
    path = out_dir / naming.output_name(deliverable, context, "pdf")

    document = _Document(str(path), deliverable=deliverable, context=context,
                        brand=brand, font=regular)
    story: list = []
    boxes: list[MeasuredBox] = []
    figure_number = [0]

    _cover(story, deliverable, context, brand, sheet)
    _contents(story, deliverable, sheet)

    planned_pages = [page for page in deliverable.pages
                     if page.purpose != "cover"]
    for index, page in enumerate(planned_pages):
        if index:
            story.append(PageBreak())
        boxes.extend(_section(story, page, deliverable, brand, sheet, assets,
                              figure_number, regular))

    _appendix(story, deliverable, context, sheet)

    # Two passes: the contents needs page numbers the first pass produces.
    document.multiBuild(story)
    log.info("rendered %s (%d pages)", path.name, document.page)

    return RenderResult(path=path, page_count=document.page,
                        element_boxes=boxes,
                        warnings=list(deliverable.warnings) + warnings)


def _fallback_brand() -> BrandSystem:
    from app.templates import template_registry

    return template_registry.default().brand


class _Document(BaseDocTemplate):
    """Frames matching the deck's grid, and a footer drawn on every page.

    A reader who has the deck and the PDF should recognise them as one document,
    which means the text column has to sit where the deck's content area does.
    """

    def __init__(self, filename: str, *, deliverable: Deliverable,
                 context: GenerationContext, brand: BrandSystem,
                 font: str) -> None:
        super().__init__(filename, pagesize=A4, leftMargin=MARGIN,
                         rightMargin=MARGIN, topMargin=MARGIN,
                         bottomMargin=MARGIN + FOOTER_HEIGHT,
                         title=deliverable.title,
                         author="Deloitte", subject=deliverable.governing_message)
        self._deliverable = deliverable
        self._context = context
        self._brand = brand
        self._font = font

        width = A4[0] - 2 * MARGIN
        height = A4[1] - 2 * MARGIN - FOOTER_HEIGHT
        content = Frame(MARGIN, MARGIN + FOOTER_HEIGHT, width, height,
                        id="content", showBoundary=0)
        cover = Frame(MARGIN, MARGIN + FOOTER_HEIGHT, width, height, id="cover",
                      showBoundary=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover], onPage=self._cover_furniture),
            PageTemplate(id="content", frames=[content],
                         onPage=self._page_furniture),
        ])

    def _cover_furniture(self, canvas, _document) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(self._brand.color("primary")))
        canvas.rect(0, A4[1] - 0.32 * inch, A4[0], 0.32 * inch, stroke=0, fill=1)
        canvas.restoreState()

    def _page_furniture(self, canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(self._brand.color("primary")))
        canvas.setLineWidth(1.4)
        canvas.line(MARGIN, A4[1] - MARGIN + 6, A4[0] - MARGIN,
                    A4[1] - MARGIN + 6)

        canvas.setFont(self._font, 7.5)
        canvas.setFillColor(colors.HexColor(self._brand.color("muted")))
        left = "  |  ".join(part for part in (
            self._context.display_name(), self._context.reporting_period,
            self._deliverable.audience_label) if part)
        canvas.drawString(MARGIN, MARGIN + 0.18 * inch, left[:110])
        canvas.drawRightString(A4[0] - MARGIN, MARGIN + 0.18 * inch,
                               f"Page {document.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        """Feed headings to the table of contents."""
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        level = {"PMIHeading1": 0, "PMIHeading2": 1}.get(style)
        if level is None:
            return
        self.notify("TOCEntry", (level, flowable.getPlainText(), self.page))


# =================================================================== styles
def _styles(brand: BrandSystem, regular: str, bold: str) -> dict:
    def style(name: str, size: float, *, colour: str = "text",
              leading_ratio: float = 1.35, space_before: float = 0,
              space_after: float = 6, font: Optional[str] = None,
              left_indent: float = 0, alignment: int = TA_LEFT,
              italic: bool = False, border: Optional[str] = None,
              background: Optional[str] = None) -> ParagraphStyle:
        return ParagraphStyle(
            name, fontName=font or regular, fontSize=size,
            leading=size * leading_ratio,
            textColor=colors.HexColor(brand.color(colour)),
            spaceBefore=space_before, spaceAfter=space_after,
            leftIndent=left_indent, alignment=alignment,
            borderColor=colors.HexColor(brand.color(border)) if border else None,
            borderWidth=2 if border else 0,
            borderPadding=(0, 0, 0, 8) if border else 0,
            backColor=colors.HexColor(brand.color(background))
            if background else None,
        )

    return {
        "title": style("PMITitle", brand.font("cover").size_pt, colour="primary",
                       font=bold, space_after=8, leading_ratio=1.15),
        "subtitle": style("PMISubtitle", brand.font("subtitle").size_pt,
                          colour="muted", space_after=16),
        "meta": style("PMIMeta", brand.font("caption").size_pt, colour="muted",
                      space_after=3),
        "governing": style("PMIGoverning", brand.font("h1").size_pt,
                           colour="deep", font=bold, space_before=14,
                           space_after=12, left_indent=10, border="emphasis"),
        "h1": style("PMIHeading1", brand.font("h1").size_pt, font=bold,
                    space_before=16, space_after=6, leading_ratio=1.2),
        "h2": style("PMIHeading2", brand.font("h2").size_pt, font=bold,
                    space_before=12, space_after=5),
        "h3": style("PMIHeading3", brand.font("h3").size_pt, colour="muted",
                    font=bold, space_before=8, space_after=4),
        "body": style("PMIBody", brand.font("body").size_pt, space_after=7),
        "bullet": style("PMIBullet", brand.font("body").size_pt, space_after=4,
                        left_indent=12),
        "caption": style("PMICaption", brand.font("caption").size_pt,
                         colour="muted", italic=True, space_before=4,
                         space_after=10),
        "callout": style("PMICallout", brand.font("small").size_pt,
                         space_before=8, space_after=10, left_indent=10,
                         border="rag_amber", background="surface_alt"),
        "quote": style("PMIQuote", brand.font("h1").size_pt * 1.15,
                       colour="deep", font=bold, space_before=16,
                       space_after=16, left_indent=10, border="emphasis",
                       leading_ratio=1.2),
        "source": style("PMISource", 6.0, colour="#A6A6A6",
                        italic=True, space_before=3, space_after=12),
        "cell": style("PMICell", brand.font("small").size_pt, space_after=0,
                      leading_ratio=1.2),
        "cell_head": style("PMICellHead", brand.font("small").size_pt,
                           colour="text_inverse", font=bold, space_after=0,
                           leading_ratio=1.2),
        "cell_num": style("PMICellNum", brand.font("small").size_pt,
                          space_after=0, alignment=TA_RIGHT, leading_ratio=1.2),
        "kpi_value": style("PMIKpiValue", brand.font("kpi").size_pt * 0.55,
                           colour="primary", font=bold, space_after=0,
                           leading_ratio=1.1),
        "kpi_label": style("PMIKpiLabel", brand.font("label").size_pt,
                           colour="muted", space_after=0),
        "toc1": ParagraphStyle("PMIToc1", fontName=regular,
                               fontSize=brand.font("body").size_pt,
                               leading=brand.font("body").size_pt * 1.5,
                               textColor=colors.HexColor(brand.color("text"))),
        "toc2": ParagraphStyle("PMIToc2", fontName=regular,
                               fontSize=brand.font("small").size_pt,
                               leading=brand.font("small").size_pt * 1.5,
                               leftIndent=14,
                               textColor=colors.HexColor(brand.color("muted"))),
    }


# ==================================================================== story
def _cover(story: list, deliverable: Deliverable, context: GenerationContext,
           brand: BrandSystem, sheet: dict) -> None:
    if brand.logo_png_b64:
        import base64
        import io

        try:
            logo = Image(io.BytesIO(base64.b64decode(brand.logo_png_b64)),
                         width=1.75 * inch, height=0.33 * inch)
            logo.hAlign = "RIGHT"
            story.append(logo)
        except Exception:                                      # noqa: BLE001
            pass
    story.append(NextPageTemplate("content"))
    story.append(Spacer(1, 1.25 * inch))
    story.append(Paragraph(_x(deliverable.title), sheet["title"]))
    if deliverable.subtitle:
        story.append(Paragraph(_x(deliverable.subtitle), sheet["subtitle"]))
    for line in (deliverable.audience_label, context.reporting_period,
                 f"Prepared {deliverable.created_at[:10]}"):
        if line:
            story.append(Paragraph(_x(line), sheet["meta"]))
    if deliverable.governing_message:
        story.append(Paragraph(_x(deliverable.governing_message),
                               sheet["governing"]))
    if deliverable.executive_takeaway:
        story.append(Paragraph(_x(deliverable.executive_takeaway), sheet["body"]))
    story.append(PageBreak())


def _contents(story: list, deliverable: Deliverable, sheet: dict) -> None:
    if len([p for p in deliverable.pages if p.purpose != "cover"]) < 3:
        return
    story.append(Paragraph("Contents", sheet["h1"]))
    toc = TableOfContents()
    toc.levelStyles = [sheet["toc1"], sheet["toc2"]]
    story.append(toc)
    story.append(PageBreak())


def _section(story: list, page: PageDesign, deliverable: Deliverable,
             brand: BrandSystem, sheet: dict, assets: Path,
             figure_number: list[int], font: str) -> list[MeasuredBox]:
    boxes: list[MeasuredBox] = []

    if page.purpose == "divider":
        story.append(Paragraph(_x(page.title), sheet["quote"]))
        return boxes

    story.append(Paragraph(_x(page.title), sheet["h1"]))
    if page.subtitle:
        story.append(Paragraph(_x(page.subtitle), sheet["h3"]))

    for element in page.elements:
        if isinstance(element, TextElement):
            if not element.text:
                continue
            key = {"callout": "callout", "quote": "quote"}.get(element.role, "body")
            story.append(Paragraph(_x(element.text), sheet[key]))
            boxes.append(MeasuredBox(page_id=page.page_id, name=element.role,
                                     text=element.text))

        elif isinstance(element, BulletsElement):
            for item in element.items:
                story.append(Paragraph(f"&bull;&nbsp;&nbsp;{_x(item)}",
                                       sheet["bullet"]))
            if element.items:
                boxes.append(MeasuredBox(page_id=page.page_id, name="bullets",
                                         text=" ".join(element.items)))

        elif isinstance(element, KpiRowElement):
            table = _kpi_table(element, brand, sheet)
            if table is not None:
                story.append(table)
                boxes.append(MeasuredBox(page_id=page.page_id, name="kpi_row"))

        elif isinstance(element, ChartElement):
            spec = deliverable.specs.charts.get(element.spec_id)
            if spec is not None:
                path = chart_render.to_png(spec, brand, assets,
                                           size_in=(9.0, 4.6))
                story.append(_figure(path, "", figure_number, sheet))
                boxes.append(MeasuredBox(page_id=page.page_id, name="chart",
                                         text=spec.caption))

        elif isinstance(element, DiagramElement):
            spec = deliverable.specs.diagrams.get(element.spec_id)
            if spec is not None:
                path = diagram_render.to_png(spec, brand, assets,
                                             size_in=(9.0, 3.8))
                story.append(_figure(path, "", figure_number, sheet))
                boxes.append(MeasuredBox(page_id=page.page_id, name="diagram",
                                         text=spec.caption))

        elif isinstance(element, TableElement):
            spec = deliverable.specs.tables.get(element.spec_id)
            if spec is not None:
                story.extend(_table(spec, brand, sheet))
                boxes.append(MeasuredBox(page_id=page.page_id, name="table",
                                         text=spec.caption))

        elif isinstance(element, ImageElement) and element.image_ref:
            try:
                story.append(_scaled(Path(element.image_ref)))
            except Exception:                                  # noqa: BLE001
                pass

    if page.source_note:
        story.append(Paragraph(_x(page.source_note), sheet["source"]))
    story.append(Spacer(1, 0.12 * inch))
    return boxes


def _figure(path: Path, caption: str, figure_number: list[int], sheet: dict, *,
            editable: bool = False) -> KeepTogether:
    """A figure and its caption, which platypus will not separate."""
    if not caption and not editable:
        return KeepTogether([_scaled(path)])
    figure_number[0] += 1
    text = caption
    if editable:
        text = (text.rstrip(".") + ". The editable version of this chart is in "
                                   "the accompanying presentation.")
    return KeepTogether([
        _scaled(path),
        Paragraph(f"Figure {figure_number[0]}. {_x(text)}", sheet["caption"]),
    ])


def _scaled(path: Path) -> Image:
    """Fit the frame while preserving the aspect ratio."""
    from PIL import Image as PILImage

    with PILImage.open(path) as source:
        width, height = source.size
    scale = FIGURE_WIDTH / width
    return Image(str(path), width=FIGURE_WIDTH, height=height * scale)


def _table(spec, brand: BrandSystem, sheet: dict) -> list:
    """A table that splits across pages and repeats its header row."""
    header = [Paragraph(_x(column.header), sheet["cell_head"])
              for column in spec.columns]
    numeric = {index for index, column in enumerate(spec.columns)
               if column.kind in ("number", "currency", "percent")}

    rows = [header]
    for row in spec.displayed_rows:
        rendered = []
        for index, cell in enumerate(row[:len(spec.columns)]):
            style = sheet["cell_num"] if index in numeric else sheet["cell"]
            colour = _emphasis_colour(cell.emphasis, brand)
            text = _x(cell.text)
            if colour:
                text = f'<font color="{colour}">{text}</font>'
            rendered.append(Paragraph(text, style))
        rows.append(rendered)

    table = Table(rows, repeatRows=1, splitByRow=True, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(brand.color("primary"))),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4,
         colors.HexColor(brand.color("rule"))),
    ]
    for index in range(1, len(rows)):
        if index % 2 == 0:
            commands.append(("BACKGROUND", (0, index), (-1, index),
                             colors.HexColor(brand.color("surface_alt"))))
    for index in spec.emphasis_rows:
        if index >= spec.displayed_row_count:
            continue
        commands.append(("BACKGROUND", (0, index + 1), (-1, index + 1),
                         colors.HexColor(brand.color("surface_alt"))))
    table.setStyle(TableStyle(commands))

    out: list = [table]
    if spec.caption:
        out.append(Paragraph(_x(spec.caption), sheet["caption"]))
    if spec.has_note:
        out.append(Paragraph(_x(spec.note()), sheet["source"]))
    return out


def _kpi_table(element: KpiRowElement, brand: BrandSystem,
               sheet: dict) -> Optional[Table]:
    tiles = element.tiles[:5]
    if not tiles:
        return None
    values, labels = [], []
    for tile in tiles:
        colour = _emphasis_colour(tile.emphasis, brand) or brand.color("primary")
        values.append(Paragraph(
            f'<font color="{colour}">{_x(tile.display or "Not Reported")}</font>',
            sheet["kpi_value"]))
        labels.append(Paragraph(
            _x(tile.label + (f" ({tile.note})" if tile.note else "")),
            sheet["kpi_label"]))

    table = Table([values, labels], hAlign="LEFT",
                  colWidths=[FIGURE_WIDTH / len(tiles)] * len(tiles))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1),
         colors.HexColor(brand.color("surface_alt"))),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
    ]))
    return table


def _emphasis_colour(emphasis: str, brand: BrandSystem) -> Optional[str]:
    return {"bad": brand.color("rag_red"), "warn": brand.color("rag_amber"),
            "good": brand.color("rag_green"),
            "muted": brand.color("muted")}.get(emphasis)


def _appendix(story: list, deliverable: Deliverable,
              context: GenerationContext, sheet: dict) -> None:
    story.append(PageBreak())
    story.append(Paragraph("Sources and methodology", sheet["h1"]))

    story.append(Paragraph("Sources read", sheet["h2"]))
    files = context.evidence.projected_from_files
    if files:
        for name in files:
            story.append(Paragraph(f"&bull;&nbsp;&nbsp;{_x(name)}",
                                   sheet["source"]))
    else:
        story.append(Paragraph("No files were read for this document.",
                               sheet["body"]))

    conflicts = context.unresolved_critical_conflicts
    if conflicts:
        story.append(Paragraph("Unresolved disagreements between sources",
                               sheet["h2"]))
        story.append(Paragraph(
            "The figures below are disputed. Neither value should be treated as "
            "agreed.", sheet["body"]))
        for conflict in conflicts:
            claims = "; ".join(f"{name} says {value}"
                               for name, value in conflict.values.items())
            story.append(Paragraph(
                f"&bull;&nbsp;&nbsp;{_x(conflict.entity_key)} "
                f"({_x(conflict.field)}): {_x(claims)}", sheet["bullet"]))

    if deliverable.notes:
        story.append(Paragraph("Limitations", sheet["h2"]))
        for note in deliverable.notes:
            story.append(Paragraph(f"&bull;&nbsp;&nbsp;{_x(note)}",
                                   sheet["bullet"]))

    if deliverable.warnings:
        story.append(Paragraph("What the system could not do", sheet["h2"]))
        for warning in deliverable.warnings[:15]:
            story.append(Paragraph(f"&bull;&nbsp;&nbsp;{_x(warning)}",
                                   sheet["bullet"]))


def _x(text: str) -> str:
    """Escape for platypus's mini-markup, which reads `<` and `&` as markup."""
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
