"""FastAPI backend (spec §15, §16 `app/api/`).

The flow the spec's §4 core user journey describes:

    POST /api/project                  name, reporting date, phase, source priority
    POST /api/upload                   drop the week's files in
    POST /api/analyze                  extract -> standardize -> check -> auto-resolve
    GET  /api/conflicts/{sid}          what the sources disagree about
    POST /api/conflicts/{sid}/resolve  the user decides (§9 Mode A)
    POST /api/generate                 build the deliverable from the stored analysis
    GET  /api/quality/{sid}            what this run could and could not do
    GET  /api/download/{sid}/{file}    fetch it

`POST /api/report` remains as the one-shot path.

Analysis and generation are separate endpoints for a concrete reason: resolving a
conflict must not re-run extraction. Re-extracting would re-pay for the vision calls
in §5.6 and re-roll the dice on what the model read out of each screenshot, so the
answer could change underneath the user between the question and their reply.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.graph import run_agent, run_analysis, run_generation
from app.agent.state import AgentState
from app.config import get_settings
from app.extractors import SUPPORTED_EXTENSIONS
from app.models.pmi import (
    Audience,
    IntegrationPhase,
    IntegrationType,
    PMIProject,
)
from app.storage import json_store
from app.storage.json_store import SessionAnalysis

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
log = logging.getLogger("pmi.api")

app = FastAPI(title="PMI Reporting Agent", version="0.2.0")

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_STATIC = REPO_ROOT / "static"


# ================================================================== schemas
class ProjectRequest(BaseModel):
    """§4 step 1: what the user can tell us that no file contains."""

    session_id: str
    project_name: str = "PMI Project"
    deal_name: Optional[str] = None
    acquirer_name: Optional[str] = None
    target_name: Optional[str] = None
    reporting_date: Optional[date] = None
    reporting_period: Optional[str] = None
    day_1_date: Optional[date] = None
    closing_date: Optional[date] = None
    integration_phase: IntegrationPhase = IntegrationPhase.UNKNOWN
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    #: §9: "The user should be able to override this rule."
    source_priority: Optional[dict[str, int]] = None


class AnalyzeRequest(BaseModel):
    session_id: str
    request_text: str
    audience: Optional[str] = None
    #: "ask" (Mode A) | "priority" (Mode B) | "hybrid" (Mode C, the default)
    conflict_strategy: Optional[str] = None


class ResolveRequest(BaseModel):
    """A file name to trust, or `{"value": "80"}` to state the truth outright (§9)."""

    choices: dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    session_id: str
    #: Generate anyway, with unresolved critical conflicts. Recorded in the outputs.
    force: bool = False


class ReportRequest(BaseModel):
    session_id: str
    request_text: str
    audience: Optional[str] = None
    conflict_strategy: str = "priority"
    user_conflict_choices: dict[str, Any] = Field(default_factory=dict)


# ================================================================== sessions
@app.post("/api/session")
def create_session() -> dict:
    return {"session_id": json_store.new_session()}


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict:
    meta = _meta_or_404(session_id)
    project = json_store.load_project(session_id)
    analysis = json_store.load_analysis(session_id)
    return {
        **meta,
        "project": project.model_dump(mode="json") if project else None,
        "analyzed": analysis is not None,
    }


@app.post("/api/project")
def set_project(req: ProjectRequest) -> dict:
    """§4 step 1. A masterplan does not state its own Day 1 date — the user does.

    This matters beyond bookkeeping: without a reporting date we cannot say what is
    overdue, and without a Day 1 date the check for Day-1 work scheduled after Day 1
    (TIME-004) silently cannot run. The data-quality report says so when they're absent.
    """
    _meta_or_404(req.session_id)

    project = PMIProject(
        project_id=req.session_id,
        project_name=req.project_name,
        deal_name=req.deal_name,
        acquirer_name=req.acquirer_name,
        target_name=req.target_name,
        reporting_date=req.reporting_date,
        reporting_period=req.reporting_period,
        day_1_date=req.day_1_date,
        closing_date=req.closing_date,
        integration_phase=req.integration_phase,
        integration_type=req.integration_type,
    )
    json_store.save_project(req.session_id, project)

    if req.source_priority:
        get_settings().source_priority = req.source_priority
        log.info("source priority overridden for %s: %s",
                 req.session_id, req.source_priority)

    return {"project": project.model_dump(mode="json")}


@app.post("/api/upload")
async def upload(session_id: str, files: list[UploadFile] = File(...)) -> dict:
    meta = _meta_or_404(session_id)
    settings = get_settings()
    limit = settings.upload_max_mb * 1024 * 1024

    saved: list[str] = []
    rejected: list[dict] = []

    for upload_file in files:
        name = Path(upload_file.filename or "").name
        suffix = Path(name).suffix.lower()

        if suffix not in SUPPORTED_EXTENSIONS:
            rejected.append({"file": name, "reason": f"unsupported type '{suffix}'"})
            continue

        payload = await upload_file.read()
        if len(payload) > limit:
            rejected.append({
                "file": name,
                "reason": f"larger than {settings.upload_max_mb} MB",
            })
            continue

        (json_store.uploads_dir(session_id) / name).write_bytes(payload)
        saved.append(name)

    meta["files"] = sorted({*meta.get("files", []), *saved})
    json_store.save_meta(session_id, meta)

    return {"saved": saved, "rejected": rejected, "files": meta["files"]}


# ================================================================== analysis
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    """Extract, standardize, check, auto-resolve. Stops before generating anything."""
    meta = _meta_or_404(req.session_id)
    file_paths = _file_paths(req.session_id, meta)

    state: AgentState = {
        "session_id": req.session_id,
        "file_paths": file_paths,
        "request_text": req.request_text,
        "audience": _audience(req.audience),
        "project": json_store.load_project(req.session_id),
        "conflict_strategy": req.conflict_strategy,
    }
    result = run_analysis(state)

    # §4: the audience could not be inferred, so ask rather than guess.
    if result.get("needs_audience"):
        return {
            "needs_audience": True,
            "options": [a.value for a in Audience],
            "detected_output_type": result.get("output_type"),
        }

    analysis = SessionAnalysis(
        session_id=req.session_id,
        request_text=req.request_text,
        output_type=result.get("output_type", "powerpoint"),
        topic=result.get("topic", "status"),
        audience=result.get("audience"),
        needs_audience=False,
        data_model=result["data_model"],
        quality_report=result.get("quality_report"),
        errors=result.get("errors", []),
        warnings=result.get("warnings", []),
    )
    json_store.save_analysis(analysis)

    return _analysis_payload(analysis)


@app.get("/api/conflicts/{session_id}")
def get_conflicts(session_id: str) -> dict:
    analysis = _analysis_or_404(session_id)
    return {
        "conflicts": [c.model_dump(mode="json") for c in analysis.conflicts],
        "unresolved": [
            c.model_dump(mode="json") for c in analysis.data_model.unresolved_conflicts()
        ],
    }


@app.post("/api/conflicts/{session_id}/resolve")
def resolve_conflicts_route(session_id: str, req: ResolveRequest) -> dict:
    """§9 Mode A. The user picks a source, or states the correct value outright."""
    from app.agent.consistency import apply_resolutions, resolve_conflicts

    analysis = _analysis_or_404(session_id)
    model = analysis.data_model

    model.conflicts = resolve_conflicts(
        model.conflicts, strategy="hybrid", user_choices=req.choices
    )
    apply_resolutions(model)

    # Re-score: resolving a conflict genuinely improves the data.
    from app.agent.data_quality import build_report

    analysis.quality_report = build_report(
        model, failed_files=_failed(analysis.errors), warnings=analysis.warnings
    )
    json_store.save_analysis(analysis)

    return _analysis_payload(analysis)


# ================================================================ generation
@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict:
    """Build the deliverable from the stored analysis. Never re-extracts."""
    meta = _meta_or_404(req.session_id)
    analysis = _analysis_or_404(req.session_id)

    blocking = analysis.data_model.unresolved_conflicts()
    blocking = [c for c in blocking if c.critical]

    if blocking and not req.force:
        # §9 Mode C: a critical conflict means two of our own sources contradict each
        # other about something that changes the management message. Producing a deck
        # that silently picks one would be the single most damaging thing this system
        # could do, so it refuses until a person decides.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "unresolved_critical_conflicts",
                "message": (
                    f"{len(blocking)} critical conflict(s) must be resolved before a "
                    f"report can be generated. Resolve them, or pass force=true to "
                    f"generate anyway (the outputs will say so)."
                ),
                "conflicts": [c.model_dump(mode="json") for c in blocking],
            },
        )

    state: AgentState = {
        "session_id": req.session_id,
        "request_text": analysis.request_text,
        "output_type": analysis.output_type,
        "topic": analysis.topic,
        "audience": analysis.audience,
        "data_model": analysis.data_model,
        "quality_report": analysis.quality_report,
        "errors": analysis.errors,
        "warnings": analysis.warnings,
        "conflict_strategy": "hybrid",
    }
    result = run_generation(state)

    outputs = [Path(p).name for p in result.get("output_files", [])]
    meta.setdefault("runs", []).append({
        "request": analysis.request_text,
        "audience": _audience_str(analysis.audience),
        "outputs": outputs,
        "forced": bool(blocking and req.force),
    })
    json_store.save_meta(req.session_id, meta)

    return {
        "outputs": outputs,
        "summary": result.get("summary_bullets", []),
        "audience": _audience_str(analysis.audience),
        "output_type": analysis.output_type,
        "generated_with_unresolved_conflicts": [
            c.conflict_id for c in blocking
        ] if blocking else [],
        "errors": result.get("errors", []),
    }


@app.get("/api/quality/{session_id}")
def get_quality(session_id: str) -> dict:
    from app.agent.data_quality import summarize

    analysis = _analysis_or_404(session_id)
    report = analysis.quality_report
    if report is None:
        raise HTTPException(404, "No data-quality report for this session")

    return {
        "report": report.model_dump(mode="json"),
        "summary": summarize(report),
        "low_confidence_items": [
            {"type": kind, "label": label, "confidence": confidence}
            for kind, label, confidence in analysis.data_model.low_confidence_items()
        ],
        "validation_issues": [
            i.model_dump(mode="json") for i in analysis.data_model.validation_issues
        ],
    }


# =============================================================== one-shot path
@app.post("/api/report")
def report(req: ReportRequest) -> dict:
    """Analysis + generation in one call."""
    meta = _meta_or_404(req.session_id)
    file_paths = _file_paths(req.session_id, meta)
    audience = _audience(req.audience)

    state: AgentState = {
        "session_id": req.session_id,
        "file_paths": file_paths,
        "request_text": req.request_text,
        "audience": audience,
        "project": json_store.load_project(req.session_id),
        "conflict_strategy": req.conflict_strategy,
        "user_conflict_choices": req.user_conflict_choices,
    }
    result = run_agent(state)

    if result.get("needs_audience") and not audience:
        return {
            "needs_audience": True,
            "options": [a.value for a in Audience],
            "detected_output_type": result.get("output_type"),
        }

    model = result.get("data_model")
    conflicts = [c.model_dump(mode="json") for c in model.conflicts] if model else []
    outputs = [Path(p).name for p in result.get("output_files", [])]
    quality = result.get("quality_report")

    meta.setdefault("runs", []).append({
        "request": req.request_text,
        "audience": _audience_str(result.get("audience") or audience),
        "outputs": outputs,
    })
    json_store.save_meta(req.session_id, meta)

    return {
        "needs_audience": False,
        "audience": _audience_str(result.get("audience") or audience),
        "output_type": result.get("output_type"),
        "summary": result.get("summary_bullets", []),
        "outputs": outputs,
        "conflicts": conflicts,
        "unresolved_conflicts": [c for c in conflicts if not c.get("resolved_value")],
        "quality_score": quality.score if quality else None,
        "stats": _stats(model),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
    }


@app.get("/api/download/{session_id}/{filename}")
def download(session_id: str, filename: str) -> FileResponse:
    out_dir = (get_settings().output_dir / session_id).resolve()
    path = (out_dir / filename).resolve()

    # Path traversal: resolve BOTH sides, then confirm containment. The original guard
    # checked `".." in filename` *after* stat-ing the path — and since a single URL
    # segment never literally contains "..", it never fired at all.
    if not path.is_file() or not path.is_relative_to(out_dir):
        raise HTTPException(404, "File not found")

    return FileResponse(str(path), filename=path.name)


# ================================================================== frontend
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    dist = get_settings().frontend_dist
    built = dist / "index.html"
    if built.is_file():
        return built.read_text(encoding="utf-8")

    legacy = LEGACY_STATIC / "index.html"
    if legacy.is_file():
        return legacy.read_text(encoding="utf-8")

    return _UNBUILT

_UNBUILT = """<!doctype html>
<title>PMI Reporting Agent</title>
<style>body{font:16px/1.6 system-ui;margin:4rem auto;max-width:40rem;padding:0 1rem}
code{background:#f4f4f4;padding:.15rem .4rem;border-radius:4px}</style>
<h1>PMI Reporting Agent</h1>
<p>The API is running, but the frontend has not been built.</p>
<pre><code>npm --prefix frontend ci
npm --prefix frontend run build</code></pre>
<p>...or run the whole stack with <code>docker compose up</code>.</p>
<p>The API works regardless — see <a href="/docs">/docs</a>.</p>
"""


def _mount_frontend() -> None:
    assets = get_settings().frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
        log.info("serving built frontend from %s", assets.parent)


_mount_frontend()


# =================================================================== helpers
def _meta_or_404(session_id: str) -> dict:
    meta = json_store.load_meta(session_id)
    if meta is None:
        raise HTTPException(404, "Unknown session")
    return meta


def _analysis_or_404(session_id: str) -> SessionAnalysis:
    analysis = json_store.load_analysis(session_id)
    if analysis is None:
        raise HTTPException(404, "No analysis for this session — POST /api/analyze first")
    return analysis


def _file_paths(session_id: str, meta: dict) -> list[str]:
    paths = [str(json_store.uploads_dir(session_id) / f) for f in meta.get("files", [])]
    if not paths:
        raise HTTPException(400, "No files uploaded yet")
    return paths


def _audience(raw: Optional[str]) -> Optional[Audience]:
    if not raw:
        return None
    try:
        return Audience(raw)
    except ValueError:
        raise HTTPException(
            400, f"Unknown audience {raw!r}. Options: {[a.value for a in Audience]}"
        )


def _audience_str(audience) -> Optional[str]:
    return audience.value if hasattr(audience, "value") else audience


def _failed(errors: list[str]) -> list[str]:
    return [e.split(":", 1)[0] for e in errors]


def _stats(model) -> dict:
    if model is None:
        return {}
    return {
        "workstreams": len(model.workstreams),
        "tasks": len(model.tasks),
        "milestones": len(model.milestones),
        "risks": len(model.risks),
        "issues": len(model.issues),
        "dependencies": len(model.dependencies),
        "decisions": len(model.decisions),
        "budget_items": len(model.budget),
        "synergies": len(model.synergies),
        "kpis": len(model.kpis),
    }


def _analysis_payload(analysis: SessionAnalysis) -> dict:
    model = analysis.data_model
    report = analysis.quality_report

    return {
        "needs_audience": False,
        "session_id": analysis.session_id,
        "audience": _audience_str(analysis.audience),
        "output_type": analysis.output_type,
        "stats": _stats(model),
        "quality_score": report.score if report else None,
        "conflicts": [c.model_dump(mode="json") for c in model.conflicts],
        "unresolved_conflicts": [
            c.model_dump(mode="json") for c in model.unresolved_conflicts()
        ],
        "blocking_conflicts": [
            c.conflict_id for c in model.unresolved_conflicts() if c.critical
        ],
        "validation_issues": [
            i.model_dump(mode="json") for i in model.validation_issues
        ],
        "low_confidence_items": [
            {"type": kind, "label": label, "confidence": confidence}
            for kind, label, confidence in model.low_confidence_items()
        ],
        "errors": analysis.errors,
        "warnings": analysis.warnings,
    }
