"""Local JSON session storage (spec §15: "Storage (Prototype): Local project
directories, JSON").

Holds the analysis result between the analyze and generate calls. That persistence is
the whole reason the human-in-the-loop round trip is affordable: without it, every
conflict the user resolves would re-run extraction — and since §5.6 landed, that means
re-paying for a vision call and re-rolling the dice on what the model saw.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_settings
from app.models.pmi import (
    Audience,
    Conflict,
    DataQualityReport,
    PMIDataModel,
    PMIProject,
)

log = logging.getLogger("pmi.storage")


class SessionAnalysis(BaseModel):
    """Everything analysis produced. Written once, read by every later call."""

    session_id: str
    request_text: str = ""
    output_type: str = "powerpoint"
    topic: str = "status"
    audience: Optional[Audience] = None
    #: The words the user used for their reader, when they gave any. `audience`
    #: is the planning key; this is what goes on the title page.
    audience_label: str = ""
    needs_audience: bool = False

    data_model: PMIDataModel = Field(default_factory=PMIDataModel)
    quality_report: Optional[DataQualityReport] = None

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def conflicts(self) -> list[Conflict]:
        return self.data_model.conflicts


def _base() -> Path:
    return get_settings().storage_dir


# ------------------------------------------------------------------- sessions
def new_session() -> str:
    session_id = uuid.uuid4().hex[:12]
    uploads_dir(session_id).mkdir(parents=True, exist_ok=True)
    save_meta(session_id, {"session_id": session_id, "files": [], "runs": []})
    return session_id


def session_dir(session_id: str) -> Path:
    return _base() / session_id


def uploads_dir(session_id: str) -> Path:
    return session_dir(session_id) / "uploads"


def exists(session_id: str) -> bool:
    return session_dir(session_id).is_dir()


# ----------------------------------------------------------------- metadata
def save_meta(session_id: str, meta: dict) -> None:
    directory = session_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "meta.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8"
    )


def load_meta(session_id: str) -> Optional[dict]:
    path = session_dir(session_id) / "meta.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- project
def save_project(session_id: str, project: PMIProject) -> None:
    (session_dir(session_id) / "project.json").write_text(
        project.model_dump_json(indent=2), encoding="utf-8"
    )


def load_project(session_id: str) -> Optional[PMIProject]:
    path = session_dir(session_id) / "project.json"
    if not path.is_file():
        return None
    return PMIProject.model_validate_json(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ analysis
def save_analysis(analysis: SessionAnalysis) -> None:
    path = session_dir(analysis.session_id) / "analysis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    log.info("saved analysis for %s (%d entities, %d conflicts)",
             analysis.session_id, analysis.data_model.entity_count(),
             len(analysis.conflicts))


def load_analysis(session_id: str) -> Optional[SessionAnalysis]:
    path = session_dir(session_id) / "analysis.json"
    if not path.is_file():
        return None
    try:
        return SessionAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # A schema change between runs should not 500 the app — it should ask the user
        # to re-analyze, which costs them a click rather than an incident.
        log.warning("stored analysis for %s is unreadable (%s); re-analysis needed",
                    session_id, exc)
        return None


# ------------------------------------------------------------------- pending
# A tiny, durable pointer for a multi-turn chat exchange — which missing value
# the agent is currently asking for, whether it is waiting for a "regenerate?"
# yes/no, or which request should resume once files arrive. Deliberately *not*
# the transcript: the transcript is compacted
# (`chat_store`) and is explicitly not the source of truth. Only the pointer
# lives here; the list of gaps is always recomputed from `analysis.json`, so this
# file can never disagree with the data it points into.
def save_pending(session_id: str, state: dict) -> None:
    directory = session_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pending.json").write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )


def load_pending(session_id: str) -> Optional[dict]:
    path = session_dir(session_id) / "pending.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (TypeError, ValueError):
        return None


def clear_pending(session_id: str) -> None:
    (session_dir(session_id) / "pending.json").unlink(missing_ok=True)


def save_session_state(session_id: str, namespace: str, state: dict) -> None:
    """Save typed state to session storage (e.g., llm_loop state)."""
    path = session_dir(session_id) / f"{namespace}_state.json"
    import json
    with open(path, "w") as f:
        json.dump(state, f, indent=2, default=str)


def load_session_state(session_id: str, namespace: str) -> dict | None:
    """Load typed state from session storage."""
    path = session_dir(session_id) / f"{namespace}_state.json"
    if not path.exists():
        return None
    import json
    with open(path) as f:
        return json.load(f)
