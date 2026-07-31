"""Review an artifact before it is delivered, and repair what can be repaired.

    review(deliverable, context, result) -> ArtifactReview

Four critics, in the order their findings matter:

* `grounding` — is everything it states supported?
* `completeness` — is it the document that was asked for, and does it disclose
  what must be disclosed?
* `overflow` — will it physically fit, and does anything collide?
* `design_review` — does it read like a considered deliverable?

`repair` regenerates only the pages a review named. It re-runs no extraction, no
projection and no storyline: a page that overflowed does not mean the argument
was wrong, and re-planning to fix a layout would rewrite text the user has
already read.

The loop is hard-capped. A page that fails twice ships with its finding recorded
in the artifact, because an unbounded repair loop against a model's judgement can
oscillate forever, and a document that never ships is worse than one that ships
with a stated flaw.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import Deliverable, TextElement
from app.quality import completeness, design_review, grounding, overflow, rasterize
from app.quality.schemas import ArtifactReview, Finding, Verdict, finding
from app.renderers.common import RenderResult

log = logging.getLogger("pmi.quality")

#: How many repair attempts before shipping with the finding recorded.
MAX_REPAIR_PASSES = 2

__all__ = ["ArtifactReview", "Finding", "MAX_REPAIR_PASSES", "repair", "review",
           "review_plan"]


def review(deliverable: Deliverable, context: GenerationContext,
           result: Optional[RenderResult] = None, *,
           brief=None, pass_number: int = 1,
           use_model: bool = True) -> ArtifactReview:
    """Every critic, combined into one review."""
    combined = ArtifactReview(review_id=f"review-{pass_number}",
                              pass_number=pass_number,
                              format=result.suffix if result else "")

    combined.add(*grounding.check(deliverable, context,
                                  pass_number=pass_number).findings)
    combined.add(*completeness.check(deliverable, context, brief=brief,
                                     pass_number=pass_number).findings)

    if result is not None:
        combined.add(*overflow.check(result, deliverable, context,
                                     pass_number=pass_number).findings)
        # `None` from the rasterizer means "not checked", never "checked and
        # fine" — on this machine a deck is never rasterised.
        images = rasterize.pages(result.path) or []
        combined.add(*design_review.review(deliverable, context, images=images,
                                           pass_number=pass_number,
                                           use_model=use_model).findings)
    else:
        combined.add(*design_review.review(deliverable, context,
                                           pass_number=pass_number,
                                           use_model=False).findings)

    log.info("review pass %d (%s): %s", pass_number, combined.format or "plan",
             combined.summary())
    return combined


def review_plan(deliverable: Deliverable, context: GenerationContext, *,
                brief=None) -> ArtifactReview:
    """The checks that do not need a rendered file. Run before rendering."""
    return review(deliverable, context, None, brief=brief, use_model=False)


# ==================================================================== repair
def repair(deliverable: Deliverable, context: GenerationContext,
           reviewed: ArtifactReview) -> tuple[Deliverable, list[str]]:
    """Apply what can be fixed without re-planning. Returns the new deliverable.

    Three kinds of repair, in increasing order of destructiveness:

    * `shorten` — trim prose or a title to fit its box.
    * `drop_element` — remove an element the user asked not to have.
    * `regenerate_page` — rebuild the page's prose from the evidence
      deterministically, which is always grounded even when the model's version
      was not.

    Anything else is recorded on the page as a warning the reader can see. A
    silent unrepaired finding is the failure mode this whole layer exists to
    prevent.
    """
    if reviewed.passed:
        return deliverable, []

    from app.generation import narrative_writer
    from app.quality import textmetrics

    revised = deliverable.model_copy(deep=True)
    revised.version = deliverable.version + 1
    revised.parent_version = deliverable.version
    applied: list[str] = []

    for item in sorted(reviewed.findings, key=lambda f: f.rank):
        if item.severity not in ("block", "fix"):
            continue
        page = revised.page(item.page_id) if item.page_id else None

        if item.suggested_action == "shorten" and page is not None:
            if _shorten(page, item, context, textmetrics):
                applied.append(f"Shortened text on {page.page_id}.")
                continue

        if item.suggested_action == "drop_element" and page is not None:
            if _drop(page, item):
                applied.append(f"Removed an element from {page.page_id}.")
                continue

        if item.suggested_action == "regenerate_page" and page is not None:
            narrative_writer.write_page(page, context, None, use_model=False)
            page.warnings.append(
                f"Rewritten during review: {item.message}")
            applied.append(f"Rewrote {page.page_id} from the evidence.")
            continue

        # Nothing automatic to do. Put it where the reader will see it.
        target = page.warnings if page is not None else revised.warnings
        if item.message not in target:
            target.append(item.message)

    _disclose(revised, reviewed)
    log.info("repair: applied %d fix(es), disclosed %d finding(s)",
             len(applied), len(revised.warnings))
    return revised, applied


def _shorten(page, item: Finding, context: GenerationContext,
             textmetrics) -> bool:
    """Trim the offending text at a sentence boundary."""
    if item.element_id:
        for element in page.elements:
            if element.element_id != item.element_id:
                continue
            text = getattr(element, "text", "")
            if text:
                element.text = textmetrics.shorten_to_fit(
                    text, size_pt=12.0, box_width_in=5.8, box_height_in=2.4)
                return True
            items = getattr(element, "items", None)
            if items:
                element.items = [textmetrics.shorten_to_fit(
                    entry, size_pt=12.0, box_width_in=5.8,
                    box_height_in=0.5) for entry in items[:6]]
                return True
        return False

    if page.title:
        page.title = textmetrics.shorten_to_fit(
            page.title, size_pt=21.0, box_width_in=12.1, box_height_in=0.37)
        return True
    return False


def _drop(page, item: Finding) -> bool:
    before = len(page.elements)
    if item.element_id:
        page.elements = [e for e in page.elements
                         if e.element_id != item.element_id]
    else:
        page.elements = [e for e in page.elements if e.role != "chart"]
    return len(page.elements) < before

"""
def _disclose(deliverable: Deliverable, reviewed: ArtifactReview) -> None:
     Put unfixed blocking findings in the artifact, on page one.

    A document that failed review and does not say so is worse than one that
    fails visibly: the reader has no way to know.
    
    blocking = [f for f in reviewed.blocking]
    if not blocking or not deliverable.pages:
        return

    notice = ("This document did not pass its own review: "
              + " ".join(f.message for f in blocking[:3]))
    if notice in deliverable.warnings:
        return
    deliverable.warnings.insert(0, notice)
    first = deliverable.pages[0]
    first.elements.insert(0, TextElement(
        element_id=f"{first.page_id}-review",
        role="callout", text=notice, emphasis="bad", authored_by="python",
        prominence="aside"))"""
