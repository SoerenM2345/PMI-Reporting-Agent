"""The project store's data models.

Kept apart from the repositories so the repository *protocols* can be typed against
these without importing any storage implementation, and so a future SQLite backend
reuses the exact same shapes.

Two families live here:

* **File tracking** — `FileRecord`, the per-file ingestion state that makes
  extraction incremental (skip an unchanged hash) and removals non-destructive
  (soft delete, correction #6).
* **Project knowledge** — `ProjectKnowledge`, the versioned canonical state. Its
  entities/facts/conflicts/validation_issues are a *projection* of an embedded
  `PMIDataModel` (the existing, tested entity model is reused, not reinvented);
  confirmed facts, assumptions, and open questions are three separate stores
  (correction #3) so a user's certainty is never conflated with a guess.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.pmi import DataQualityReport, PMIDataModel

# --- input taxonomy (corrections #1, #2, #4, #5) -------------------------------
# Fact-bearing inputs that may update canonical knowledge.
KnowledgeSourceType = Literal[
    "uploaded_file", "user_correction", "manual_entry",
    "conflict_resolution", "confirmed_user_fact",
]
# Audit-only inputs — transcript / audit trail, never canonical knowledge.
AuditEventType = Literal[
    "user_message", "generated_draft", "draft_edit", "draft_export",
]
# How a chat message is classified before it is allowed to touch knowledge.
MessageContribution = Literal[
    "no_knowledge_change", "new_fact", "correction",
    "decision", "assumption", "instruction",
]
# Certainty/authority of a user-supplied value. Only "confirmed" auto-supersedes.
UserInputAuthority = Literal["confirmed", "proposed", "uncertain", "scenario_only"]
# Where a fact applies. "scenario" never touches canonical project knowledge.
KnowledgeScope = Literal["project_canonical", "chat_local", "draft_local", "scenario"]

ExtractionStatus = Literal["pending", "completed", "failed", "needs_review"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- events (correction #1: knowledge is separated from audit) -----------------
class SourceEvent(BaseModel):
    """A fact-bearing input that *may* update canonical knowledge.

    Only these five `KnowledgeSourceType`s ever reach the knowledge base; a
    message that is merely a question or a formatting request is an `AuditEvent`,
    never a source. `authority` and `scope` decide *how* a source lands: only a
    `confirmed`, `project_canonical` source auto-supersedes a file value.
    """

    source_id: str
    project_id: str
    chat_id: Optional[str] = None
    type: KnowledgeSourceType
    created_at: str = Field(default_factory=_now)
    content: str = ""
    authority: UserInputAuthority = "confirmed"
    scope: KnowledgeScope = "project_canonical"
    #: The message-classification verdict, when this source came from a chat turn.
    contribution: Optional[MessageContribution] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """An input recorded for the trail but never treated as project knowledge:
    an ordinary user message, a generated draft, a draft edit, an export."""

    event_id: str
    project_id: str
    chat_id: Optional[str] = None
    type: AuditEventType
    created_at: str = Field(default_factory=_now)
    content: str = ""
    contribution: Optional[MessageContribution] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- file tracking -------------------------------------------------------------
class FileRecord(BaseModel):
    """One uploaded file's ingestion state (spec §"Incremental Ingestion").

    `content_hash` is what makes ingestion incremental: an unchanged hash means the
    cached `records/<file_id>.json` is reused and the (possibly paid, possibly
    non-deterministic) extractor is not re-run.

    A removed file is marked inactive rather than deleted (correction #6): rebuild
    ignores it, but its record and provenance survive so an old knowledge version
    that cited it can still be explained.
    """

    file_id: str
    file_name: str
    content_hash: str
    uploaded_at: str = Field(default_factory=_now)
    extraction_status: ExtractionStatus = "pending"
    #: Number of extracted records, for quick display without loading the cache.
    record_count: int = 0
    #: The knowledge version this file first contributed to. None until a rebuild
    #: has run that included it.
    knowledge_version_added: Optional[int] = None
    #: Why an extraction failed, surfaced to the data-quality report — never a
    #: silent drop (§21.17).
    error: Optional[str] = None

    active: bool = True
    status: Literal["active", "removed"] = "active"
    removed_at: Optional[str] = None


# --- project knowledge ---------------------------------------------------------
class ConfirmedFact(BaseModel):
    """A value the user asserted as true, with its authority and scope.

    Populated in 1B; defined here so the knowledge schema is stable from 1A and a
    version written now round-trips a version written later.
    """

    fact_id: str
    text: str
    field: Optional[str] = None
    value: Any = None
    authority: UserInputAuthority = "confirmed"
    scope: KnowledgeScope = "project_canonical"
    source_id: Optional[str] = None
    at: str = Field(default_factory=_now)


class Assumption(BaseModel):
    """Something the report leans on that no source confirmed. Never a fact."""

    assumption_id: str
    text: str
    scope: KnowledgeScope = "project_canonical"
    at: str = Field(default_factory=_now)


class OpenQuestion(BaseModel):
    """A proposed/uncertain value kept *alongside* the current one, flagged for
    review rather than allowed to supersede it (correction #5)."""

    question_id: str
    text: str
    field: Optional[str] = None
    proposed_value: Any = None
    current_value: Any = None
    authority: UserInputAuthority = "proposed"
    source_id: Optional[str] = None
    at: str = Field(default_factory=_now)


class UserDecision(BaseModel):
    """A decision that must survive a rebuild: a conflict resolution or a confirmed
    value. Re-applied onto the freshly derived model so re-reading the files never
    silently un-resolves what the user already settled."""

    decision_id: str
    kind: Literal["conflict_resolution", "confirmed_value"]
    #: For a conflict resolution: the conflict_id and the chosen source/value.
    #: For a confirmed value: the entity/field and the value. Free-form so 1B can
    #: fill it without a schema migration.
    detail: dict[str, Any] = Field(default_factory=dict)
    at: str = Field(default_factory=_now)


class ChangeLogEntry(BaseModel):
    """What changed between two knowledge versions — the basis for stale-draft
    detection (dependency tracking arrives in 1C)."""

    version: int
    at: str = Field(default_factory=_now)
    trigger: str = ""
    added_entities: list[str] = Field(default_factory=list)
    removed_entities: list[str] = Field(default_factory=list)
    changed_entities: list[str] = Field(default_factory=list)
    added_files: list[str] = Field(default_factory=list)
    removed_files: list[str] = Field(default_factory=list)
    note: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.added_entities or self.removed_entities
                    or self.changed_entities or self.added_files
                    or self.removed_files)


DraftStatus = Literal["draft", "reviewed", "approved", "stale", "potentially_stale"]


class Dependencies(BaseModel):
    """What a draft section was built from (correction #7).

    Tracking more than source ids is what lets staleness be *precise*: a change to
    one milestone should stale only the sections that used it. `fact_ids` and
    `calculation_ids` cannot be resolved against the entity-level change log, so a
    section that declares them is treated conservatively — see `drafts.py`.
    """

    source_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.source_ids or self.entity_ids or self.fact_ids
                    or self.calculation_ids)

    @property
    def only_resolvable(self) -> bool:
        """True when every declared dependency is one we can check against the
        change log (entities, sources) — no unresolvable fact/calculation ids."""
        return not (self.fact_ids or self.calculation_ids)


class DraftSection(BaseModel):
    """One editable section of a draft.

    `content` is free-text Markdown the user may rewrite directly. `depends_on`
    and `based_on_knowledge_version` drive *per-section* staleness (correction #7):
    regenerating one section refreshes only its base and dependencies, so a change
    that stales section A never un-stales — or re-stales — an untouched section B.
    `origin` records whether the section's current text came from the planner or a
    user edit, so a regenerate can respect a hand-written section.
    """

    section_id: str
    heading: str = ""
    content: str = ""
    depends_on: Dependencies = Field(default_factory=Dependencies)
    based_on_knowledge_version: int = 0
    stale: bool = False
    origin: Literal["assistant", "user"] = "assistant"


class DraftRecord(BaseModel):
    """A report draft: free-text Markdown, versioned, editable.

    `content` is the whole draft as one Markdown document (what "copy all" returns);
    `sections` is the same content split for section-level edit/regenerate and for
    staleness. A draft is never rewritten by the system — only *flagged* — so a user
    edit is never silently overwritten (correction #7, spec "never silently replace").
    """

    draft_id: str
    project_id: str
    chat_id: Optional[str] = None
    title: str = "Untitled draft"
    draft_type: str = "custom"
    #: The draft's editable form. Always Markdown — that is what the user reads
    #: and edits.
    format: Literal["markdown"] = "markdown"
    #: What it was planned to be *delivered* as, which shapes how many pages it
    #: has and how dense they are: a one-page PDF brief and a twelve-slide deck
    #: are not the same document even from the same evidence.
    target_format: Literal["pptx", "docx", "pdf", "html"] = "pptx"
    audience: Optional[str] = None
    audience_label: str = ""
    content: str = ""
    sections: list[DraftSection] = Field(default_factory=list)
    based_on_knowledge_version: int = 0
    #: The planned `Deliverable` this draft was derived from, so an export can
    #: render the real artifact rather than re-parsing the draft's Markdown.
    #: Optional so drafts written before the planning engine still load.
    deliverable_id: Optional[str] = None
    deliverable_version: Optional[int] = None
    status: DraftStatus = "draft"
    version: int = 0
    created_by: Literal["assistant", "user"] = "assistant"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class DraftVersionInfo(BaseModel):
    """One entry in a draft's history — cheap to list without loading content."""

    version: int
    status: DraftStatus
    based_on_knowledge_version: int
    created_by: str
    updated_at: str


class ProjectKnowledge(BaseModel):
    """The canonical, versioned project state.

    `data_model` is the embedded `PMIDataModel` — the reused entity/fact/conflict
    store. The spec's flat `entities`/`facts`/`conflicts`/`validation_issues` are
    projections of it (see properties below), so there is exactly one copy of each
    fact and it is the typed one the rest of the pipeline already understands.
    """

    project_id: str
    version: int = 0
    updated_at: str = Field(default_factory=_now)

    data_model: PMIDataModel = Field(default_factory=PMIDataModel)
    quality_report: Optional[DataQualityReport] = None

    confirmed_user_facts: list[ConfirmedFact] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    user_decisions: list[UserDecision] = Field(default_factory=list)
    #: A report outline imported from or set in any project chat.  It is typed
    #: data because generation must enforce it; leaving it only in a transcript
    #: would make compaction able to forget the user's requested structure.
    requested_structure: list[str] = Field(default_factory=list)

    #: One entry per active contributing source (file today, events in 1B).
    source_index: list[dict[str, Any]] = Field(default_factory=list)
    change_log: list[ChangeLogEntry] = Field(default_factory=list)

    # ------------------------------------------------------------- projections
    @property
    def conflicts(self):
        return self.data_model.conflicts

    @property
    def validation_issues(self):
        return self.data_model.validation_issues

    def entity_count(self) -> int:
        return self.data_model.entity_count()
