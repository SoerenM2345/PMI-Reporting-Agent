"""Where a project's data lives on disk.

The one place that knows the project directory layout, so the repositories are the
only callers and a future move to a database changes this file plus the repo
implementations and nothing else.

    storage_data/projects/<project_id>/
      project.json                 PMI header (§4 step 1): reporting date, priorities
      sources/
        files/<file_id>/<name>     the raw uploaded file, kept verbatim
        records/<file_id>.json     that file's extracted raw_records, cached by hash
        file_index.json            FileRecord[] — hash, status, active flag
        events.jsonl               SourceEvent log        (1B)
        audit.jsonl                AuditEvent log          (1B)
      knowledge/
        current.json               the live ProjectKnowledge
        versions/vN.json           append-only history
        .lock                      per-project write lock
      drafts/<draft_id>/           editable drafts         (Phase 2)
      exports/                     generated deliverables  (Phase 4)
"""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def projects_root() -> Path:
    return get_settings().storage_dir / "projects"


def project_dir(project_id: str) -> Path:
    return projects_root() / project_id


def sources_dir(project_id: str) -> Path:
    return project_dir(project_id) / "sources"


def files_dir(project_id: str) -> Path:
    """Raw uploaded files, one directory per file so a name is never overwritten."""
    return sources_dir(project_id) / "files"


def records_dir(project_id: str) -> Path:
    """Cached extractor output, one JSON file per uploaded file."""
    return sources_dir(project_id) / "records"


def file_index_path(project_id: str) -> Path:
    return sources_dir(project_id) / "file_index.json"


def events_path(project_id: str) -> Path:
    return sources_dir(project_id) / "events.jsonl"


def audit_path(project_id: str) -> Path:
    return sources_dir(project_id) / "audit.jsonl"


def knowledge_dir(project_id: str) -> Path:
    return project_dir(project_id) / "knowledge"


def knowledge_current_path(project_id: str) -> Path:
    return knowledge_dir(project_id) / "current.json"


def knowledge_versions_dir(project_id: str) -> Path:
    return knowledge_dir(project_id) / "versions"


def knowledge_version_path(project_id: str, version: int) -> Path:
    return knowledge_versions_dir(project_id) / f"v{version}.json"


def lock_path(project_id: str) -> Path:
    return knowledge_dir(project_id) / ".lock"


def project_header_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def drafts_dir(project_id: str) -> Path:
    return project_dir(project_id) / "drafts"


def exports_dir(project_id: str) -> Path:
    return project_dir(project_id) / "exports"
