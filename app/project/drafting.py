"""Create and edit report drafts (spec §"Editable Draft Model", Phase 2).

A draft is the report as *editable free text*: the user reads it, edits a section
directly, asks the agent to rewrite another, and only exports when they choose to.
It is planned once from project knowledge and then owned by the user — the system
flags it when knowledge moves (Phase 1C) but never rewrites it.

Reuse, not reinvention: the section structure, titles and figures come from
`report/planner.py` (the same plan every format uses, so a draft cannot disagree
with an eventual deck), rendered to Markdown by `report/render/markdown.py`. Each
section records what it depended on, so a later change stales only the sections it
touched, and a regenerate refreshes one section without disturbing the rest.

Drafts are **audit, not knowledge** (correction #1): creating, editing and
exporting a draft logs an `AuditEvent` and never alters the knowledge base. A
factual correction is made by *messaging* the agent (`facts.record_message`), not
by editing prose.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.models.pmi import Audience
from app.project.json_repositories import Repositories, default_repositories
from app.project.models import (
    AuditEvent,
    Dependencies,
    DraftRecord,
    DraftSection,
    ProjectKnowledge,
)

log = logging.getLogger("pmi.project.drafting")


class DraftError(RuntimeError):
    """A draft operation could not proceed (no knowledge yet, unknown section)."""


def _uid() -> str:
    return f"draft_{uuid.uuid4().hex[:10]}"


# ------------------------------------------------------------------ create
def create_draft(project_id: str, *, audience: Optional[str] = None,
                 audience_label: str = "", title: Optional[str] = None,
                 draft_type: str = "custom", chat_id: Optional[str] = None,
                 repos: Optional[Repositories] = None) -> DraftRecord:
    """Plan a fresh draft from current project knowledge."""
    repos = repos or default_repositories()
    knowledge = repos.knowledge.current(project_id)
    if knowledge is None or knowledge.entity_count() == 0:
        raise DraftError("There is nothing to draft yet — add project files first.")

    content = _plan(knowledge, audience, audience_label)
    draft = DraftRecord(
        draft_id=_uid(), project_id=project_id, chat_id=chat_id,
        title=title or content.title, draft_type=draft_type,
        audience=(audience or Audience.PMO.value), audience_label=audience_label,
        based_on_knowledge_version=knowledge.version, created_by="assistant",
        sections=_sections_from_content(content, knowledge),
    )
    draft.content = _assemble(draft)
    repos.drafts.commit(draft)
    _audit(repos, project_id, chat_id, "generated_draft",
           f"Drafted “{draft.title}”", draft.draft_id)
    log.info("project %s: drafted %s (v%d) from knowledge v%d", project_id,
             draft.draft_id, draft.version, knowledge.version)
    return draft


# ------------------------------------------------------------------ edit
def edit_draft(project_id: str, draft_id: str, *, title: Optional[str] = None,
               content: Optional[str] = None, chat_id: Optional[str] = None,
               repos: Optional[Repositories] = None) -> DraftRecord:
    """A direct user edit of the whole draft (title and/or full text) → new version.

    A full-text replace is stored verbatim as the user's; the section structure is
    retained for staleness and regeneration, but the sections are marked user-owned
    so a later regenerate does not quietly discard hand-written prose.
    """
    repos = repos or default_repositories()
    draft = _require(repos, project_id, draft_id)
    if title is not None:
        draft.title = title
    if content is not None:
        draft.content = content
        for section in draft.sections:
            section.origin = "user"
    draft.created_by = draft.created_by  # unchanged; the edit is a new version
    repos.drafts.commit(draft)
    _audit(repos, project_id, chat_id, "draft_edit", "Edited the draft", draft_id)
    return draft


def edit_section(project_id: str, draft_id: str, section_id: str, text: str, *,
                 chat_id: Optional[str] = None,
                 repos: Optional[Repositories] = None) -> DraftRecord:
    """A direct user edit of one section → new version, the rest untouched."""
    repos = repos or default_repositories()
    draft = _require(repos, project_id, draft_id)
    section = _section(draft, section_id)
    section.content = text
    section.origin = "user"
    draft.content = _assemble(draft)
    repos.drafts.commit(draft)
    _audit(repos, project_id, chat_id, "draft_edit",
           f"Edited section “{section.heading or section_id}”", draft_id)
    return draft


# ------------------------------------------------------------- regenerate
def regenerate_section(project_id: str, draft_id: str, section_id: str, *,
                       chat_id: Optional[str] = None,
                       repos: Optional[Repositories] = None) -> DraftRecord:
    """Re-plan a single section from current knowledge, preserving every other one.

    Only the named section's text, dependencies and staleness base move; a
    hand-edited section elsewhere is left exactly as the user wrote it (Scenario 3).
    """
    repos = repos or default_repositories()
    draft = _require(repos, project_id, draft_id)
    section = _section(draft, section_id)

    knowledge = repos.knowledge.current(project_id)
    if knowledge is None:
        raise DraftError("No project knowledge to regenerate from.")

    content = _plan(knowledge, draft.audience, draft.audience_label)
    planned = content.section(section_id)
    if planned is None:
        raise DraftError(
            f"Section “{section_id}” is not part of the current plan, so there is "
            f"nothing to regenerate it from.")

    section.content = _render_section(planned, content)
    section.heading = planned.headline
    section.depends_on = _dependencies(planned, knowledge)
    section.based_on_knowledge_version = knowledge.version
    section.stale = False
    section.origin = "assistant"

    draft.content = _assemble(draft)
    repos.drafts.commit(draft)
    _audit(repos, project_id, chat_id, "draft_edit",
           f"Regenerated section “{section.heading or section_id}”", draft_id)
    return draft


# --------------------------------------------------------------- versions
def restore_version(project_id: str, draft_id: str, version: int, *,
                    chat_id: Optional[str] = None,
                    repos: Optional[Repositories] = None) -> DraftRecord:
    """Restore an earlier version by committing its content as a *new* version.

    Append-only: restoring never deletes history, so a restore is itself undoable.
    """
    repos = repos or default_repositories()
    old = repos.drafts.get_version(project_id, draft_id, version)
    if old is None:
        raise DraftError(f"Draft {draft_id} has no version {version}.")
    repos.drafts.commit(old)  # commit assigns the next version number
    _audit(repos, project_id, chat_id, "draft_edit",
           f"Restored version {version}", draft_id)
    return old


# ------------------------------------------------------------------ helpers
def _plan(knowledge: ProjectKnowledge, audience: Optional[str],
          audience_label: str):
    from app.report import planner

    aud = _audience(audience)
    return planner.plan(
        knowledge.data_model, aud, quality=knowledge.quality_report,
        audience_label=audience_label,
        fingerprint=f"pk:{knowledge.version}")


def _audience(value: Optional[str]) -> Audience:
    """Tolerant lookup: `Audience` values are capitalised ("Executive"), but a
    caller (API, chat) naturally types "executive" — match by value or name,
    case-insensitively, and default to PMO."""
    if not value:
        return Audience.PMO
    lowered = value.strip().lower()
    for audience in Audience:
        if lowered in (audience.value.lower(), audience.name.lower()):
            return audience
    return Audience.PMO


def _sections_from_content(content, knowledge: ProjectKnowledge) -> list[DraftSection]:
    return [
        DraftSection(
            section_id=section.section_id,
            heading=section.headline,
            content=_render_section(section, content),
            depends_on=_dependencies(section, knowledge),
            based_on_knowledge_version=knowledge.version,
            origin="assistant",
        )
        for section in content.narrative()
    ]


def _render_section(section, content) -> str:
    from app.report.render import markdown as md

    return "\n".join(md._section(section, content, False)).rstrip()


def _dependencies(section, knowledge: ProjectKnowledge) -> Dependencies:
    """What this section was built from — entity content-keys and calc/fact keys.

    Entity keys match the change log's `kind:label` identity (resolved from the
    entity id), so a change to that entity stales exactly this section. Tile fact
    keys are calculation dependencies, which the change log cannot verify — a
    section carrying them is treated conservatively by `drafts.evaluate`.
    """
    from app.agent.nl_updates import LABELS

    model = knowledge.data_model
    entity_keys: set[str] = set()
    calc_keys: set[str] = set()

    for block in section.blocks:
        kind = getattr(block, "kind", None)
        if kind == "table" and not getattr(block, "is_derived", False):
            for row in block.rows:
                for cell in row:
                    ref = getattr(cell, "ref", None)
                    if ref is None or not ref.entity_id:
                        continue
                    label = _label_of(model, ref.entity_type, ref.entity_id, LABELS)
                    if label:
                        entity_keys.add(f"{ref.entity_type}:{label}")
        elif kind == "tiles":
            for tile in block.tiles:
                if getattr(tile, "fact_key", None):
                    calc_keys.add(tile.fact_key)

    return Dependencies(entity_ids=sorted(entity_keys),
                        calculation_ids=sorted(calc_keys))


def _label_of(model, entity_type: str, entity_id: str, labels) -> Optional[str]:
    entry = labels.get(entity_type)
    if entry is None:
        return None
    coll, id_attr, label_attr = entry
    for entity in getattr(model, coll, []) or []:
        if getattr(entity, id_attr, None) == entity_id:
            return str(getattr(entity, label_attr, "")) or None
    return None


def _assemble(draft: DraftRecord) -> str:
    """The whole draft as one Markdown document — what "copy all" returns."""
    parts = [f"# {draft.title}"]
    for section in draft.sections:
        parts.append(section.content)
    return "\n\n---\n\n".join(p for p in parts if p).rstrip() + "\n"


def _section(draft: DraftRecord, section_id: str) -> DraftSection:
    for section in draft.sections:
        if section.section_id == section_id:
            return section
    raise DraftError(f"Draft {draft.draft_id} has no section “{section_id}”.")


def _require(repos: Repositories, project_id: str, draft_id: str) -> DraftRecord:
    draft = repos.drafts.get(project_id, draft_id)
    if draft is None:
        raise DraftError(f"No such draft: {draft_id}")
    return draft


def _audit(repos: Repositories, project_id: str, chat_id: Optional[str],
           event_type: str, content: str, draft_id: str) -> None:
    repos.audit.append(AuditEvent(
        event_id=f"aud_{uuid.uuid4().hex[:10]}", project_id=project_id,
        chat_id=chat_id, type=event_type, content=content,
        metadata={"draft_id": draft_id}))
