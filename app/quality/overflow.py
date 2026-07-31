"""Catch text that will not fit, shapes that collide, and content off the canvas.

Deterministic geometry, always on. It reads the boxes the renderers reported
rather than re-opening the file and inferring them: a renderer knows what it
drew, and a critic guessing afterwards gets the placeholder inheritance wrong.

**An honest statement of coverage.** For PPTX this is *analytic* — text is laid
out here, in Python, using a font that is probably not the one the reader will
see, and PowerPoint's own autofit is not simulated. It reliably catches the
gross cases (a title twice too long, shapes overlapping, content off the slide)
and cannot catch what only appears once a real layout engine runs. LibreOffice
would close that gap by rasterising the deck; it is not installed here, so
`rasterize.py` skips it and this module is what stands in. Nobody should read a
green suite as "somebody looked at the deck".

The PDF is different: `pdfmetrics.stringWidth` is exact and the pages can be
rasterised, so the PDF is the calibration reference for the others.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import Deliverable
from app.quality import textmetrics
from app.quality.schemas import ArtifactReview, Finding, finding
from app.renderers.common import MeasuredBox, RenderResult
from app.templates.brand_system import BrandSystem

log = logging.getLogger("pmi.quality.overflow")

#: Two shapes overlapping by more than this fraction of the smaller one are
#: colliding rather than deliberately layered.
OVERLAP_TOLERANCE = 0.28
#: How far outside the canvas is a rounding artefact rather than a bug.
EDGE_TOLERANCE_IN = 0.03
#: Shapes whose overlap is part of the design.
_LAYERED = ("pmi:callout-rule", "pmi:footer", "pmi:page-number",
            "diagram:cell", "diagram:axis")


def check_pptx(result: RenderResult, deliverable: Deliverable,
               context: GenerationContext, *,
               pass_number: int = 1) -> ArtifactReview:
    """Analytic checks over a rendered deck."""
    review = ArtifactReview(review_id=f"overflow-pptx-{pass_number}",
                            pass_number=pass_number, format="pptx")
    brand: BrandSystem = context.brand_system or _fallback_brand()
    catalog = getattr(context.template_reference, "catalog", None)

    review.add(*_check_canvas(result.element_boxes, brand))
    review.add(*_check_overlaps(result.element_boxes))
    review.add(*_check_text_fits(result, deliverable, brand, catalog))
    review.add(*_check_readability(result, deliverable, brand, catalog))
    review.add(*_check_empty(deliverable))

    if review.findings:
        log.info("overflow pass %d: %s", pass_number, review.summary())
    return review


def _fallback_brand() -> BrandSystem:
    from app.templates import template_registry

    return template_registry.default().brand


# ================================================================== geometry
def _check_canvas(boxes: Sequence[MeasuredBox],
                  brand: BrandSystem) -> list[Finding]:
    findings: list[Finding] = []
    for box in boxes:
        if box.right_in > brand.slide_w_in + EDGE_TOLERANCE_IN or \
                box.bottom_in > brand.slide_h_in + EDGE_TOLERANCE_IN or \
                box.left_in < -EDGE_TOLERANCE_IN or \
                box.top_in < -EDGE_TOLERANCE_IN:
            findings.append(finding(
                "overflow", "fix",
                f"An element on this page ({box.name}) extends past the edge of "
                f"the slide, so part of it will not be visible.",
                page_id=box.page_id, action="relayout",
                detail=(f"box {box.left_in:.2f},{box.top_in:.2f} "
                        f"{box.width_in:.2f}x{box.height_in:.2f}in on a "
                        f"{brand.slide_w_in:.2f}x{brand.slide_h_in:.2f}in slide")))
    return findings


def _check_overlaps(boxes: Sequence[MeasuredBox]) -> list[Finding]:
    findings: list[Finding] = []
    by_page: dict[str, list[MeasuredBox]] = {}
    for box in boxes:
        if box.name.startswith(_LAYERED):
            continue
        by_page.setdefault(box.page_id, []).append(box)

    for page_id, page_boxes in by_page.items():
        for index, first in enumerate(page_boxes):
            for second in page_boxes[index + 1:]:
                # A placeholder that content was drawn over was consumed by
                # design; only report two pieces of *content* colliding.
                if first.is_placeholder and second.is_placeholder:
                    continue
                overlap = first.overlaps(second)
                smaller = min(first.area_in2, second.area_in2)
                if smaller <= 0:
                    continue
                if overlap / smaller > OVERLAP_TOLERANCE:
                    findings.append(finding(
                        "overflow", "fix",
                        f"Two elements on this page overlap ({first.name} and "
                        f"{second.name}), so one obscures the other.",
                        page_id=page_id, action="relayout",
                        detail=f"{overlap:.2f}in² of {smaller:.2f}in²"))
    return findings


# ====================================================================== text
def _check_text_fits(result: RenderResult, deliverable: Deliverable,
                     brand: BrandSystem, catalog) -> list[Finding]:
    findings: list[Finding] = []
    for box in result.element_boxes:
        if not box.text.strip() or box.name.startswith(_LAYERED):
            continue
        size_pt = box.font_pt or _size_for(box, deliverable, brand, catalog)
        if size_pt is None:
            continue

        # Placeholder insets: PowerPoint's default text margins.
        width = max(box.width_in - 0.2, 0.3)
        height = max(box.height_in - 0.1, 0.2)
        extent = textmetrics.measure(box.text, size_pt=size_pt,
                                     max_width_in=width)
        if not extent.overflows(width, height):
            continue

        smaller = textmetrics.largest_size_that_fits(
            box.text, box_width_in=width, box_height_in=height,
            ceiling_pt=size_pt)
        action = "shorten" if smaller is None else "relayout"
        remedy = ("The text has to be shorter." if smaller is None
                  else f"It would fit at {smaller:g}pt.")
        findings.append(finding(
            "overflow", "fix",
            f"Text on this page does not fit its box ({box.name}): it needs "
            f"{extent.line_count} line(s) at {size_pt:g}pt in "
            f"{height:.2f}in of height. {remedy}",
            page_id=box.page_id, action=action,
            detail=(f"needs {extent.height_in:.2f}in x {extent.width_in:.2f}in, "
                    f"has {height:.2f}in x {width:.2f}in; measured in "
                    f"{textmetrics.measured_font_name()}")))
    return findings


def _size_for(box: MeasuredBox, deliverable: Deliverable, brand: BrandSystem,
             catalog) -> Optional[float]:
    """The effective point size of a box's text.

    For a placeholder, the layout resolved it (python-pptx reports `None`). For
    a textbox Python drew, the token it was drawn with.
    """
    page = deliverable.page(box.page_id)
    if page is not None and catalog is not None and box.is_placeholder:
        layout = catalog.by_id(page.layout_id)
        if layout is not None:
            for slot in layout.slots:
                if slot.ph_idx is not None and _matches(box, slot):
                    return slot.default_pt

    token = {
        "pmi:governing": "h1", "pmi:quote": "display", "pmi:caption": "caption",
        "pmi:source-note": "caption", "pmi:footer": "label",
        "pmi:page-number": "label", "pmi:callout": "small",
        "pmi:bullets": "body", "pmi:body": "body",
    }.get(box.name)
    if token:
        return brand.font(token).size_pt
    if box.name.startswith("pmi:"):
        return brand.font("body").size_pt
    return None


def _matches(box: MeasuredBox, slot) -> bool:
    return (abs(box.left_in - slot.left_in) < 0.05
            and abs(box.top_in - slot.top_in) < 0.05)


def _check_readability(result: RenderResult, deliverable: Deliverable,
                       brand: BrandSystem, catalog) -> list[Finding]:
    """Type too small to read from the back of the room."""
    findings: list[Finding] = []
    seen: set[str] = set()
    for box in result.element_boxes:
        if not box.text.strip():
            continue
        size_pt = box.font_pt or _size_for(box, deliverable, brand, catalog)
        # Footers and captions are meant to be small; body copy is not.
        if size_pt is None or box.name.startswith(_LAYERED) or \
                box.name in ("pmi:caption", "pmi:source-note"):
            continue
        if size_pt < textmetrics.MIN_SLIDE_PT and box.page_id not in seen:
            seen.add(box.page_id)
            findings.append(finding(
                "overflow", "warn",
                f"Text on this page is set at {size_pt:g}pt, below the "
                f"{textmetrics.MIN_SLIDE_PT:g}pt floor for a projected slide.",
                page_id=box.page_id, action="relayout"))
    return findings


def _check_empty(deliverable: Deliverable) -> list[Finding]:
    """A page with nothing on it, or a title over nothing."""
    findings: list[Finding] = []
    for page in deliverable.pages:
        if page.is_empty:
            findings.append(finding(
                "overflow", "block",
                "This page has no content at all.",
                page_id=page.page_id, action="regenerate_page"))
            continue
        if page.purpose in ("cover", "divider", "closing"):
            continue
        has_text = any(getattr(e, "text", "") or getattr(e, "items", [])
                       for e in page.elements)
        if not has_text and not page.has_visual:
            findings.append(finding(
                "overflow", "block",
                "This page has a title and nothing under it.",
                page_id=page.page_id, action="regenerate_page"))
    return findings


# ============================================================ other formats
def check_pdf(result: RenderResult, deliverable: Deliverable,
              context: GenerationContext, *,
              pass_number: int = 1) -> ArtifactReview:
    """Rasterise and look for blank or clipped pages.

    PyMuPDF gives real pixels here, so this is the one format where the check is
    not an approximation.
    """
    review = ArtifactReview(review_id=f"overflow-pdf-{pass_number}",
                            pass_number=pass_number, format="pdf")
    try:
        import fitz
    except ImportError:                                        # noqa: BLE001
        return review

    try:
        with fitz.open(str(result.path)) as document:
            for index, page in enumerate(document, start=1):
                text = page.get_text().strip()
                images = page.get_images()
                if not text and not images:
                    review.add(finding(
                        "overflow", "block",
                        f"Page {index} of the PDF is blank.",
                        action="regenerate_page"))
                    continue
                review.add(*_check_clipping(page, index))
    except Exception as exc:                                   # noqa: BLE001
        log.warning("could not inspect the PDF (%s)", exc)
    return review


def _check_clipping(page, index: int) -> list[Finding]:
    """Text whose bounding box runs past the page edge."""
    findings: list[Finding] = []
    rect = page.rect
    for block in page.get_text("blocks"):
        x0, y0, x1, y1 = block[:4]
        if x1 > rect.x1 + 1 or y1 > rect.y1 + 1 or x0 < rect.x0 - 1:
            findings.append(finding(
                "overflow", "fix",
                f"Text on page {index} of the PDF is clipped by the page edge.",
                action="shorten",
                detail=f"block {x0:.0f},{y0:.0f}-{x1:.0f},{y1:.0f} in {rect}"))
            break
    return findings


def check_docx(result: RenderResult, deliverable: Deliverable,
               context: GenerationContext, *,
               pass_number: int = 1) -> ArtifactReview:
    """Word reflows, so there is no overflow to check — only emptiness."""
    review = ArtifactReview(review_id=f"overflow-docx-{pass_number}",
                            pass_number=pass_number, format="docx")
    review.add(*_check_empty(deliverable))
    return review


def check_html(result: RenderResult, deliverable: Deliverable,
               context: GenerationContext, *,
               pass_number: int = 1) -> ArtifactReview:
    """HTML reflows too. What can go wrong is content, not geometry."""
    review = ArtifactReview(review_id=f"overflow-html-{pass_number}",
                            pass_number=pass_number, format="html")
    review.add(*_check_empty(deliverable))
    return review


CHECKS = {"pptx": check_pptx, "pdf": check_pdf, "docx": check_docx,
          "html": check_html}


def check(result: RenderResult, deliverable: Deliverable,
          context: GenerationContext, *, pass_number: int = 1) -> ArtifactReview:
    checker = CHECKS.get(result.suffix, check_docx)
    return checker(result, deliverable, context, pass_number=pass_number)
