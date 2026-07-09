"""Local JSON session storage (PDF spec: 'Storage (Prototype): Local JSON')."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "storage_data"


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    (BASE / sid / "uploads").mkdir(parents=True, exist_ok=True)
    save_meta(sid, {"session_id": sid, "files": [], "runs": []})
    return sid


def session_dir(sid: str) -> Path:
    return BASE / sid


def uploads_dir(sid: str) -> Path:
    return BASE / sid / "uploads"


def save_meta(sid: str, meta: dict) -> None:
    (BASE / sid).mkdir(parents=True, exist_ok=True)
    (BASE / sid / "meta.json").write_text(json.dumps(meta, indent=2, default=str))


def load_meta(sid: str) -> dict | None:
    p = BASE / sid / "meta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())
