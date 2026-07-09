"""FastAPI backend — serves the drag-and-drop UI and runs the agent.

Endpoints:
  GET  /                      the web UI
  POST /api/session           new session
  POST /api/upload            add files to a session (drag & drop target)
  POST /api/report            run the 7-step agent; may return needs_audience
  GET  /api/download/...      fetch generated outputs
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.agent.graph import run_agent
from app.agent.state import AgentState
from app.extractors import SUPPORTED_EXTENSIONS
from app.models.pmi import Audience
from app.storage import json_store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("pmi.api")

app = FastAPI(title="PMI Reporting Agent", version="0.1.0")

STATIC = Path(__file__).resolve().parents[1] / "static"


class ReportRequest(BaseModel):
    session_id: str
    request_text: str
    audience: str | None = None  # Executive | PMO | Finance
    conflict_strategy: str = "priority"  # "priority" (Option B) | "ask" (Option A)
    user_conflict_choices: dict[str, str] = {}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/api/session")
def create_session() -> dict:
    return {"session_id": json_store.new_session()}


@app.post("/api/upload")
async def upload(session_id: str, files: list[UploadFile] = File(...)) -> dict:
    meta = json_store.load_meta(session_id)
    if meta is None:
        raise HTTPException(404, "Unknown session")
    saved, rejected = [], []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            rejected.append(f.filename)
            continue
        dest = json_store.uploads_dir(session_id) / Path(f.filename).name
        dest.write_bytes(await f.read())
        saved.append(dest.name)
    meta["files"] = sorted({*meta.get("files", []), *saved})
    json_store.save_meta(session_id, meta)
    return {"saved": saved, "rejected": rejected, "files": meta["files"]}


@app.post("/api/report")
def report(req: ReportRequest) -> dict:
    meta = json_store.load_meta(req.session_id)
    if meta is None:
        raise HTTPException(404, "Unknown session")
    file_paths = [str(json_store.uploads_dir(req.session_id) / f)
                  for f in meta.get("files", [])]
    if not file_paths:
        raise HTTPException(400, "No files uploaded yet")

    audience = None
    if req.audience:
        try:
            audience = Audience(req.audience)
        except ValueError:
            raise HTTPException(400, f"Unknown audience: {req.audience}")

    state: AgentState = {
        "session_id": req.session_id,
        "file_paths": file_paths,
        "request_text": req.request_text,
        "audience": audience,
        "conflict_strategy": req.conflict_strategy,
        "user_conflict_choices": req.user_conflict_choices,
    }
    result = run_agent(state)

    # Step 2: audience unclear -> UI must ask (graph paused before extraction)
    if result.get("needs_audience") and not audience:
        return {"needs_audience": True,
                "options": [a.value for a in Audience],
                "detected_output_type": result.get("output_type")}

    model = result.get("data_model")
    conflicts = [c.model_dump() for c in model.conflicts] if model else []
    unresolved = [c for c in conflicts if not c.get("resolved_value")]
    outputs = [Path(p).name for p in result.get("output_files", [])]

    meta.setdefault("runs", []).append({
        "request": req.request_text,
        "audience": (result.get("audience") or audience or Audience.PMO).value
        if hasattr(result.get("audience") or audience or Audience.PMO, "value") else str(audience),
        "outputs": outputs,
    })
    json_store.save_meta(req.session_id, meta)

    return {
        "needs_audience": False,
        "audience": _aud_str(result.get("audience") or audience),
        "output_type": result.get("output_type"),
        "summary": result.get("summary_bullets", []),
        "outputs": outputs,
        "conflicts": conflicts,
        "unresolved_conflicts": unresolved,
        "stats": {
            "tasks": len(model.tasks) if model else 0,
            "milestones": len(model.milestones) if model else 0,
            "risks": len(model.risks) if model else 0,
            "budget_items": len(model.budget) if model else 0,
            "kpis": len(model.kpis) if model else 0,
        },
        "errors": result.get("errors", []),
    }


@app.get("/api/download/{session_id}/{filename}")
def download(session_id: str, filename: str) -> FileResponse:
    path = (Path(__file__).resolve().parents[1] / "output" / session_id / filename)
    if not path.exists() or ".." in filename:
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), filename=filename)


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict:
    meta = json_store.load_meta(session_id)
    if meta is None:
        raise HTTPException(404, "Unknown session")
    return meta


def _aud_str(a) -> str | None:
    return a.value if hasattr(a, "value") else a
