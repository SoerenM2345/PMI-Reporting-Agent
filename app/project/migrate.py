"""Migrate the session-centric store into project-centric knowledge (correction #9).

The old world was one chat → one session → one `analysis.json`. The new world is
one project → many chats → one shared knowledge base. This bridges them, safely:

* **One project per orphaned session.** A chat that never belonged to a project
  becomes its *own* project — never lumped into a shared bucket, which would merge
  unrelated engagements' figures. Chats already filed under a project migrate into
  that project, which is exactly the shared-knowledge end state.
* **Copy before delete.** Nothing under `storage_data/<session>/` is removed. Files
  are copied into the project and re-ingested; the original session stays on disk as
  a fallback until the project store is trusted.
* **Idempotent.** Each project records which sessions it has absorbed; a second run
  skips them, so migration can run on every startup without duplicating anything.

Reuses Phase 1A/1B wholesale: files are ingested (hash + cache), a rebuild derives
the knowledge, and the session's user-supplied values return as `confirmed_value`
decisions so a re-read keeps honouring them.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.project import files as files_mod
from app.project import paths
from app.project.json_repositories import Repositories, default_repositories
from app.project.locks import atomic_write_text
from app.project.models import UserDecision
from app.project.rebuild import rebuild
from app.storage import chat_store, json_store

log = logging.getLogger("pmi.project.migrate")


class MigrationReport(BaseModel):
    projects_created: list[str] = Field(default_factory=list)
    sessions_migrated: list[str] = Field(default_factory=list)
    sessions_skipped: list[str] = Field(default_factory=list)


def _marker_path(project_id: str):
    return paths.project_dir(project_id) / ".migrated_sessions.json"


def _migrated_sessions(project_id: str) -> set[str]:
    path = _marker_path(project_id)
    if not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _mark_migrated(project_id: str, session_id: str) -> None:
    done = _migrated_sessions(project_id)
    done.add(session_id)
    atomic_write_text(_marker_path(project_id), json.dumps(sorted(done)))


def migrate_all(*, repos: Optional[Repositories] = None) -> MigrationReport:
    """Migrate every chat's session into a project. Safe to run repeatedly."""
    repos = repos or default_repositories()
    report = MigrationReport()
    orphan_projects: dict[str, str] = {}

    for chat in chat_store.list_chats(include_archived=True):
        if chat.project_id:
            project_id = chat.project_id
        else:
            # One project per orphaned session (deduped if two chats somehow share
            # a session), never a shared catch-all.
            if chat.session_id in orphan_projects:
                project_id = orphan_projects[chat.session_id]
            else:
                created = chat_store.create_project(
                    name=chat.title or "Migrated project")
                project_id = created.project_id
                orphan_projects[chat.session_id] = project_id
                report.projects_created.append(project_id)
            chat_store.set_chat_project(chat.chat_id, project_id)

        if migrate_session(chat.session_id, project_id, repos=repos):
            report.sessions_migrated.append(chat.session_id)
        else:
            report.sessions_skipped.append(chat.session_id)

    log.info("migration: %d project(s) created, %d session(s) migrated, %d skipped",
             len(report.projects_created), len(report.sessions_migrated),
             len(report.sessions_skipped))
    return report


def migrate_session(session_id: str, project_id: str, *,
                    repos: Optional[Repositories] = None) -> bool:
    """Absorb one session's files and user values into `project_id`.

    Returns True if it migrated, False if it was already done (idempotent).
    """
    repos = repos or default_repositories()
    if session_id in _migrated_sessions(project_id):
        return False

    uploads = json_store.uploads_dir(session_id)
    if uploads.is_dir():
        for path in sorted(uploads.iterdir()):
            if path.is_file():
                files_mod.ingest_file(project_id, path, repos=repos)

    rebuild(project_id, repos=repos, trigger=f"migrate:{session_id}",
            add_decisions=_decisions_from_session(session_id),
            set_project_fields=_project_fields_from_session(session_id))

    _mark_migrated(project_id, session_id)
    log.info("migrated session %s into project %s", session_id, project_id)
    return True


def _decisions_from_session(session_id: str) -> list[UserDecision]:
    """The session's user-supplied entity values, as confirmed-value decisions, so
    they survive re-derivation exactly as a chat correction now does."""
    from app.agent import knowledge as sess_knowledge

    kb = sess_knowledge.load(session_id)
    decisions: list[UserDecision] = []
    for uv in kb.user_values:
        if not uv.field:
            continue
        decisions.append(UserDecision(
            decision_id=f"mig_{session_id}_{uv.entity_type}_{uv.field}",
            kind="confirmed_value",
            detail={"entity_type": uv.entity_type, "entity_label": uv.label,
                    "field": uv.field, "raw": uv.raw or str(uv.value),
                    "migrated_from": session_id}))
    return decisions


def _project_fields_from_session(session_id: str) -> dict[str, str]:
    """Project-header facts the user set in the session (reporting date, Day 1, …)."""
    from app.agent import knowledge as sess_knowledge

    kb = sess_knowledge.load(session_id)
    return {k: str(v) for k, v in kb.project_fields.items()}
