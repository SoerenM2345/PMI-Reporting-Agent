"""Versioned storage for `ReportContent`, and the staleness check.

Kept deliberately **separate from `analysis.json`**. `json_store.load_analysis`
swallows a validation error and returns `None`, which the API turns into "please
re-analyze" — the right call for analysis, but fatal if presentation content
lived in the same file: a schema change to a *slide layout* would then destroy
the *extraction*, including the vision calls that cost money and cannot be
reproduced identically. Two files, two failure domains.

    storage_data/<session>/content/
      v1.json  v2.json  v3.json
      HEAD                        {"version": 3}

**Append-only.** A revert writes a *new* version whose `parent_version` points
at the one restored; nothing is ever mutated or deleted. In a PMI context the
trail is the point — "which text did the Steering Committee actually approve"
is a question someone will eventually ask — and it makes the chat loop ("adjust
slide 3" / "no, undo that") trivial.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from app.models.pmi import DataQualityReport, PMIDataModel
from app.report.content import ContentProvenance, ReportContent
from app.storage.json_store import session_dir

log = logging.getLogger("pmi.report.store")


class VersionInfo(BaseModel):
    """One entry in the history, cheap enough to list without loading content."""

    version: int
    parent_version: Optional[int] = None
    created_at: str
    created_by: str
    instruction: Optional[str] = None
    is_head: bool = False


# ------------------------------------------------------------------- layout
def content_dir(session_id: str) -> Path:
    return session_dir(session_id) / "content"


def _head_file(session_id: str) -> Path:
    return content_dir(session_id) / "HEAD"


def _version_file(session_id: str, version: int) -> Path:
    return content_dir(session_id) / f"v{version}.json"


# ---------------------------------------------------------------- fingerprint
def fingerprint(
    model: PMIDataModel,
    quality: Optional[DataQualityReport] = None,
    *,
    session_id: str = "",
) -> str:
    """A cheap hash of everything a plan was built from.

    Not a checksum of everything — just the things that change what the report
    *says*: how many entities we found, how many conflicts are open, how many
    have been decided, and the quality score. Resolving a conflict moves the
    resolved count and the score, which is exactly the case this exists to
    catch (see `is_stale`).
    """
    resolved = sum(1 for c in model.conflicts if c.is_resolved)
    score = getattr(quality, "score", None) if quality else None
    # The source file list is part of the identity. Without it, adding a file
    # whose entities happen to balance out a removed one would leave the
    # fingerprint unchanged and a stale report looking current.
    sources = ",".join(sorted(model.source_files))
    # …and so is what the *user* has told us. A supplied value, a chosen
    # audience or a requested structure changes the report without touching a
    # single extracted entity, so without this a draft would survive them all
    # and render exactly what the user just corrected.
    session = session_id or model.project.project_id or ""
    knowledge = _knowledge_revision(session)
    seed = (f"{model.entity_count()}|{len(model.conflicts)}|{resolved}|"
            f"{len(model.unresolved_conflicts())}|{score}|{sources}|kb{knowledge}")
    return hashlib.sha1(seed.encode()).hexdigest()[:12]


def _knowledge_revision(session_id: str) -> int:
    if not session_id:
        return 0
    from app.agent import knowledge

    return knowledge.content_revision(session_id)


def is_stale(
    content: ReportContent,
    model: PMIDataModel,
    quality: Optional[DataQualityReport] = None,
) -> bool:
    """Has the analysis moved since this content was planned?

    The dangerous sequence: plan a report, then resolve a conflict. The stored
    content still states the figure the *losing* source reported, and rendering
    it would produce a deck that is confidently wrong — the exact failure the
    whole conflict system exists to prevent. An empty fingerprint means the
    content predates this check; treat it as stale rather than assume it is fine.
    """
    if not content.analysis_fingerprint:
        return True
    return content.analysis_fingerprint != fingerprint(
        model, quality, session_id=content.session_id
    )


# --------------------------------------------------------------------- write
def save(content: ReportContent) -> ReportContent:
    """Write `content` as the next version and move HEAD to it."""
    directory = content_dir(content.session_id)
    directory.mkdir(parents=True, exist_ok=True)

    next_version = latest_version(content.session_id) + 1
    stored = content.model_copy(update={"version": next_version})

    _version_file(content.session_id, next_version).write_text(
        stored.model_dump_json(indent=2), encoding="utf-8"
    )
    _head_file(content.session_id).write_text(
        json.dumps({"version": next_version}), encoding="utf-8"
    )
    log.info("saved content v%d for %s (%d sections)",
             next_version, content.session_id, len(stored.sections))
    return stored


# ---------------------------------------------------------------------- read
def latest_version(session_id: str) -> int:
    """0 when nothing has been planned yet."""
    head = _head_file(session_id)
    if head.is_file():
        try:
            return int(json.loads(head.read_text(encoding="utf-8"))["version"])
        except Exception:
            # HEAD is a two-field file; if it is unreadable, fall through to
            # the directory listing rather than losing the whole history.
            log.warning("HEAD for %s is unreadable; scanning versions", session_id)

    existing = _all_version_numbers(session_id)
    return max(existing) if existing else 0


def load(session_id: str, version: Optional[int] = None) -> Optional[ReportContent]:
    """HEAD by default, or one specific version. `None` when there is none."""
    wanted = version if version is not None else latest_version(session_id)
    if wanted <= 0:
        return None

    path = _version_file(session_id, wanted)
    if not path.is_file():
        return None
    try:
        return ReportContent.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # Same reasoning as `json_store.load_analysis`: a schema change between
        # runs should cost a re-plan, not a 500. The analysis is untouched, so
        # re-planning is cheap and involves no extraction.
        log.warning("content v%d for %s is unreadable (%s); re-plan needed",
                    wanted, session_id, exc)
        return None


def versions(session_id: str) -> list[VersionInfo]:
    """Newest first. Reads each file — histories are short by construction."""
    head = latest_version(session_id)
    out: list[VersionInfo] = []
    for number in sorted(_all_version_numbers(session_id), reverse=True):
        content = load(session_id, number)
        if content is None:
            continue
        out.append(VersionInfo(
            version=content.version,
            parent_version=content.parent_version,
            created_at=content.created_at.isoformat(timespec="seconds"),
            created_by=content.provenance.created_by,
            instruction=content.provenance.instruction,
            is_head=(content.version == head),
        ))
    return out


def _all_version_numbers(session_id: str) -> list[int]:
    directory = content_dir(session_id)
    if not directory.is_dir():
        return []
    numbers = []
    for path in directory.glob("v*.json"):
        try:
            numbers.append(int(path.stem[1:]))
        except ValueError:
            continue
    return numbers


# -------------------------------------------------------------------- revert
def revert(session_id: str, to_version: int) -> Optional[ReportContent]:
    """Restore an earlier version by appending it again as a new one.

    Deliberately not a rollback: the discarded versions stay on disk. Someone
    asking "what did we send the board in week 3" must be able to get an answer
    even after five rounds of edits.
    """
    source = load(session_id, to_version)
    if source is None:
        return None

    restored = source.model_copy(update={
        "parent_version": to_version,
        "provenance": ContentProvenance(
            created_by="revert",
            reverted_from=to_version,
            instruction=f"Reverted to version {to_version}",
        ),
    })
    return save(restored)
