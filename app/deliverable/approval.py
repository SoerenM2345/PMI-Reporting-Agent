"""Approval bound to one immutable deliverable version and output format."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from app.deliverable import workflow


class GenerationApproval(BaseModel):
    approval_id: str
    session_id: str
    deliverable_version: int
    output_format: workflow.ReviewFormat
    fingerprint_digest: str
    approved_at: str


class ApprovalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def approve(session_id: str, version: int, output_format: str,
            analysis=None) -> GenerationApproval:
    from app.deliverable import session as session_plan

    selected = workflow.normalize_format(output_format)
    if selected is None:
        raise ApprovalError("unsupported_format", "Choose PowerPoint, PDF, Word, HTML, or chart.")
    deliverable = session_plan.load(session_id)
    if deliverable is None:
        raise ApprovalError("no_content", "There is no report preview to approve.")
    if deliverable.version != version:
        raise ApprovalError(
            "version_mismatch",
            f"Version {version} is no longer current. Review version {deliverable.version} instead.",
        )
    planned = workflow.normalize_format(deliverable.primary_format)
    if planned != selected:
        raise ApprovalError(
            "format_mismatch",
            f"This preview is for {workflow.FORMAT_LABELS.get(planned or '', planned or 'another format')}, "
            f"not {workflow.FORMAT_LABELS[selected]}. Build a new preview for the requested format.",
        )
    if analysis is not None and session_plan.is_stale(deliverable, session_id, analysis):
        raise ApprovalError("stale_content", "The underlying data changed. Review a fresh preview first.")

    record = GenerationApproval(
        approval_id=uuid.uuid4().hex,
        session_id=session_id,
        deliverable_version=deliverable.version,
        output_format=selected,
        fingerprint_digest=_fingerprint(deliverable),
        approved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _write(_path(session_id), record.model_dump_json(indent=2))
    workflow.update(session_id, selected_format=selected, state="approved",
                    version=deliverable.version)
    return record


def load(session_id: str) -> Optional[GenerationApproval]:
    path = _path(session_id)
    if not path.is_file():
        return None
    try:
        return GenerationApproval.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def current(session_id: str, deliverable, output_format: str, *, analysis=None,
            approval_id: Optional[str] = None) -> Optional[GenerationApproval]:
    from app.deliverable import session as session_plan

    record = load(session_id)
    selected = workflow.normalize_format(output_format)
    if record is None or selected is None:
        return None
    if approval_id and record.approval_id != approval_id:
        return None
    if record.deliverable_version != deliverable.version:
        return None
    if record.output_format != selected:
        return None
    if record.fingerprint_digest != _fingerprint(deliverable):
        return None
    if analysis is not None and session_plan.is_stale(deliverable, session_id, analysis):
        return None
    return record


def describe(session_id: str, deliverable, *, analysis=None) -> dict:
    selected = workflow.normalize_format(deliverable.primary_format)
    record = current(session_id, deliverable, selected or "", analysis=analysis)
    return {
        "required": bool(deliverable.review_required),
        "approved": record is not None,
        "approval_id": record.approval_id if record else None,
        "approved_version": record.deliverable_version if record else None,
        "approved_format": record.output_format if record else None,
    }


def _fingerprint(deliverable) -> str:
    payload = {
        "version": deliverable.version,
        "format": workflow.normalize_format(deliverable.primary_format),
        "fingerprint": deliverable.fingerprint,
        "references": [item.model_dump(mode="json")
                       for item in deliverable.source_use_constraints],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _path(session_id: str) -> Path:
    from app.storage import json_store

    return json_store.session_dir(session_id) / "deliverables" / "approval.json"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
