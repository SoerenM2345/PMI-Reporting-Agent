"""Incremental file ingestion (spec §"Incremental Ingestion", corrections #6).

The one expensive, non-deterministic step in the pipeline is extraction — a PDF
parse, and since §5.6 a *paid* vision call whose output can differ run to run. So
this module is where "don't reprocess an unchanged file" is enforced: a file is
identified by its name within the project (re-uploading `Finance.xlsx` updates that
file), and its content hash decides whether the cached extractor output is reused
or the extractor runs again.

Removal is a soft delete: the record is marked inactive and its cached records and
provenance are kept, so an earlier knowledge version that cited the file can still
be explained. `collect_active` — the union rebuild reads from — simply skips it.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from app.extractors import SUPPORTED_EXTENSIONS, extract_file
from app.project.json_repositories import Repositories, default_repositories
from app.project.models import FileRecord, _now

log = logging.getLogger("pmi.project.files")


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_id_for(file_name: str) -> str:
    """A stable id per file *name* within a project.

    Name is the identity, as on a filesystem: re-uploading `Finance.xlsx` updates
    the same logical file rather than accumulating duplicates. Derived, so the id
    is reproducible without consulting the index.
    """
    return hashlib.sha1(file_name.encode("utf-8")).hexdigest()[:12]


def _index_by_id(records: list[FileRecord]) -> dict[str, FileRecord]:
    return {r.file_id: r for r in records}


def ingest_file(project_id: str, src: Path, *,
                repos: Optional[Repositories] = None) -> FileRecord:
    """Ingest one uploaded file, extracting only if its content changed.

    Returns the `FileRecord`. Does **not** rebuild knowledge — the caller ingests
    every file it wants, then calls `rebuild` once, so a batch upload re-derives the
    model a single time.
    """
    repos = repos or default_repositories()
    src = Path(src)
    file_name = src.name
    file_id = file_id_for(file_name)
    content_hash = hash_bytes(src.read_bytes())

    index = repos.files.get_index(project_id)
    by_id = _index_by_id(index)
    existing = by_id.get(file_id)

    # Unchanged content that we already extracted successfully → reuse the cache.
    # Re-activates a file that had been removed and re-uploaded identically.
    if (existing is not None and existing.content_hash == content_hash
            and existing.extraction_status == "completed" and existing.active):
        log.info("%s unchanged (hash match) — skipping extraction", file_name)
        return existing

    repos.files.store_upload(project_id, file_id, src)

    record = FileRecord(
        file_id=file_id, file_name=file_name, content_hash=content_hash,
        uploaded_at=_now(),
        # A changed file starts a fresh contribution: it will be attributed to the
        # next rebuild, not the one that ingested its previous version.
        knowledge_version_added=None,
    )

    if src.suffix.lower() not in SUPPORTED_EXTENSIONS:
        record.extraction_status = "failed"
        record.error = f"unsupported file type '{src.suffix}'"
        repos.files.save_records(project_id, file_id, [])
        log.warning("%s: %s", file_name, record.error)
    else:
        try:
            records = extract_file(src)
            repos.files.save_records(project_id, file_id, records)
            record.record_count = len(records)
            record.extraction_status = "completed"
        except Exception as exc:                                  # noqa: BLE001
            # A broken file must stay visible (§21.17 / "never silently remove
            # data"), so it becomes a failed record that the data-quality report
            # will surface, not a dropped upload.
            record.extraction_status = "failed"
            record.error = str(exc)
            repos.files.save_records(project_id, file_id, [])
            log.warning("extraction failed for %s: %s", file_name, exc)

    by_id[file_id] = record
    repos.files.save_index(project_id, list(by_id.values()))
    return record


def remove_file(project_id: str, file_id: str, *,
                repos: Optional[Repositories] = None) -> Optional[FileRecord]:
    """Soft-delete a file: mark it inactive, keep its record and cache (correction #6).

    Returns the updated record, or None if there was no such file. Like ingestion,
    it does not rebuild — the caller rebuilds once after the change.
    """
    repos = repos or default_repositories()
    by_id = _index_by_id(repos.files.get_index(project_id))
    record = by_id.get(file_id)
    if record is None:
        return None

    record.active = False
    record.status = "removed"
    record.removed_at = _now()
    repos.files.save_index(project_id, list(by_id.values()))
    log.info("project %s: file %s (%s) marked removed", project_id, file_id,
             record.file_name)
    return record


def active_file_records(project_id: str, *,
                        repos: Optional[Repositories] = None) -> list[FileRecord]:
    """Active files that extracted successfully — the ones rebuild draws from.

    Sorted by name for a deterministic record order, which keeps the positional
    entity ids (`T001`, `M002`, …) that `standardize` assigns stable across
    rebuilds when the file set has not changed.
    """
    repos = repos or default_repositories()
    return sorted(
        (r for r in repos.files.get_index(project_id)
         if r.active and r.extraction_status == "completed"),
        key=lambda r: r.file_name,
    )


def collect_active(project_id: str, *,
                   repos: Optional[Repositories] = None) -> tuple[list[dict], list[str]]:
    """`(union_of_records, source_file_names)` for the active file set.

    This is the whole input to a rebuild: the concatenation of every active file's
    cached extractor records, in a stable order, plus the names those records came
    from.
    """
    repos = repos or default_repositories()
    records: list[dict] = []
    names: list[str] = []
    for rec in active_file_records(project_id, repos=repos):
        names.append(rec.file_name)
        records.extend(repos.files.get_records(project_id, rec.file_id))
    return records, names


def failed_file_names(project_id: str, *,
                      repos: Optional[Repositories] = None) -> list[str]:
    """Active files whose extraction failed — surfaced in the data-quality report."""
    repos = repos or default_repositories()
    return [r.file_name for r in repos.files.get_index(project_id)
            if r.active and r.extraction_status == "failed"]
