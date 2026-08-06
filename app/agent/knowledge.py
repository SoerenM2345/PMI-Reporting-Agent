"""What the *session* knows, as opposed to what the *files* said.

`analysis.json` is the source of truth for extracted data and stays that way.
This is the other half: the audience the user named, the structure they asked
for, the values they supplied, the gaps they declined, what has been generated
so far. None of that is in any file, and none of it survived a turn before this
existed — `pending.json` held one pointer, and the transcript is explicitly not
the source of truth (see `budget.py`, which may compact it away). So the agent
asked for the same thing twice, which reads as not listening.

**Structured JSON is canonical; the Markdown digest is derived from it.** JSON is
what code can validate and apply — types, provenance, a revision counter — and
Markdown is only a projection for prompting. Storing the prose and parsing it
back would let the two disagree, and the one a model reads would be the one
nobody checked.

Nothing lives *only* here. Every `UserValue` is also written into the data model
through `corrections.apply_and_persist`, so the report is built from the model
exactly as it always was; the KB records that the user is where the value came
from, and what has already been asked.

    storage_data/<session>/knowledge.json
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.pmi import Audience
from app.storage.json_store import session_dir

log = logging.getLogger("pmi.knowledge")


def _as_text(value: Any) -> Optional[str]:
    """A value as the user would read it back, or `None` for missing."""
    if value is None:
        return None
    if isinstance(value, date):
        return f"{value:%d-%m-%Y}"
    return str(value)


class EntityRef(BaseModel):
    """One entity, by type and id — what the agent last talked about."""

    entity_type: str
    entity_id: Optional[str] = None
    label: str = ""
    field: Optional[str] = None


class UserValue(BaseModel):
    """A value the user supplied, with its provenance.

    `raw` is what they typed; `value` is what was written after coercion. Keeping
    both means a rejected re-read ("12-08-2026" parsed as a date) can be
    explained in the user's own terms rather than ours — and it is what makes
    the value **replayable**: re-extraction builds a brand-new model from the
    files, and `raw` is re-coerced against the live field each time.

    `label` is load-bearing for the same reason. Entity ids are reassigned by
    every `standardize`, so `entity_id` cannot survive a re-read; the entity is
    found again by `(type, label)`, which is the rule
    `app/project/rebuild.py::_apply_confirmed_values` already follows.
    """

    entity_type: str
    entity_id: Optional[str] = None
    label: str = ""
    field: str
    value: Any = None
    raw: str = ""
    #: What the files said before the user overruled them. Kept so a correction
    #: can be explained, undone, and shown as *superseding* something rather
    #: than as having appeared from nowhere.
    old_value: Optional[str] = None
    #: Where the correction came from: a chat sentence, a preview cell, a gap
    #: answer. Different surfaces, one durable record.
    source: str = "chat"
    when: datetime = Field(default_factory=datetime.now)


class GeneratedOutput(BaseModel):
    """A file this session produced, so "regenerate" knows what to rebuild."""

    format: str
    content_version: Optional[int] = None
    files: list[str] = Field(default_factory=list)
    when: datetime = Field(default_factory=datetime.now)


class RemovedPage(BaseModel):
    """A page the user took out of the report, named three ways.

    A removal has to survive a re-plan, and a re-plan is exactly what loses the
    identity: `page_id` comes from the design and may be reassigned, `title` is
    rewritten each time, and `section_id` is stable only for the sections Python
    appends itself. Any one of the three matching is treated as the same page —
    the cost of a false positive is a page the user asked to lose staying lost,
    which is what they asked for, and it is restorable either way.
    """

    page_id: str = ""
    section_id: str = ""
    title: str = ""

    def matches(self, page) -> bool:
        return bool(
            (self.page_id and self.page_id == page.page_id)
            or (self.section_id and self.section_id == getattr(page, "section_id", ""))
            or (self.title and self.title.casefold()
                == (page.title or "").casefold()))


class KnowledgeBase(BaseModel):
    session_id: str
    #: Bumped on every write — the KB's own version, for logging and debugging.
    revision: int = 0
    #: Bumped only by writes that change **what the report says**: the audience,
    #: the structure, a project field, a supplied value. This is what the report
    #: fingerprint reads, so those leave a drafted report stale and force a
    #: re-plan before it renders — the same discipline that already covers a
    #: resolved conflict.
    #:
    #: Bookkeeping deliberately does not count. Remembering which entity the
    #: agent just mentioned changes nothing a reader would see, and staling the
    #: draft for it would make every gap question invalidate the very report the
    #: user is reading.
    content_revision: int = 0

    audience: Optional[Audience] = None
    audience_label: str = ""
    #: A user-defined report structure (§17), when one was detected. Typed as a
    #: dict here so `report.structure` can own the schema without this module
    #: importing it — the KB is storage, not planning.
    structure: Optional[dict] = None

    #: Project-level facts no file states: reporting date, Day 1, deal names.
    project_fields: dict[str, Any] = Field(default_factory=dict)
    user_values: list[UserValue] = Field(default_factory=list)

    #: Prose the user rewrote in the preview, keyed by the block's stable id
    #: ("summary.bullets", "next_steps.bullets"). Stored here rather than only in
    #: the content version so it survives a re-plan: a re-plan rebuilds every
    #: block from the model, and without this the user's wording would be
    #: silently discarded the next time a due date changed. The planner re-applies
    #: it, so the override is authoritative over whatever the planner wrote.
    #: Figures are validated before an override is stored (`guard.check_text`), so
    #: nothing here can smuggle a number past §11.
    prose_overrides: dict[str, str] = Field(default_factory=dict)

    #: Pages the user asked to take out, for the same reason `prose_overrides`
    #: exists: a re-plan rebuilds the document from the model and would put them
    #: straight back. Asking for the report in a second format re-plans, so
    #: without this "remove the data quality page" held for the deck the user was
    #: looking at and silently lapsed in the Word version of it.
    removed_pages: list[RemovedPage] = Field(default_factory=list)

    #: Gap keys already answered or explicitly skipped, so the same question is
    #: never asked twice across turns.
    answered_gaps: list[str] = Field(default_factory=list)
    declined_gaps: list[str] = Field(default_factory=list)

    #: What the agent last named. A bare "The deadline is 12-08-2026." resolves
    #: against this — without it the sentence refers to nothing and the turn
    #: dead-ends in "I didn't change anything."
    focus: Optional[EntityRef] = None

    outputs: list[GeneratedOutput] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------- projection
    def digest(self) -> str:
        """The KB as Markdown, for injection into a prompt.

        Derived, never stored: there is exactly one copy of each fact and it is
        the typed one above.
        """
        lines: list[str] = []

        if self.audience:
            who = self.audience_label or self.audience.value
            lines.append(f"- Audience: {who} (report shape: {self.audience.value})")
        if self.structure:
            titles = [s.get("title", "") for s in self.structure.get("sections", [])]
            if titles:
                lines.append("- Requested structure: " + " → ".join(titles))
        for key, value in self.project_fields.items():
            lines.append(f"- {key.replace('_', ' ').capitalize()}: {value}")
        for supplied in self.user_values[-12:]:
            lines.append(
                f"- {supplied.label or supplied.entity_id} "
                f"{supplied.field.replace('_', ' ')} = {supplied.raw} "
                f"(supplied by the user)"
            )
        if self.declined_gaps:
            lines.append(f"- {len(self.declined_gaps)} gap(s) the user chose to "
                         f"leave blank — do not ask about them again.")
        if self.focus:
            lines.append(f"- Currently discussing: {self.focus.label or ''} "
                         f"({self.focus.entity_type})")
        for output in self.outputs[-4:]:
            lines.append(f"- Already generated: {output.format} "
                         f"({', '.join(output.files) or 'no files recorded'})")
        for note in self.notes[-6:]:
            lines.append(f"- {note}")

        if not lines:
            return ""
        return ("The user has already told me the following. Do not ask for any "
                "of it again:\n" + "\n".join(lines))

    # ---------------------------------------------------------------- writers
    # Each returns `self` so a caller can chain and save once. None of them
    # writes to disk — `save()` is always explicit, so a read-only inspection
    # cannot bump the revision and invalidate a perfectly good draft.
    def set_audience(self, audience: Optional[Audience], label: str = "") -> "KnowledgeBase":
        if audience is not None:
            self.audience = audience
        if label:
            self.audience_label = label
        self.content_revision += 1
        return self

    def record_value(self, value: UserValue) -> "KnowledgeBase":
        """Remember one supplied value, replacing any earlier one for the field.

        Matched on `(entity_type, label, field)`, not on `entity_id`: ids are
        reassigned by every `standardize`, so keying on one meant a second
        correction to the same field after a re-read appended a *new* row
        instead of replacing the old one — leaving two live values for one field
        and no way to tell which was current.

        The replaced value's own `value` becomes the new one's `old_value` when
        the caller did not supply one, so the chain of what superseded what
        survives without every call site having to remember it.
        """
        superseded = [
            v for v in self.user_values
            if v.entity_type == value.entity_type
            and v.field == value.field
            and (v.label or "") == (value.label or "")
        ]
        if superseded and value.old_value is None:
            value.old_value = _as_text(superseded[-1].value)

        self.user_values = [v for v in self.user_values if v not in superseded]
        self.user_values.append(value)
        self.content_revision += 1
        return self

    def set_prose_override(self, block_id: str, text: str) -> "KnowledgeBase":
        """Remember the user's wording for one block. Changes what the report
        says, so it counts towards the content revision and leaves any drafted
        report stale until it is re-planned with the override applied."""
        self.prose_overrides[block_id] = text
        self.content_revision += 1
        return self

    def record_project_field(self, field: str, value: Any) -> "KnowledgeBase":
        self.project_fields[field] = value
        self.content_revision += 1
        return self

    def answer_gap(self, key: str) -> "KnowledgeBase":
        if key and key not in self.answered_gaps:
            self.answered_gaps.append(key)
        # An answered gap is no longer declined.
        self.declined_gaps = [k for k in self.declined_gaps if k != key]
        return self

    def decline_gap(self, key: str) -> "KnowledgeBase":
        if key and key not in self.declined_gaps:
            self.declined_gaps.append(key)
        return self

    def set_focus(self, ref: Optional[EntityRef]) -> "KnowledgeBase":
        self.focus = ref
        return self

    def record_output(self, output: GeneratedOutput) -> "KnowledgeBase":
        self.outputs.append(output)
        return self

    def note(self, text: str) -> "KnowledgeBase":
        if text and text not in self.notes:
            self.notes.append(text)
        return self


# ------------------------------------------------------------------ storage
def _path(session_id: str):
    return session_dir(session_id) / "knowledge.json"


def load(session_id: str) -> KnowledgeBase:
    """The session's knowledge, or an empty one.

    Never `None` and never raises: a KB that cannot be read is a session that
    has forgotten what it was told, which is bad, but a 500 in the middle of a
    conversation is worse. The loss is logged rather than swallowed silently.
    """
    path = _path(session_id)
    if not path.is_file():
        return KnowledgeBase(session_id=session_id)
    try:
        return KnowledgeBase.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:                                  # noqa: BLE001
        log.warning("knowledge for %s is unreadable (%s); starting fresh",
                    session_id, exc)
        return KnowledgeBase(session_id=session_id)


def save(kb: KnowledgeBase) -> KnowledgeBase:
    """Write the KB and bump its revision.

    `content_revision` is bumped by the writers themselves, not here, precisely
    so that saving the KB after a bookkeeping change does not invalidate a
    drafted report. What *does* invalidate it — a supplied value, a chosen
    audience, a requested structure — is what `report.store.fingerprint` reads,
    so the user telling us something forces a re-plan before the report renders.
    Re-planning costs no extraction and no LLM call when the summary bullets are
    reused, and the alternative — a report that looks current while stating a
    value the user has since corrected — is the worst output this system can
    produce.
    """
    kb.revision += 1
    directory = session_dir(kb.session_id)
    directory.mkdir(parents=True, exist_ok=True)
    _path(kb.session_id).write_text(kb.model_dump_json(indent=2), encoding="utf-8")
    return kb


def content_revision(session_id: str) -> int:
    """The content revision alone, without validating the whole model.

    `fingerprint` is called on every staleness check, including inside render
    paths; parsing the full KB there would make a hot path pay for a feature it
    does not use.
    """
    path = _path(session_id)
    if not path.is_file():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))
                   .get("content_revision", 0))
    except Exception:                                         # noqa: BLE001
        return 0
