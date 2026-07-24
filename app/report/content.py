"""`ReportContent` — what the report says, before anything decides how to draw it.

Until now "what to say" and "how to render it" were fused: each generator walked
`PMIDataModel` and emitted python-pptx or xlsxwriter primitives inline, so the
same editorial judgement lived twice and could only be inspected by opening a
binary. That made three things impossible: showing the user the report as text
before generating it, letting them revise it ("add a slide about X"), and adding
a fourth output format without a fourth copy of the judgement.

The structure separates three kinds of thing, and the separation is what makes
§11 enforceable rather than merely intended:

* **Facts** — values from `PMIDataModel` and `calculations.py`. Keyed, carrying
  their own provenance. Never authored by a model.
* **Prose** — headlines, bullets, framing. A model may write these.
* **Selection and order** — which sections, which rows. A model may change these,
  but only by *reference*: it names a section or a filter, never a value.

A bullet stored as the flat string "3 critical risks are open" cannot be revised
safely — ask a model to make it punchier and it can hand back "4". So numbers
that matter live in `Fact`, and text that mentions them is checked against the
fact table (`guard.py`) before it is ever accepted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.models.enums import Audience

Emphasis = Literal["none", "good", "warn", "bad", "muted"]


# --------------------------------------------------------------------- facts
class FactRef(BaseModel):
    """Where a fact came from — the §6.14 provenance, flattened for display."""

    entity_type: str
    entity_id: Optional[str] = None
    field: Optional[str] = None

    file_name: Optional[str] = None
    location: Optional[str] = None
    confidence: Optional[float] = None

    #: Computed by `calculations.py` rather than read from a file. Worth marking:
    #: a derived figure has no single source to cite, and saying "tracker.xlsx"
    #: for a number we worked out ourselves would be a false citation.
    is_derived: bool = False

    #: Set when the sources disagreed about this value and nobody has decided yet.
    conflict_id: Optional[str] = None


class Fact(BaseModel):
    """One number or status the report may state.

    `value` is the raw thing (for a spreadsheet cell that should sort and chart);
    `display` is the already-formatted string (for everything else). Both are
    produced by Python — a renderer never re-derives a figure, and a model never
    supplies one.
    """

    key: str                      # "risk.open_critical", "budget.total_variance"
    label: str
    value: Optional[Union[float, int, str]] = None
    display: str
    refs: list[FactRef] = Field(default_factory=list)

    @property
    def is_missing(self) -> bool:
        return self.value is None


class FactTable(BaseModel):
    values: dict[str, Fact] = Field(default_factory=dict)

    def add(self, fact: Fact) -> Fact:
        self.values[fact.key] = fact
        return fact

    def get(self, key: str) -> Optional[Fact]:
        return self.values.get(key)

    def display(self, key: str, missing: str = "Not Reported") -> str:
        fact = self.values.get(key)
        return fact.display if fact else missing

    def numeric_corpus(self) -> set[str]:
        """Every number this report is entitled to state.

        `guard.py` checks model-authored prose against this set. A figure that is
        not in here did not come from the data, which means something invented it.
        """
        corpus: set[str] = set()
        for fact in self.values.values():
            corpus.update(_numbers_in(fact.display))
            if isinstance(fact.value, (int, float)):
                corpus.add(_normalise_number(str(fact.value)))
        return corpus


def _normalise_number(token: str) -> str:
    """`1,250` `1250.0` `45%` all compare equal to their bare integer form."""
    token = token.strip().rstrip("%").replace(",", "")
    if token.endswith(".0"):
        token = token[:-2]
    return token.lstrip("+")


def _numbers_in(text: str) -> set[str]:
    """Numbers a piece of report text states — signed *and* unsigned.

    A budget variance is stored as -250 and reads naturally as "over budget by
    250". Both refer to the same figure; the sign is a presentational choice, so
    admitting the magnitude keeps the guard from rejecting an honest rephrase.
    It does not widen what can be claimed: 250 is a number this report already
    prints.
    """
    import re

    found: set[str] = set()
    for match in re.findall(r"-?\d[\d,]*(?:\.\d+)?%?", text or ""):
        value = _normalise_number(match)
        found.add(value)
        found.add(value.lstrip("-"))
    return found


# --------------------------------------------------------------------- table
class Column(BaseModel):
    """A column's *meaning*, not its formatting.

    The workbook turns `kind` and the two flags back into xlsxwriter formats and
    conditional-format ranges; the deck ignores most of it. Keeping intent here
    rather than a format name means a new renderer does not have to reverse
    engineer what `percent_columns=[3]` was for.
    """

    header: str
    kind: Literal["text", "number", "percent", "currency", "date", "flag"] = "text"
    rag: bool = False                 # colour by Red/Amber/Green status
    negative_is_bad: bool = False     # a negative variance is not merely a minus sign
    width: Optional[int] = None


class Cell(BaseModel):
    text: str                         # always present — this is what a slide shows
    value: Optional[Union[float, int, str]] = None   # raw, for a sortable cell
    emphasis: Emphasis = "none"


class EntityQuery(BaseModel):
    """A table defined by reference rather than by value.

    The Masterplan sheet is ~500 rows. Materialising it into the stored content
    would bloat every saved version and, worse, let the stored copy drift from
    the data model after a conflict is resolved. So large tables carry the query
    and are resolved at render time; narrative tables (a dozen rows the user is
    actually reading) are materialised so the preview can show them.
    """

    entity: Literal["task", "milestone", "risk", "issue", "dependency",
                    "decision", "budget", "synergy", "kpi", "workstream"]
    only_open: bool = False
    only_overdue: bool = False
    min_severity: Optional[str] = None
    workstream: Optional[str] = None
    order_by: Optional[str] = None
    descending: bool = False


# -------------------------------------------------------------------- blocks
class ProseBlock(BaseModel):
    kind: Literal["prose"] = "prose"
    block_id: str
    title: Optional[str] = None
    text: str
    authored_by: Literal["planner", "llm", "user"] = "planner"


class Bullet(BaseModel):
    text: str
    emphasis: Emphasis = "none"
    refs: list[FactRef] = Field(default_factory=list)
    authored_by: Literal["planner", "llm", "user"] = "planner"


class BulletsBlock(BaseModel):
    kind: Literal["bullets"] = "bullets"
    block_id: str
    #: Optional because one slide can stack two labelled lists (the §12.2
    #: "missing updates" slide does exactly this).
    title: Optional[str] = None
    items: list[Bullet] = Field(default_factory=list)


class Tile(BaseModel):
    label: str
    fact_key: Optional[str] = None    # preferred: resolve from the fact table
    value: Optional[str] = None       # literal, for the rare non-fact tile
    emphasis: Emphasis = "none"


class TilesBlock(BaseModel):
    kind: Literal["tiles"] = "tiles"
    block_id: str
    tiles: list[Tile] = Field(default_factory=list)


class TableBlock(BaseModel):
    kind: Literal["table"] = "table"
    block_id: str
    title: Optional[str] = None
    columns: list[Column] = Field(default_factory=list)
    #: Materialised rows. Empty when `query` is set.
    rows: list[list[Cell]] = Field(default_factory=list)
    query: Optional[EntityQuery] = None
    #: How many rows a *narrative* renderer shows before saying "showing N of M".
    #: The workbook ignores it — a dashboard that truncates is a broken dashboard.
    row_limit: Optional[int] = None
    note: Optional[str] = None

    @property
    def is_derived(self) -> bool:
        return self.query is not None


class ChartBlock(BaseModel):
    kind: Literal["chart"] = "chart"
    block_id: str
    #: A key into `charts_registry.CHART_BUILDERS`, never an attribute name.
    #: `getattr(charts, name)` on a model-influenced string would be an
    #: arbitrary-call primitive; an explicit dict is not.
    builder: str
    caption: Optional[str] = None


Block = Annotated[
    Union[ProseBlock, BulletsBlock, TilesBlock, TableBlock, ChartBlock],
    Field(discriminator="kind"),
]


# ------------------------------------------------------------------ sections
class Section(BaseModel):
    """One slide, one sheet, one chapter — depending on who is rendering."""

    section_id: str                   # stable across versions: "risks.critical"
    label: str                        # the section's name ("Critical risks")
    #: §12.5's management message: states the finding, not the topic. "Risks"
    #: tells a reader nothing; "Two critical risks are unmitigated" tells them
    #: what to do.
    headline: str
    blocks: list[Block] = Field(default_factory=list)

    #: Which audiences this section belongs to. Empty means "every audience".
    audiences: list[Audience] = Field(default_factory=list)
    #: Position in the narrative. `None` means the section exists in the data
    #: dump (the workbook) but is not part of any deck.
    narrative_order: Optional[int] = None

    origin: Literal["planner", "user"] = "planner"
    #: Survives a re-plan after the underlying analysis changes.
    locked: bool = False

    #: Shown instead of an empty table. "No critical risks" and "nobody told us
    #: about the risks" are different claims and must not render identically.
    empty_explanation: Optional[str] = None

    def for_audience(self, audience: Audience) -> bool:
        return not self.audiences or audience in self.audiences


class ContentProvenance(BaseModel):
    """How this version came to exist — the audit trail for a revision."""

    created_by: Literal["planner", "llm_revision", "user_revision", "revert"] = "planner"
    instruction: Optional[str] = None
    applied: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    reverted_from: Optional[int] = None


class ReportContent(BaseModel):
    """The whole report, renderer-agnostic and previewable as text."""

    schema_version: int = 1
    session_id: str
    version: int = 1
    parent_version: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)

    #: Cheap hash of the analysis this was planned from. If it stops matching,
    #: the analysis moved underneath us — a conflict was resolved, say — and the
    #: stored content may now state a figure that is no longer true.
    analysis_fingerprint: str = ""

    audience: Audience
    topic: str = "status"
    title: str
    subtitle: str = ""
    meta_line: list[str] = Field(default_factory=list)
    footer: str = ""

    sections: list[Section] = Field(default_factory=list)
    facts: FactTable = Field(default_factory=FactTable)

    provenance: ContentProvenance = Field(default_factory=ContentProvenance)
    warnings: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------ projections
    def narrative(self) -> list[Section]:
        """The audience's report: filtered and ordered.

        Deck, document, PDF, HTML and the text preview all read this. The
        workbook deliberately does not — §13 is a data dump of every sheet
        regardless of audience, and forcing it through this filter would either
        drop sheets the spec requires or hollow the filter out for everyone else.
        """
        chosen = [
            s for s in self.sections
            if s.narrative_order is not None and s.for_audience(self.audience)
        ]
        return sorted(chosen, key=lambda s: s.narrative_order or 0)

    def section(self, section_id: str) -> Optional[Section]:
        return next((s for s in self.sections if s.section_id == section_id), None)

    def numeric_corpus_cached(self) -> set[str]:
        """Every figure this report may state, including ones already written
        into deterministic table cells and headlines.

        Wider than `FactTable.numeric_corpus()` on purpose: the planner writes
        computed sentences ("2 milestone(s) have slipped") and table cells
        ("+15d") whose numbers are just as real as a fact's, and rejecting a
        rephrase for reusing one of them would be nonsense.
        """
        corpus = self.facts.numeric_corpus()
        for section in self.sections:
            corpus |= _numbers_in(section.headline)
            corpus |= _numbers_in(section.label)
            for block in section.blocks:
                corpus |= _block_numbers(block)
        return corpus


def _block_numbers(block) -> set[str]:
    found: set[str] = set()
    kind = getattr(block, "kind", None)
    if kind == "bullets":
        for item in block.items:
            if item.authored_by == "planner":
                found |= _numbers_in(item.text)
    elif kind == "prose" and block.authored_by == "planner":
        found |= _numbers_in(block.text)
    elif kind == "tiles":
        for tile in block.tiles:
            found |= _numbers_in(tile.value or "")
    elif kind == "table":
        for row in block.rows:
            for cell in row:
                found |= _numbers_in(cell.text)
    return found
