"""Create and edit report drafts (spec §"Editable Draft Model", Phase 2).

A draft is the report as *editable free text*: the user reads it, edits a section
directly, asks the agent to rewrite another, and only exports when they choose to.
It is planned once from project knowledge and then owned by the user — the system
flags it when knowledge moves (Phase 1C) but never rewrites it.

A draft is derived from a planned `Deliverable` (`app/deliverable/engine.py`) and
records which one, so an export renders *that* artifact rather than re-parsing the
draft's Markdown back into a document model — a round trip that used to discard
cell provenance, emphasis and column types on the way out.

Where the user has edited a section, the edit wins: `exporting` overlays
user-owned section text onto the deliverable before rendering. The draft is the
text the user approved, and an export that quietly regenerated a different
narrative would break that promise (Scenario 6).

Each section records what it depended on, so a later knowledge change stales only
the sections it touched, and a regenerate refreshes one section without
disturbing the rest.

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
                 request_text: str = "", fmt: Optional[str] = None,
                 repos: Optional[Repositories] = None) -> DraftRecord:
    """Plan a fresh draft from the project's context, knowledge and request.

    `request_text` is what the user actually asked for. It used to be discarded:
    the draft was planned from a per-audience table, so every draft of a given
    audience was the same document whatever the user said.
    """
    repos = repos or default_repositories()
    knowledge = repos.knowledge.current(project_id)
    if knowledge is None or knowledge.entity_count() == 0:
        raise DraftError("There is nothing to draft yet — add project files first.")

    deliverable, context = _plan(project_id, request_text, audience,
                                 audience_label, fmt, repos)
    draft = DraftRecord(
        draft_id=_uid(), project_id=project_id, chat_id=chat_id,
        title=title or deliverable.title, draft_type=draft_type,
        target_format=(fmt or deliverable.primary_format),
        audience=(audience or deliverable.audience_label or Audience.PMO.value),
        audience_label=audience_label or deliverable.audience_label,
        based_on_knowledge_version=knowledge.version, created_by="assistant",
        deliverable_id=deliverable.deliverable_id,
        deliverable_version=deliverable.version,
        sections=_sections_from_deliverable(deliverable, context, knowledge),
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

    deliverable, context = _plan(project_id, "", draft.audience,
                                 draft.audience_label, draft.target_format, repos)
    page = deliverable.page(section_id)
    if page is None:
        raise DraftError(
            f"Section “{section_id}” is not part of the current plan, so there is "
            f"nothing to regenerate it from.")

    section.content = _render_page(page, deliverable)
    section.heading = page.title
    section.depends_on = _page_dependencies(page, context, knowledge)
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
def _plan(project_id: str, request_text: str, audience: Optional[str],
          audience_label: str, fmt: Optional[str], repos: Repositories):
    """Build the context, plan a deliverable, and store it."""
    from app.context import builder
    from app.deliverable import engine, store

    context = builder.build_for_project(
        project_id, request_text, requested_format=fmt, repos=repos)
    if audience and not context.audience:
        context.audience = audience_label or audience

    # `force`: a draft is explicitly not a final artifact, so an unresolved
    # conflict is disclosed in it rather than blocking it. The export gate is
    # where publication is held back.
    deliverable = engine.build(context, force=True,
                               knowledge_version=_version(repos, project_id))
    store.save(deliverable)
    return deliverable, context


def _version(repos: Repositories, project_id: str) -> int:
    knowledge = repos.knowledge.current(project_id)
    return knowledge.version if knowledge is not None else 0


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


def _sections_from_deliverable(deliverable, context,
                               knowledge: ProjectKnowledge) -> list[DraftSection]:
    """One editable section per page. The cover is furniture, not content."""
    return [
        DraftSection(
            section_id=page.page_id,
            heading=page.title,
            content=_render_page(page, deliverable),
            depends_on=_page_dependencies(page, context, knowledge),
            based_on_knowledge_version=knowledge.version,
            origin="assistant",
        )
        for page in deliverable.pages if page.purpose != "cover"
    ]


def _render_page(page, deliverable) -> str:
    from app.renderers import markdown as md

    return md.section_markdown(page, deliverable).rstrip()


def _page_dependencies(page, context, knowledge: ProjectKnowledge) -> Dependencies:
    """What this page was built from, as the change log identifies things.

    Entity keys are `kind:label`, matching the change log, so a change to that
    entity stales exactly the pages that used it. Computed facts are
    calculation dependencies, which the change log cannot verify, so a page
    carrying them is treated conservatively by `drafts.evaluate`.
    """
    entity_keys: set[str] = set()
    calc_keys: set[str] = set()

    for evidence_id in page.evidence_ids:
        item = context.evidence.get(evidence_id)
        if item is None:
            continue
        if item.kind in ("fact", "calculation"):
            calc_keys.add(evidence_id.split(":", 2)[-1])
        elif item.entity_type and item.label:
            entity_keys.add(f"{item.entity_type}:{item.label}")

    return Dependencies(entity_ids=sorted(entity_keys),
                        calculation_ids=sorted(calc_keys))


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
