"""Repository interfaces (correction #10).

Orchestration and knowledge logic depend on these Protocols, never on a file scan
or a `.json` path. JSON/JSONL is fine for the prototype, but the moment a query
gets slow or a second writer appears the answer is a SQLite/Postgres implementation
of these same interfaces — and no agent code changes, because no agent code ever
knew where the bytes were.

Only the two repositories Phase 1A needs are defined here; `SourceEventRepository`,
`AuditEventRepository`, and `DraftRepository` land with the checkpoints that first
use them (1B, Phase 2), against this same pattern.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from app.project.models import (
    AuditEvent,
    DraftRecord,
    FileRecord,
    ProjectKnowledge,
    SourceEvent,
)


class StaleVersionError(RuntimeError):
    """Raised when a knowledge write's `expected_current_version` no longer matches
    what is on disk — another writer got there first. The caller should re-read the
    current version and rebuild on top of it rather than overwrite (correction #8)."""


@runtime_checkable
class FileRepository(Protocol):
    """Per-file ingestion state and the cached extractor output."""

    def get_index(self, project_id: str) -> list[FileRecord]: ...

    def save_index(self, project_id: str, records: list[FileRecord]) -> None: ...

    def store_upload(self, project_id: str, file_id: str, src: Path) -> Path:
        """Copy a raw uploaded file into the project, returning its stored path."""
        ...

    def get_records(self, project_id: str, file_id: str) -> list[dict]:
        """The cached extractor records for one file (empty if none)."""
        ...

    def save_records(self, project_id: str, file_id: str,
                     records: list[dict]) -> None: ...


@runtime_checkable
class KnowledgeRepository(Protocol):
    """The versioned canonical knowledge state."""

    def current(self, project_id: str) -> Optional[ProjectKnowledge]: ...

    def current_version(self, project_id: str) -> int:
        """The live version number without parsing the whole document (0 if none)."""
        ...

    def save_next(self, knowledge: ProjectKnowledge, *,
                  expected_current_version: int) -> ProjectKnowledge:
        """Write `knowledge` as the next version, atomically.

        Raises `StaleVersionError` if the on-disk current version is not
        `expected_current_version`. Assigns `version = expected + 1`, appends
        `versions/vN.json`, and replaces `current.json` atomically.
        """
        ...


@runtime_checkable
class SourceEventRepository(Protocol):
    """Append-only log of fact-bearing inputs (knowledge sources)."""

    def append(self, event: SourceEvent) -> SourceEvent: ...

    def list(self, project_id: str) -> list[SourceEvent]: ...


@runtime_checkable
class AuditEventRepository(Protocol):
    """Append-only trail of inputs that are recorded but never treated as
    knowledge — ordinary messages, generated drafts, edits, exports."""

    def append(self, event: AuditEvent) -> AuditEvent: ...

    def list(self, project_id: str) -> list[AuditEvent]: ...


@runtime_checkable
class DraftRepository(Protocol):
    """Report drafts, versioned. `commit` mints a new content version (create/edit/
    regenerate/restore); `save` updates the current record in place for flag-only
    changes (staleness) without inflating history."""

    def get(self, project_id: str, draft_id: str) -> Optional[DraftRecord]: ...

    def get_version(self, project_id: str, draft_id: str,
                    version: int) -> Optional[DraftRecord]: ...

    def commit(self, draft: DraftRecord) -> DraftRecord: ...

    def save(self, draft: DraftRecord) -> DraftRecord: ...

    def list_versions(self, project_id: str, draft_id: str): ...

    def list(self, project_id: str) -> list[DraftRecord]: ...
