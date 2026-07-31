"""Everything a deliverable is generated *from*, in one object.

The old pipeline lost the request. `planner.plan()` had no parameter for it, so
sections came from a fixed per-audience table and the user's words survived only
as a section-title hint. Meanwhile the project's own context — the free text a
user pins to a project, their confirmed facts, their assumptions — reached no
prompt at all: `chat_store.Project.knowledge` had no consumer outside CRUD, and
`KnowledgeBase.digest()`, which exists to render exactly that for a prompt, had
zero callers.

A `GenerationContext` is built once per deliverable and passed to every stage:
request interpretation, storyline, section drafting, titles, visuals, rendering
and review. If the merging companies are named in project context, every one of
those stages can see it — which is the whole reason a deck stops being called
"PMI Project".

Two conventions worth stating:

* **`user_request` is verbatim and `request_history` keeps the rest.** The old
  code made the *first* turn's phrasing sticky, so refining an ask on turn four
  changed nothing.
* **`project_context` is untrusted text.** It is the user's own free text and it
  goes into prompts. It is fenced as data, never as instruction, and the
  structural defences (closed schemas, no numeric fields, validated evidence
  ids) are what actually make that safe.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.model import EvidenceIndex
from app.models.quality import Conflict, DataQualityReport, ValidationIssue

ConstraintKind = Literal[
    "max_pages", "min_pages", "include_topic", "exclude_topic", "tone",
    "language", "must_cite", "no_charts", "must_chart", "deadline", "other",
]
GapSeverity = Literal["block", "warn", "note"]


class CompanyNames(BaseModel):
    acquirer: Optional[str] = None
    target: Optional[str] = None
    deal_name: Optional[str] = None

    @property
    def known(self) -> list[str]:
        return [n for n in (self.acquirer, self.target) if n]

    def as_phrase(self) -> str:
        """How to name the transaction in prose, using what is actually known."""
        if self.acquirer and self.target:
            return f"{self.acquirer} / {self.target}"
        return self.deal_name or self.acquirer or self.target or ""

    def as_sentence(self) -> str:
        if self.acquirer and self.target:
            return f"{self.acquirer} is integrating {self.target}."
        return ""


class TransactionContext(BaseModel):
    integration_phase: str = "unknown"
    integration_type: str = "unknown"
    signing_date: Optional[date] = None
    closing_date: Optional[date] = None
    day_1_date: Optional[date] = None
    #: Computed in Python against the reporting date. The model is never asked
    #: to work out how many days are left.
    days_to_day_1: Optional[int] = None

    @property
    def has_dates(self) -> bool:
        return any((self.signing_date, self.closing_date, self.day_1_date))


class UserConstraint(BaseModel):
    """A hard rule the user stated, preserved for the completeness critic."""

    kind: ConstraintKind
    value: str
    source: Literal["request", "project_knowledge", "confirmed_fact"] = "request"


class ContextGap(BaseModel):
    """Something missing, stated in the user's terms with a way forward."""

    gap_id: str
    severity: GapSeverity
    message: str
    remedy: str = ""


class ChatExcerpt(BaseModel):
    message_id: str = ""
    role: Literal["user", "assistant"] = "user"
    text: str = ""
    at: str = ""
    relevance: float = 0.0


class UserFact(BaseModel):
    """A value the user supplied, still attached to what it is about.

    The digest's `confirmed_facts` are sentences — "Payroll cutover: 2026-06-02"
    — and a sentence cannot be compared with anything. Projection minted them as
    `ev:user_fact:001` with no entity, no field and no value, so nothing in the
    system could tell that the user fact and `ev:milestone:M7` were about the
    same date. Two contradictory values could sit in the index, both blessed as
    factual, with BM25 deciding which the model saw.
    """

    entity_type: str = ""
    label: str = ""
    field: str = ""
    value: Optional[str] = None
    #: What the sources said before the user overruled them, when known.
    old_value: Optional[str] = None

    def as_statement(self) -> str:
        subject = self.label or self.entity_type or "this"
        field = (self.field or "value").replace("_", " ")
        said = self.value if self.value is not None else "not stated"
        sentence = f"The user states that the {field} of “{subject}” is {said}."
        if self.old_value and self.old_value != self.value:
            sentence += f" The files said {self.old_value}."
        return sentence


class KnowledgeDigest(BaseModel):
    """Both knowledge stores, projected into one shape.

    The session stack keeps a `KnowledgeBase`; the project stack keeps a
    `ProjectKnowledge`. Prompts should not have to know which one they are
    looking at, and neither should the evidence projection.
    """

    free_text: str = ""
    confirmed_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    #: Gaps the user declined to fill. Asking again is a nuisance, and asking in
    #: the artifact ("this was not provided") is worse.
    declined: list[str] = Field(default_factory=list)
    #: The same corrections as `confirmed_facts`, still attached to the entity
    #: and field they are about, so they can be *compared* with what the files
    #: say rather than merely appearing alongside it.
    confirmed_values: list[UserFact] = Field(default_factory=list)
    #: Section titles from a structure the user described in an earlier turn
    #: (§17), in their order. Typed rather than folded into `free_text`, because
    #: a structure has to be *enforced* — `enforce_coverage` needs a list, and a
    #: sentence inside a prompt is something a keyless run cannot act on at all.
    requested_structure: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.free_text or self.confirmed_facts or self.assumptions
                    or self.decisions or self.open_questions)

    def as_evidence_pairs(self) -> list[tuple[str, str]]:
        """`(origin, statement)` for `evidence.projection.project`."""
        pairs: list[tuple[str, str]] = []
        if self.free_text.strip():
            for line in _sentences(self.free_text):
                pairs.append(("project_context", line))
        pairs += [("user_confirmed", t) for t in self.confirmed_facts]
        pairs += [("user_confirmed", t) for t in self.decisions]
        pairs += [("user_assumption", t) for t in self.assumptions]
        return pairs

    def as_markdown(self) -> str:
        """For a prompt. Fenced as data by the caller, never as instruction."""
        blocks: list[str] = []
        if self.free_text.strip():
            blocks.append(f"### Project background (written by the user)\n"
                          f"{self.free_text.strip()}")
        for title, items in (("Confirmed facts", self.confirmed_facts),
                             ("Decisions taken", self.decisions),
                             ("Assumptions (not evidenced)", self.assumptions),
                             ("Open questions", self.open_questions)):
            if items:
                lines = "\n".join(f"- {item}" for item in items)
                blocks.append(f"### {title}\n{lines}")
        return "\n\n".join(blocks)


class GenerationContext(BaseModel):
    """The single object every generation stage receives."""

    model_config = ConfigDict(revalidate_instances="never")

    # --- identity
    scope: Literal["project", "session"] = "project"
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    chat_id: Optional[str] = None

    # --- who and what
    project_name: str = ""
    project_context: str = ""
    project_knowledge: KnowledgeDigest = Field(default_factory=KnowledgeDigest)
    company_names: CompanyNames = Field(default_factory=CompanyNames)
    transaction: TransactionContext = Field(default_factory=TransactionContext)
    reporting_period: str = ""
    reporting_date: Optional[date] = None

    # --- conversation
    chat_summary: str = ""
    relevant_chat_messages: list[ChatExcerpt] = Field(default_factory=list)

    # --- the ask, preserved
    user_request: str = ""
    request_history: list[str] = Field(default_factory=list)
    requested_output_format: Optional[str] = None
    requested_sections: list[str] = Field(default_factory=list)
    requested_visuals: list[str] = Field(default_factory=list)
    audience: Optional[str] = None
    user_constraints: list[UserConstraint] = Field(default_factory=list)

    # --- the ground
    evidence: EvidenceIndex = Field(default_factory=EvidenceIndex)
    conflicts: list[Conflict] = Field(default_factory=list)
    quality_issues: list[ValidationIssue] = Field(default_factory=list)
    quality_report: Optional[DataQualityReport] = None

    # --- the medium (set by the template registry; typed loosely to keep this
    # module free of a dependency on the renderer stack)
    template_reference: Optional[object] = None
    brand_system: Optional[object] = None

    gaps: list[ContextGap] = Field(default_factory=list)

    # ------------------------------------------------------------- accessors
    def blocking_gaps(self) -> list[ContextGap]:
        return [g for g in self.gaps if g.severity == "block"]

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocking_gaps())

    @property
    def unresolved_critical_conflicts(self) -> list[Conflict]:
        return [c for c in self.conflicts if c.requires_user_input]

    @property
    def has_evidence(self) -> bool:
        """Whether there is anything substantive to report on.

        Projection always emits the computed-fact scaffold, so an empty project
        still yields two dozen facts — half "Not Reported" and half genuine
        zeroes ("0 overdue tasks"). Those are arithmetic over nothing, and a
        document built from them would be a page of blanks and zeroes presenting
        itself as a status report.

        So the question is not "are there items" but "did anything come from a
        source or a person": a file was read, or the user told us something.
        """
        return any(item.origin not in ("absence", "computed_value")
                   for item in self.evidence)

    def display_name(self) -> str:
        """What to print. Always something; never a placeholder posing as a name."""
        return self.project_name or self.company_names.as_phrase() \
            or "Untitled integration report"

    def subject_line(self) -> str:
        """One line naming the transaction, for a cover or a title slide."""
        sentence = self.company_names.as_sentence()
        if sentence:
            return sentence
        return self.project_name or ""


def _sentences(text: str) -> list[str]:
    """Split free text into statements evidence can address individually."""
    import re

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    return [p for p in parts if len(p) > 3]
