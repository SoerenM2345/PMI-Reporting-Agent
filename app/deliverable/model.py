"""The artifact, planned and resolved, before anything is rendered.

A `Deliverable` is what the four renderers consume. It is the boundary between
"the model decided" and "Python is now responsible": by the time one exists,
every evidence id has been validated, every composition has been bound to a real
template layout, and every figure that will appear has been resolved from
evidence rather than written by a model.

It plays the role `ReportContent` played, and differs in the ways that matter:

* pages are whatever the storyline needed, not a fixed list per audience;
* elements carry a *role* and a *slot*, so the same page renders as a slide, a
  Word section and an HTML block without any of them re-deciding anything;
* every page records the evidence behind it, so its footnote, its staleness and
  its grounding check all read from one place;
* `planned_by` says whether a model shaped this or a fallback did — and the
  fallback says so on the page, not only in a log.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.report.content import Emphasis
from app.context.schemas import SourceUseConstraint
from app.visualizations.specs import ChartSpec, DiagramSpec, TableSpec

log = logging.getLogger("pmi.deliverable")

PlannedBy = Literal["llm", "fallback", "user"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ elements
class BaseElement(BaseModel):
    element_id: str
    #: The layout slot this was bound to (`title`, `col1`, …). Empty for
    #: elements the renderer positions itself, such as a footer band.
    slot: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    authored_by: Literal["llm", "python", "user"] = "python"
    emphasis: Emphasis = "none"
    prominence: Literal["primary", "supporting", "aside"] = "supporting"


class TextElement(BaseElement):
    role: Literal["headline", "kicker", "body", "callout", "quote", "footnote",
                  "source_note"] = "body"
    text: str = ""


class BulletsElement(BaseElement):
    role: Literal["bullets"] = "bullets"
    items: list[str] = Field(default_factory=list)


class TableElement(BaseElement):
    role: Literal["table"] = "table"
    spec_id: str = ""
    caption: str = ""


class ChartElement(BaseElement):
    role: Literal["chart"] = "chart"
    spec_id: str = ""
    caption: str = ""


class DiagramElement(BaseElement):
    role: Literal["diagram"] = "diagram"
    spec_id: str = ""
    caption: str = ""


class KpiTile(BaseModel):
    label: str = ""
    evidence_id: str = ""
    #: Resolved by Python from the evidence. Never written by a model.
    display: str = ""
    emphasis: Emphasis = "none"
    note: str = ""


class KpiRowElement(BaseElement):
    role: Literal["kpi_row"] = "kpi_row"
    tiles: list[KpiTile] = Field(default_factory=list)


class ImageElement(BaseElement):
    role: Literal["image"] = "image"
    image_ref: str = ""
    alt: str = ""
    caption: str = ""


DesignElement = Annotated[
    Union[TextElement, BulletsElement, TableElement, ChartElement,
          DiagramElement, KpiRowElement, ImageElement],
    Field(discriminator="role"),
]


# --------------------------------------------------------------------- pages
class PageDesign(BaseModel):
    """One page, bound to a real layout and ready to render."""

    model_config = ConfigDict(revalidate_instances="never")

    page_id: str
    index: int = 0
    section_id: str = ""
    purpose: str = "content"
    composition: str = "single"

    #: A real `TemplateLayout.layout_id`, chosen by Python from the catalog.
    layout_id: str = ""
    layout_name: str = ""

    title: str = ""
    subtitle: str = ""
    elements: list[DesignElement] = Field(default_factory=list)
    speaker_notes: str = ""
    source_note: str = ""

    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    planned_by: PlannedBy = "fallback"
    #: Anything compromised about this page — a degraded layout, a chart that
    #: could not be validated, a repair that did not take. Rendered where the
    #: reader can see it, not only logged.
    warnings: list[str] = Field(default_factory=list)

    def element(self, element_id: str) -> Optional[DesignElement]:
        for element in self.elements:
            if element.element_id == element_id:
                return element
        return None

    def of_role(self, *roles: str) -> list[DesignElement]:
        wanted = set(roles)
        return [e for e in self.elements if e.role in wanted]

    @property
    def is_empty(self) -> bool:
        """A page with a title and nothing else is a defect unless it is a
        divider, whose whole design is one line of type."""
        if self.purpose in ("divider", "cover", "closing"):
            return not (self.title or self.subtitle)
        return not self.elements

    @property
    def has_visual(self) -> bool:
        return bool(self.of_role("chart", "diagram", "image", "table"))

    def text_content(self) -> str:
        parts = [self.title, self.subtitle]
        for element in self.elements:
            parts.append(getattr(element, "text", ""))
            parts.extend(getattr(element, "items", []) or [])
            parts.append(getattr(element, "caption", ""))
            for tile in getattr(element, "tiles", []) or []:
                parts.extend([tile.label, tile.display])
        return "\n".join(p for p in parts if p)


# ------------------------------------------------------------------ document
class DeliverableSpecs(BaseModel):
    """Validated visual specifications, keyed by the `spec_id` pages reference.

    Typed concretely, not as `dict[str, Any]`. That was the first attempt and it
    does not survive storage: a `Deliverable` is persisted as JSON and reloaded
    for every export, and loosely-typed specs come back as plain dicts, so the
    renderers reach for `spec.columns` on a dict and fail at export time — long
    after the code that made the mistake has returned.
    """

    charts: dict[str, ChartSpec] = Field(default_factory=dict)
    diagrams: dict[str, DiagramSpec] = Field(default_factory=dict)
    tables: dict[str, TableSpec] = Field(default_factory=dict)

    def get(self, kind: str, spec_id: str) -> Optional[Any]:
        return getattr(self, kind, {}).get(spec_id)


class Deliverable(BaseModel):
    """A planned document. The renderers' single input."""

    model_config = ConfigDict(revalidate_instances="never")

    schema_version: int = 1
    deliverable_id: str = ""
    version: int = 1
    parent_version: Optional[int] = None
    created_at: str = Field(default_factory=_now)

    project_id: Optional[str] = None
    session_id: Optional[str] = None
    chat_id: Optional[str] = None

    title: str = ""
    subtitle: str = ""
    document_kind: str = "status_report"
    primary_format: str = "pptx"
    audience_label: str = ""
    presentation_layout: bool = False
    #: True for user-facing chat drafts.  Legacy/programmatic planning may keep
    #: this false, but a reviewed draft cannot be rendered until its exact
    #: version and format have been approved.
    review_required: bool = False
    governing_message: str = ""
    executive_takeaway: str = ""

    pages: list[PageDesign] = Field(default_factory=list)
    specs: DeliverableSpecs = Field(default_factory=DeliverableSpecs)

    #: What the plan promised, kept so the completeness critic can check the
    #: artifact against the ask rather than against itself.
    requested_sections: list[str] = Field(default_factory=list)
    covered_sections: dict[str, list[str]] = Field(default_factory=dict)

    #: The ask this document was planned from, verbatim. Recorded because the
    #: staleness check has to fingerprint *the same* request the plan was built
    #: from: re-deriving it from the analysis instead compares this document
    #: against a request nobody made, and reports it stale the instant it is
    #: saved. A genuinely new ask arrives through `plan()`, not through a check.
    request_text: str = ""

    #: The audience value in the context when the request fingerprint was made.
    #: This is deliberately separate from ``audience_label``: planning may turn
    #: an inferred reader into polished display copy (for example, "CHRO" into
    #: "Steering Committee"). Reusing that editorial label as request input
    #: makes a draft appear stale the instant it is saved.
    planning_audience: Optional[str] = None

    #: Uploaded files the user explicitly asked this output to reuse.  The
    #: extracted content lives in normal elements/specs; this list records the
    #: instruction, its source locator and checksum for preview and staleness.
    source_use_constraints: list[SourceUseConstraint] = Field(default_factory=list)

    #: Pages a revision removed. Kept rather than deleted so "put the
    #: dependencies slide back" is a one-word instruction and not a re-plan, and
    #: so a renderer never has to know that removal is a concept — the pages it
    #: iterates simply do not include them.
    dropped_pages: list[PageDesign] = Field(default_factory=list)

    fingerprint: dict[str, Any] = Field(default_factory=dict)
    planned_by: PlannedBy = "fallback"
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    # ----------------------------------------------------------- accessors
    def page(self, page_id: str) -> Optional[PageDesign]:
        for page in self.pages:
            if page.page_id == page_id:
                return page
        return None

    def pages_of_section(self, section_id: str) -> list[PageDesign]:
        return [p for p in self.pages if p.section_id == section_id]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def evidence_ids(self) -> list[str]:
        seen: list[str] = []
        for page in self.pages:
            for evidence_id in page.evidence_ids:
                if evidence_id not in seen:
                    seen.append(evidence_id)
        return seen

    @property
    def layouts_used(self) -> list[str]:
        seen: list[str] = []
        for page in self.pages:
            if page.layout_id and page.layout_id not in seen:
                seen.append(page.layout_id)
        return seen

    @property
    def compositions_used(self) -> list[str]:
        return [page.composition for page in self.pages]

    def text_content(self) -> str:
        return "\n".join(page.text_content() for page in self.pages)

    def replace_page(self, page: PageDesign) -> None:
        for index, existing in enumerate(self.pages):
            if existing.page_id == page.page_id:
                page.index = existing.index
                self.pages[index] = page
                return
        raise KeyError(f"no page {page.page_id!r} to replace")

    def renumber(self) -> None:
        for index, page in enumerate(self.pages):
            page.index = index
