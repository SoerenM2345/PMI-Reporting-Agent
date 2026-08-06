"""What the planning model is allowed to decide, and how it says so.

Every schema here is filled in by an LLM. Read them as a list of the decisions
that are genuinely editorial — what the document argues, in what order, on how
many pages, expressed how — and note what is conspicuously absent.

**No schema in this module has a numeric field.** Not a value, not a percentage,
not a currency amount, not a coordinate. A page that wants to state a figure
names the evidence it came from and Python resolves it at render time. This is
the same structural guarantee `app/report/ops.py::ReviseOp` already relies on,
generalised: an invented number has nowhere to live, so it cannot be produced,
so it does not need to be detected.

The two count-like fields that do exist — `target_page_count` and
`suggested_pages` — are facts about the document, not about the project.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DocumentKind = Literal[
    "status_report", "steerco_pack", "board_update", "workstream_review",
    "deep_dive", "one_pager", "financial_review", "risk_review",
    "readiness_assessment", "decision_paper", "custom",
]
OutputFormat = Literal["pptx", "docx", "pdf", "html", "chart"]
Seniority = Literal["board", "executive", "management", "operational"]
Tone = Literal["direct", "neutral", "diplomatic"]
Length = Literal["tight", "standard", "thorough"]

SectionPurpose = Literal[
    "frame", "evidence", "analysis", "implication", "decision", "plan",
    "risk", "appendix",
]
VisualIntent = Literal[
    "none", "trend", "comparison", "composition", "distribution",
    "relationship", "sequence", "hierarchy", "matrix", "table",
]
NarrativeFlow = Literal[
    "scqa", "chronological", "by_workstream", "by_severity", "decision_first",
    "options_analysis",
]
PagePurpose = Literal["cover", "agenda", "divider", "content", "appendix",
                      "closing"]
Composition = Literal[
    "single", "two_column", "three_column", "four_column", "hero_chart",
    "chart_plus_commentary", "matrix", "table_full", "kpi_banner",
    "full_bleed", "quote",
]
ElementRole = Literal[
    "headline", "kicker", "body", "bullets", "table", "chart", "diagram",
    "kpi_row", "callout", "quote", "image", "source_note",
]
Prominence = Literal["primary", "supporting", "aside"]


class OutputBrief(BaseModel):
    """What the user is actually asking for.

    Deliberately not a report-type enum. The old pipeline reduced every request
    to one of four audiences and looked the sections up in a table, so "a
    one-pager for the CFO on whether we hold the Day 1 date" and "a full SteerCo
    pack" produced the same document.
    """

    document_kind: DocumentKind = "status_report"
    primary_format: OutputFormat = "pptx"
    also_produce: list[OutputFormat] = Field(default_factory=list)

    audience_label: str = Field(
        default="", description="The reader, in the user's own words.")
    audience_seniority: Seniority = "executive"
    reader_goal: str = Field(
        default="",
        description="What this reader must be able to do after reading it.")
    decisions_sought: list[str] = Field(default_factory=list)

    scope_topics: list[str] = Field(
        default_factory=list,
        description="Topics to cover, in the user's own words. Every topic the "
                    "user named must appear here, even if no evidence covers it.")
    excluded_topics: list[str] = Field(default_factory=list)

    tone: Tone = "direct"
    length_hint: Length = "standard"
    target_page_count: Optional[int] = Field(
        default=None, description="Pages or slides, when the user stated a limit.")

    title_proposal: str = ""
    open_questions_for_user: list[str] = Field(
        default_factory=list,
        description="What you would ask before writing, if you could.")

    @property
    def formats(self) -> list[str]:
        seen = [self.primary_format]
        for fmt in self.also_produce:
            if fmt not in seen:
                seen.append(fmt)
        return seen


class SectionIntent(BaseModel):
    """One argument the document makes."""

    section_id: str = Field(description="A short unique slug you invent.")
    working_title: str = Field(
        default="",
        description="A conclusion-oriented title. Never state a figure in it.")
    management_question: str = Field(
        default="", description="The question this section answers for the reader.")
    intended_message: str = Field(
        default="", description="The one sentence this section exists to land.")

    purpose: SectionPurpose = "evidence"
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Ids from the evidence given to you. Required unless the "
                    "purpose is 'frame'.")
    depth: Literal["headline_only", "summary", "detailed"] = "summary"
    suggested_pages: int = 1

    recommended_expression: VisualIntent = "none"
    why_this_expression: str = ""
    visual_priority: Literal["low", "medium", "high"] = "medium"

    #: Set by Python when this section answers a topic the user named, so the
    #: completeness critic can prove coverage rather than infer it.
    covers_requested: list[str] = Field(default_factory=list)


class StorylinePlan(BaseModel):
    """The argument, before anyone thinks about pages."""

    governing_message: str = Field(
        default="",
        description="The one thing the reader must take away. Lead with it.")
    executive_takeaway: str = Field(
        default="", description="The governing message expanded to 2-3 sentences.")

    situation: str = ""
    complication: str = Field(
        default="", description="What changed or went wrong. Do not bury it.")
    question: str = ""

    supporting_arguments: list[str] = Field(
        default_factory=list,
        description="Two to four arguments that, together, establish the "
                    "governing message.")
    narrative_arc: list[str] = Field(default_factory=list)
    narrative_flow: NarrativeFlow = "scqa"

    sections: list[SectionIntent] = Field(default_factory=list)
    closing_ask: str = ""
    evidence_not_used: list[str] = Field(
        default_factory=list,
        description="Ids you consciously set aside. There is no reason to hide "
                    "this and a reviewer may disagree with you.")

    @property
    def section_ids(self) -> list[str]:
        return [s.section_id for s in self.sections]

    def section(self, section_id: str) -> Optional[SectionIntent]:
        for section in self.sections:
            if section.section_id == section_id:
                return section
        return None


class ElementIntent(BaseModel):
    """One thing on a page. No coordinates, no sizes, no values."""

    role: ElementRole
    intent: str = Field(
        default="", description="What this element must communicate.")
    evidence_ids: list[str] = Field(default_factory=list)
    prominence: Prominence = "supporting"


class PageIntent(BaseModel):
    """How one page should communicate its part of the argument.

    `composition` names an arrangement, not a layout. Python binds it to a real
    template layout and works out the geometry, because the model has no way to
    know that this master's two-column layout puts its right column at 6.84in.
    """

    page_id: str = Field(description="A short unique slug you invent.")
    section_id: str = ""
    purpose: PagePurpose = "content"
    composition: Composition = "single"

    message_title: str = Field(
        default="",
        description="The page's headline. Say the finding, not the topic.")
    supporting_message: str = ""

    elements: list[ElementIntent] = Field(default_factory=list)
    visual_hierarchy: list[str] = Field(
        default_factory=list,
        description="Element roles in the order the reader should meet them.")
    density: Literal["sparse", "normal", "dense"] = "normal"
    speaker_notes_intent: str = ""

    @property
    def evidence_ids(self) -> list[str]:
        seen: list[str] = []
        for element in self.elements:
            for evidence_id in element.evidence_ids:
                if evidence_id not in seen:
                    seen.append(evidence_id)
        return seen


class DocumentDesign(BaseModel):
    """Every page, in order."""

    pages: list[PageIntent] = Field(default_factory=list)
    rationale: str = Field(
        default="", description="Why this shape, in one or two sentences.")

    @property
    def page_ids(self) -> list[str]:
        return [page.page_id for page in self.pages]


class PageCopy(BaseModel):
    """The written content of one page."""

    page_id: str = ""
    message_title: str = ""
    supporting_message: str = ""
    body: str = ""
    bullets: list[str] = Field(default_factory=list)
    callout: str = ""
    speaker_notes: str = ""


class PageTitle(BaseModel):
    page_id: str = ""
    title: str = ""
    subtitle: str = ""


class DocumentTitles(BaseModel):
    """Titles for the whole document in one call.

    Batched deliberately: written page by page, six slides in a row open with
    the same verb, and no single call can see that happening.
    """

    document_title: str = ""
    document_subtitle: str = ""
    titles: list[PageTitle] = Field(default_factory=list)


class CompleteReportPlan(BaseModel):
    """Every editorial decision for one report, returned in one model call.

    The nested contracts deliberately reuse the existing validated schemas.
    Figures still have no authored field here: pages refer to evidence ids and
    Python remains responsible for resolving values, arithmetic and charts.
    """

    brief: OutputBrief = Field(default_factory=OutputBrief)
    storyline: StorylinePlan = Field(default_factory=StorylinePlan)
    design: DocumentDesign = Field(default_factory=DocumentDesign)
    page_copy: list[PageCopy] = Field(default_factory=list)
    titles: DocumentTitles = Field(default_factory=DocumentTitles)
