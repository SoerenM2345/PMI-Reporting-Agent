"""Revision operations, and the only way content is ever edited.

The op vocabulary is the §11 guarantee made structural. Read the field list on
`ReviseOp`: there is nothing that can write a table cell, a tile value or a
fact. The type cannot express "change the variance to -400", so no prompt,
jailbreak or malformed response can produce that edit — it is not a matter of
the model behaving.

What a revision *can* do is select, reorder, and reword. Rewording is the one
place free text enters, so every authored string passes `guard.check_text`
before it is accepted.

Applying is pure: ops in, a new `ReportContent` out. Nothing here writes to
disk, and the input content is never mutated — the caller decides whether the
result becomes a version.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.report import guard
from app.report.content import (
    Bullet,
    BulletsBlock,
    ContentProvenance,
    ProseBlock,
    ReportContent,
    Section,
)

log = logging.getLogger("pmi.report.ops")

OpName = Literal[
    "reorder", "drop_section", "restore_section", "rewrite_headline",
    "rewrite_bullet", "add_bullet", "drop_bullet", "add_section",
    "set_row_limit", "set_emphasis",
]


class ReviseOp(BaseModel):
    """One edit. Deliberately anaemic — see the module docstring."""

    op: OpName
    section_id: Optional[str] = None
    #: Which bullet, for the bullet ops.
    index: Optional[int] = None
    #: New wording. Guarded before it is accepted.
    text: Optional[str] = None
    #: Full section order, for `reorder`.
    order: Optional[list[str]] = None
    #: For `add_section`: a title, plus prose-only content.
    label: Optional[str] = None
    row_limit: Optional[int] = None
    emphasis: Optional[str] = None


class ContentRevision(BaseModel):
    """What a revision request produces. Capped so one instruction cannot
    rewrite the entire report in a single turn."""

    ops: list[ReviseOp] = Field(default_factory=list, max_length=12)
    rationale: str = ""


class RejectedOp(BaseModel):
    op: str
    reason: str


class RevisionResult(BaseModel):
    content: Optional[ReportContent] = None
    applied: list[str] = Field(default_factory=list)
    rejected: list[RejectedOp] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def apply(
    content: ReportContent,
    revision: ContentRevision,
    *,
    instruction: str = "",
    author: Literal["llm_revision", "user_revision"] = "llm_revision",
) -> RevisionResult:
    """Apply `revision`, reporting everything accepted and everything refused.

    §21.17: nothing is dropped silently. If every op is rejected the result
    carries no content and all the reasons — the caller surfaces them rather
    than handing back the old version as though the request had succeeded.
    """
    draft = content.model_copy(deep=True)
    corpus = content.numeric_corpus_cached()

    applied: list[str] = []
    rejected: list[RejectedOp] = []

    for op in revision.ops:
        try:
            note = _apply_one(draft, op, corpus)
        except _Refused as refusal:
            rejected.append(RejectedOp(op=op.op, reason=str(refusal)))
            continue
        applied.append(note)

    if not applied:
        return RevisionResult(content=None, applied=[], rejected=rejected)

    draft.parent_version = content.version
    draft.provenance = ContentProvenance(
        created_by=author,
        instruction=instruction,
        applied=applied,
        rejected=[r.reason for r in rejected],
    )
    return RevisionResult(content=draft, applied=applied, rejected=rejected)


class _Refused(Exception):
    """Internal: this op will not be applied, and here is why."""


def _apply_one(draft: ReportContent, op: ReviseOp, corpus: set[str]) -> str:
    handler = _HANDLERS.get(op.op)
    if handler is None:
        raise _Refused(f"unknown operation {op.op!r}")
    return handler(draft, op, corpus)


def _guarded(text: Optional[str], corpus: set[str], what: str) -> str:
    if not text or not text.strip():
        raise _Refused(f"{what} requires text")
    offending = guard.check_text(text, corpus)
    if offending:
        raise _Refused(guard.describe(offending, text))
    return text.strip()


def _find(draft: ReportContent, op: ReviseOp) -> Section:
    if not op.section_id:
        raise _Refused("no section named")
    section = draft.section(op.section_id)
    if section is None:
        raise _Refused(f"no section {op.section_id!r} in this report")
    return section


# ------------------------------------------------------------------ handlers
def _reorder(draft: ReportContent, op: ReviseOp, _corpus) -> str:
    if not op.order:
        raise _Refused("reorder needs an order")
    known = {s.section_id for s in draft.sections}
    unknown = [sid for sid in op.order if sid not in known]
    if unknown:
        raise _Refused(f"unknown section(s): {', '.join(unknown)}")

    # Only sections already in the narrative can be positioned; a section that
    # was dropped stays dropped until explicitly restored.
    position = {sid: index for index, sid in enumerate(op.order)}
    for section in draft.sections:
        if section.narrative_order is not None and section.section_id in position:
            section.narrative_order = position[section.section_id] + 1
    return f"reordered {len(op.order)} section(s)"


def _drop_section(draft: ReportContent, op: ReviseOp, _corpus) -> str:
    section = _find(draft, op)
    if section.section_id == "quality.limitations":
        # §12.5 requires it, and a user removing the slide that says what the
        # report could not do is exactly the outcome that rule exists to stop.
        raise _Refused(
            "the data-quality section cannot be removed — it states what this "
            "report could not do, which every recipient is entitled to see"
        )
    if section.narrative_order is None:
        raise _Refused(f"{section.section_id!r} is not in the report")
    section.narrative_order = None
    return f"removed “{section.label}”"


def _restore_section(draft: ReportContent, op: ReviseOp, _corpus) -> str:
    section = _find(draft, op)
    if section.narrative_order is not None:
        raise _Refused(f"{section.section_id!r} is already in the report")
    highest = max((s.narrative_order or 0) for s in draft.sections)
    section.narrative_order = highest + 1
    return f"restored “{section.label}”"


def _rewrite_headline(draft: ReportContent, op: ReviseOp, corpus) -> str:
    section = _find(draft, op)
    section.headline = _guarded(op.text, corpus, "rewrite_headline")
    return f"retitled “{section.label}”"


def _rewrite_bullet(draft: ReportContent, op: ReviseOp, corpus) -> str:
    section = _find(draft, op)
    block = _bullets_block(section)
    if op.index is None or not 0 <= op.index < len(block.items):
        raise _Refused(f"no bullet {op.index} in “{section.label}”")
    block.items[op.index].text = _guarded(op.text, corpus, "rewrite_bullet")
    block.items[op.index].authored_by = "llm"
    return f"reworded bullet {op.index + 1} of “{section.label}”"


def _add_bullet(draft: ReportContent, op: ReviseOp, corpus) -> str:
    section = _find(draft, op)
    block = _bullets_block(section, create=True)
    block.items.append(Bullet(
        text=_guarded(op.text, corpus, "add_bullet"), authored_by="llm"
    ))
    return f"added a point to “{section.label}”"


def _drop_bullet(draft: ReportContent, op: ReviseOp, _corpus) -> str:
    section = _find(draft, op)
    block = _bullets_block(section)
    if op.index is None or not 0 <= op.index < len(block.items):
        raise _Refused(f"no bullet {op.index} in “{section.label}”")
    removed = block.items.pop(op.index)
    return f"removed “{removed.text[:40]}” from “{section.label}”"


def _add_section(draft: ReportContent, op: ReviseOp, corpus) -> str:
    """Prose only.

    A section whose *rows* came from a model would be data the report never
    extracted. New tables can only ever be a filtered view of entities we
    already hold, which is a planner job — so what a revision may add is
    commentary, and commentary goes through the guard like any other text.
    """
    if not op.label:
        raise _Refused("add_section needs a title")
    text = _guarded(op.text, corpus, "add_section")

    section_id = op.section_id or f"user.{len(draft.sections) + 1}"
    if draft.section(section_id) is not None:
        raise _Refused(f"section {section_id!r} already exists")

    highest = max((s.narrative_order or 0) for s in draft.sections)
    draft.sections.append(Section(
        section_id=section_id,
        label=op.label,
        headline=op.label,
        narrative_order=highest + 1,
        origin="user",
        locked=True,          # survives a re-plan; the user asked for it
        blocks=[ProseBlock(block_id=f"{section_id}.prose", text=text,
                           authored_by="llm")],
    ))
    return f"added “{op.label}”"


def _set_row_limit(draft: ReportContent, op: ReviseOp, _corpus) -> str:
    section = _find(draft, op)
    if op.row_limit is None or op.row_limit < 1:
        raise _Refused("row_limit must be at least 1")
    for block in section.blocks:
        if block.kind == "table":
            block.row_limit = op.row_limit
    return f"showing {op.row_limit} row(s) in “{section.label}”"


def _set_emphasis(draft: ReportContent, op: ReviseOp, _corpus) -> str:
    section = _find(draft, op)
    if op.emphasis not in ("none", "good", "warn", "bad", "muted"):
        raise _Refused(f"unknown emphasis {op.emphasis!r}")
    block = _bullets_block(section)
    if op.index is None or not 0 <= op.index < len(block.items):
        raise _Refused(f"no bullet {op.index} in “{section.label}”")
    block.items[op.index].emphasis = op.emphasis
    return f"changed emphasis in “{section.label}”"


def _bullets_block(section: Section, *, create: bool = False) -> BulletsBlock:
    block = next((b for b in section.blocks if b.kind == "bullets"), None)
    if block is None:
        if not create:
            raise _Refused(f"“{section.label}” has no bullet list to edit")
        block = BulletsBlock(block_id=f"{section.section_id}.bullets")
        section.blocks.append(block)
    return block


_HANDLERS = {
    "reorder": _reorder,
    "drop_section": _drop_section,
    "restore_section": _restore_section,
    "rewrite_headline": _rewrite_headline,
    "rewrite_bullet": _rewrite_bullet,
    "add_bullet": _add_bullet,
    "drop_bullet": _drop_bullet,
    "add_section": _add_section,
    "set_row_limit": _set_row_limit,
    "set_emphasis": _set_emphasis,
}
