"""JSON/JSONL implementations of the repository protocols (the prototype backend).

Deliberately dumb: read a file, write a file, atomically. Everything clever about
*when* to write and *what* the next version is lives in `rebuild.py`, above the
repository line, so a SQLite backend can be a drop-in that reuses that logic.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from app.models.source import SourceReference
from app.project import paths
from app.project.locks import atomic_write_text
from app.project.models import (
    AuditEvent,
    DraftRecord,
    FileRecord,
    ProjectKnowledge,
    SourceEvent,
    _now,
)
from app.project.repositories import StaleVersionError

log = logging.getLogger("pmi.project.store")


# --- record cache codec --------------------------------------------------------
# Extractor records are not plain JSON: each carries a live `SourceReference` under
# `source` (used directly by `standardize`, not re-parsed) and, from spreadsheets,
# real `date`/`datetime` cell values that `parse_date` accepts as objects but not in
# every string form. Caching must therefore round-trip these exactly, or a file read
# from cache would standardize differently from the same file read fresh — a silent
# divergence. Values are tagged on write and reconstructed on read; everything else
# is ordinary JSON.
def _encode_record_value(obj: Any):
    if isinstance(obj, SourceReference):
        return {"__t__": "source", "v": obj.model_dump(mode="json")}
    if isinstance(obj, datetime):
        return {"__t__": "dt", "v": obj.isoformat()}
    if isinstance(obj, date):
        return {"__t__": "d", "v": obj.isoformat()}
    raise TypeError(f"cannot cache value of type {type(obj).__name__}")


def _decode_record_obj(d: dict) -> Any:
    tag = d.get("__t__")
    if tag == "source":
        return SourceReference.model_validate(d["v"])
    if tag == "dt":
        return datetime.fromisoformat(d["v"])
    if tag == "d":
        return date.fromisoformat(d["v"])
    return d


class JsonFileRepository:
    """`file_index.json` for state, `records/<file_id>.json` for cached output."""

    def get_index(self, project_id: str) -> list[FileRecord]:
        path = paths.file_index_path(project_id)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("file index for %s unreadable (%s); treating as empty",
                        project_id, exc)
            return []
        return [FileRecord.model_validate(item) for item in raw]

    def save_index(self, project_id: str, records: list[FileRecord]) -> None:
        atomic_write_text(
            paths.file_index_path(project_id),
            json.dumps([r.model_dump(mode="json") for r in records], indent=2),
        )

    def store_upload(self, project_id: str, file_id: str, src: Path) -> Path:
        dest_dir = paths.files_dir(project_id) / file_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        return dest

    def get_records(self, project_id: str, file_id: str) -> list[dict]:
        path = paths.records_dir(project_id) / f"{file_id}.json"
        if not path.is_file():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"),
                              object_hook=_decode_record_obj)
        except (OSError, ValueError) as exc:
            log.warning("cached records for %s/%s unreadable (%s)",
                        project_id, file_id, exc)
            return []

    def save_records(self, project_id: str, file_id: str,
                     records: list[dict]) -> None:
        atomic_write_text(
            paths.records_dir(project_id) / f"{file_id}.json",
            json.dumps(records, indent=2, default=_encode_record_value),
        )


class JsonKnowledgeRepository:
    """`knowledge/current.json` + append-only `knowledge/versions/vN.json`.

    The version check in `save_next` is the second half of correction #8: even if
    two writers both hold the lock in sequence, the second sees a bumped current
    version and is told to re-plan instead of overwriting the first.
    """

    def current(self, project_id: str) -> Optional[ProjectKnowledge]:
        path = paths.knowledge_current_path(project_id)
        if not path.is_file():
            return None
        try:
            return ProjectKnowledge.model_validate_json(
                path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("knowledge for %s unreadable (%s)", project_id, exc)
            return None

    def current_version(self, project_id: str) -> int:
        """Read just the version — cheap, and used on every staleness check."""
        path = paths.knowledge_current_path(project_id)
        if not path.is_file():
            return 0
        try:
            return int(json.loads(path.read_text(encoding="utf-8")).get("version", 0))
        except (OSError, ValueError):
            return 0

    def save_next(self, knowledge: ProjectKnowledge, *,
                  expected_current_version: int) -> ProjectKnowledge:
        project_id = knowledge.project_id
        on_disk = self.current_version(project_id)
        if on_disk != expected_current_version:
            raise StaleVersionError(
                f"knowledge for {project_id} moved to v{on_disk} while a write "
                f"expecting v{expected_current_version} was in flight"
            )

        knowledge.version = expected_current_version + 1
        payload = knowledge.model_dump_json(indent=2)

        # Version file first: if the process dies between the two writes, the
        # history has the new version and `current.json` still points at the old
        # one — recoverable — rather than the reverse.
        atomic_write_text(
            paths.knowledge_version_path(project_id, knowledge.version), payload)
        atomic_write_text(paths.knowledge_current_path(project_id), payload)
        log.info("project %s knowledge -> v%d (%d entities)",
                 project_id, knowledge.version, knowledge.entity_count())
        return knowledge


def _append_jsonl(path: Path, line: str) -> None:
    """Append one JSON line. Append is the only mutation an event log allows, so
    there is no read-modify-write window to guard — concurrent appends interleave
    at whole lines, never mid-line, for records this small."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            log.warning("skipping unreadable event line in %s", path)
    return rows


class JsonSourceEventRepository:
    """Append-only `sources/events.jsonl` of `SourceEvent`s (knowledge sources)."""

    def append(self, event: SourceEvent) -> SourceEvent:
        _append_jsonl(paths.events_path(event.project_id),
                      event.model_dump_json())
        return event

    def list(self, project_id: str) -> list[SourceEvent]:
        return [SourceEvent.model_validate(row)
                for row in _read_jsonl(paths.events_path(project_id))]


class JsonAuditEventRepository:
    """Append-only `sources/audit.jsonl` of `AuditEvent`s (the trail)."""

    def append(self, event: AuditEvent) -> AuditEvent:
        _append_jsonl(paths.audit_path(event.project_id),
                      event.model_dump_json())
        return event

    def list(self, project_id: str) -> list[AuditEvent]:
        return [AuditEvent.model_validate(row)
                for row in _read_jsonl(paths.audit_path(project_id))]


class JsonDraftRepository:
    """`drafts/<draft_id>/current.json` + append-only `vN.json` history.

    Two writes with different meanings (spec §"Editable Draft Model"):

    * `commit` mints a new **content** version — a create, a user edit, a section
      regenerate, a restore. Every direct user edit is one of these, per the spec's
      "every direct user edit must create or update a draft version".
    * `save` updates `current.json` in place with **no** new version — used for a
      staleness flag, which is not an edit of the draft's content and must not
      inflate its history.
    """

    def _dir(self, project_id: str, draft_id: str):
        return paths.drafts_dir(project_id) / draft_id

    def get(self, project_id: str, draft_id: str) -> Optional[DraftRecord]:
        return self._read(self._dir(project_id, draft_id) / "current.json",
                          project_id, draft_id)

    def get_version(self, project_id: str, draft_id: str,
                    version: int) -> Optional[DraftRecord]:
        return self._read(self._dir(project_id, draft_id) / f"v{version}.json",
                          project_id, draft_id)

    def _read(self, path, project_id, draft_id) -> Optional[DraftRecord]:
        if not path.is_file():
            return None
        try:
            return DraftRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("draft %s/%s unreadable (%s)", project_id, draft_id, exc)
            return None

    def _latest_version(self, project_id: str, draft_id: str) -> int:
        base = self._dir(project_id, draft_id)
        if not base.is_dir():
            return 0
        versions = [int(p.stem[1:]) for p in base.glob("v*.json")
                    if p.stem[1:].isdigit()]
        return max(versions, default=0)

    def commit(self, draft: DraftRecord) -> DraftRecord:
        """Mint the next version of `draft` and make it current."""
        draft.version = self._latest_version(draft.project_id, draft.draft_id) + 1
        draft.updated_at = _now()
        payload = draft.model_dump_json(indent=2)
        base = self._dir(draft.project_id, draft.draft_id)
        atomic_write_text(base / f"v{draft.version}.json", payload)
        atomic_write_text(base / "current.json", payload)
        return draft

    def save(self, draft: DraftRecord) -> DraftRecord:
        """In-place current update (flags only) — no new version."""
        atomic_write_text(self._dir(draft.project_id, draft.draft_id)
                          / "current.json", draft.model_dump_json(indent=2))
        return draft

    def list_versions(self, project_id: str, draft_id: str):
        from app.project.models import DraftVersionInfo

        infos = []
        base = self._dir(project_id, draft_id)
        if base.is_dir():
            for path in sorted(base.glob("v*.json"),
                               key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit()
                               else 0):
                draft = self._read(path, project_id, draft_id)
                if draft is not None:
                    infos.append(DraftVersionInfo(
                        version=draft.version, status=draft.status,
                        based_on_knowledge_version=draft.based_on_knowledge_version,
                        created_by=draft.created_by, updated_at=draft.updated_at))
        return infos

    def list(self, project_id: str) -> list[DraftRecord]:
        base = paths.drafts_dir(project_id)
        if not base.is_dir():
            return []
        drafts = []
        for child in sorted(base.iterdir()):
            if child.is_dir():
                got = self.get(project_id, child.name)
                if got is not None:
                    drafts.append(got)
        return drafts


# ------------------------------------------------------------------ accessor
class Repositories:
    """The concrete backend handed to orchestration.

    A single object so a caller says `repos.files` / `repos.knowledge` and a test
    can substitute a fake for one repository without the others. Today every field
    is the JSON implementation; swapping one for SQLite is a one-line change here.
    """

    def __init__(self, *, files: Optional[JsonFileRepository] = None,
                 knowledge: Optional[JsonKnowledgeRepository] = None,
                 sources: Optional[JsonSourceEventRepository] = None,
                 audit: Optional[JsonAuditEventRepository] = None,
                 drafts: Optional[JsonDraftRepository] = None) -> None:
        self.files = files or JsonFileRepository()
        self.knowledge = knowledge or JsonKnowledgeRepository()
        self.sources = sources or JsonSourceEventRepository()
        self.audit = audit or JsonAuditEventRepository()
        self.drafts = drafts or JsonDraftRepository()


def default_repositories() -> Repositories:
    return Repositories()
