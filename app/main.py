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

from app.agent.graph import run_generation
from app.agent.state import AgentState
from app.config import get_settings
from app.extractors import SUPPORTED_EXTENSIONS
from app.models.pmi import (
    Audience,
    IntegrationPhase,
    IntegrationType,
    PMIProject,
)
from app.report import store as report_store
from app.report.render.markdown import render_blocks, render_markdown
from app.storage import chat_store, json_store
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
    #: Render the approved content as something else — "powerpoint" | "word" |
    #: "pdf" | "html" | "excel" | "chart". Omitted keeps whatever the original
    #: request asked for. Re-rendering is cheap: the content is already planned,
    #: so no LLM call and no extraction happens, and the wording cannot change.
    format: Optional[str] = None


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
        # §9's override lives on the project, not on the settings singleton.
        # Writing it to settings made one session's judgement about which files
        # to trust silently govern how every other session in the process
        # resolved its conflicts — and it persisted until restart.
        source_priority=req.source_priority,
    )
    json_store.save_project(req.session_id, project)

    if req.source_priority:
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
    from app.agent.analysis import ensure_analysis

    meta = _meta_or_404(req.session_id)
    _file_paths(req.session_id, meta)          # 400s when nothing was uploaded

    # One analysis constructor, shared with the chat path. Two of them meant two
    # answers to "what did we read", and which one you got depended on the
    # endpoint you came in through.
    analysis, needs_audience = ensure_analysis(
        req.session_id,
        request_text=req.request_text,
        audience=_audience(req.audience),
        conflict_strategy=req.conflict_strategy,
        # An explicit POST to /analyze is a request to re-read, even when the
        # file set has not moved — that is what the endpoint is for.
        force=True,
    )

    # §4: the audience could not be inferred, so ask rather than guess.
    if needs_audience:
        return {
            "needs_audience": True,
            "options": [a.value for a in Audience],
            "detected_output_type": None,
        }

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

    # Render the version the user read and approved, when there is one. Falls
    # back to planning fresh, so a caller that never opens the preview behaves
    # exactly as it did before this existed.
    approved = report_store.load(req.session_id)
    if approved is not None and report_store.is_stale(
        approved, analysis.data_model, analysis.quality_report
    ):
        # The analysis moved after this was planned — almost always because a
        # conflict was resolved. Rendering it would state the figure the user
        # has since corrected, so it is discarded rather than trusted.
        log.info("stored content for %s is stale; re-planning", req.session_id)
        approved = None

    state: AgentState = {
        "session_id": req.session_id,
        "request_text": analysis.request_text,
        "output_type": req.format or analysis.output_type,
        "topic": analysis.topic,
        "audience": analysis.audience,
        "data_model": analysis.data_model,
        "quality_report": analysis.quality_report,
        "errors": analysis.errors,
        "warnings": analysis.warnings,
        "conflict_strategy": "hybrid",
        "report_content": approved,
    }
    result = run_generation(state)

    outputs = [Path(p).name for p in result.get("output_files", [])]
    meta.setdefault("runs", []).append({
        "request": analysis.request_text,
        "audience": _audience_str(analysis.audience),
        "content_version": approved.version if approved else None,
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


# ============================================================ report content
# The §4 loop this enables: plan -> read it as text -> revise -> render. The
# expensive half (extraction, vision) already happened during analysis and is
# never repeated here, so a user can iterate on wording for free.
def _content_payload(content, analysis, *, stale: bool = False) -> dict:
    return {
        "version": content.version,
        "stale": stale,
        "audience": _audience_str(content.audience),
        "markdown": render_markdown(content),
        "sections": [
            {
                "section_id": s.section_id,
                "label": s.label,
                "headline": s.headline,
                "origin": s.origin,
                "block_kinds": [b.kind for b in s.blocks],
                "empty_explanation": s.empty_explanation,
            }
            for s in content.narrative()
        ],
        # Structured blocks, carrying each cell's identity so the preview can
        # offer to edit it. Kept separate from `sections` above, which several
        # callers already read for its headline/label shape.
        "blocks": render_blocks(content),
        "warnings": content.warnings,
    }


@app.post("/api/content/{session_id}")
def plan_content_route(session_id: str) -> dict:
    """Plan (or re-plan) the report and store it as a new version."""
    from app.report.pipeline import plan_for_session

    analysis = _analysis_or_404(session_id)
    stored = plan_for_session(session_id, analysis)
    return _content_payload(stored, analysis)


@app.get("/api/content/{session_id}")
def get_content(session_id: str, version: Optional[int] = None) -> dict:
    """The current plan as text. 404 when nothing has been planned yet."""
    analysis = _analysis_or_404(session_id)
    content = report_store.load(session_id, version)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_content",
                    "message": "Nothing has been planned for this session yet. "
                               "POST to this path to plan it."},
        )

    stale = report_store.is_stale(
        content, analysis.data_model, analysis.quality_report
    )
    return _content_payload(content, analysis, stale=stale)


@app.get("/api/content/{session_id}/versions")
def list_content_versions(session_id: str) -> dict:
    _analysis_or_404(session_id)
    return {"versions": [v.model_dump(mode="json")
                         for v in report_store.versions(session_id)]}


@app.post("/api/content/{session_id}/revert")
def revert_content(session_id: str, version: int) -> dict:
    """Restore an earlier version by appending it again — nothing is erased."""
    analysis = _analysis_or_404(session_id)
    restored = report_store.revert(session_id, version)
    if restored is None:
        raise HTTPException(status_code=404,
                            detail={"error": "no_such_version",
                                    "message": f"No version {version}."})
    stale = report_store.is_stale(
        restored, analysis.data_model, analysis.quality_report
    )
    return _content_payload(restored, analysis, stale=stale)


@app.get("/api/models")
def list_models() -> dict:
    """What the picker offers, and which options are actually usable.

    Served rather than hard-coded in the frontend because §21.10 confines model
    IDs to `config.py`; a list in JSX would put them somewhere the grep test
    cannot see and could drift from what the backend accepts.
    """
    from app.config import MODEL_CATALOGUE

    settings = get_settings()
    configured = {
        provider: bool(settings.api_key_for(provider))
        for provider in ("anthropic", "openai")
    }

    return {
        "models": [
            {**choice.model_dump(), "available": configured.get(choice.provider, False)}
            for choice in MODEL_CATALOGUE
        ],
        "providers": configured,
        "default": {"provider": settings.llm_provider, "model": settings.llm_model},
        # With no key at all the app still runs end to end on the deterministic
        # path; the picker should say so rather than looking broken.
        "keyless": not settings.llm_configured(),
    }


# ==================================================================== chats
# A chat owns a session id; uploads, analysis and outputs keep living exactly
# where they did. That keeps the expensive artefacts out of the conversation's
# failure domain, and lets every route above keep working untouched.
class NewChatRequest(BaseModel):
    title: str = "New chat"
    provider: Optional[str] = None
    model: Optional[str] = None
    #: Optional home for the chat. Omitted / null starts it outside any project.
    project_id: Optional[str] = None


class NewProjectRequest(BaseModel):
    name: str = "New project"
    icon: str = "📁"
    knowledge: str = ""


class PatchProjectRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    knowledge: Optional[str] = None


class PatchChatRequest(BaseModel):
    title: Optional[str] = None
    archived: Optional[bool] = None
    provider: Optional[str] = None
    model: Optional[str] = None


class ChatMessageRequest(BaseModel):
    text: str


def _chat_or_404(chat_id: str):
    chat = chat_store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail={"error": "no_such_chat"})
    return chat


@app.post("/api/chats")
def create_chat(req: NewChatRequest) -> dict:
    """A chat and its session are created together — one conversation, one
    working set of files."""
    session_id = json_store.new_session()
    chat = chat_store.create_chat(session_id, req.title,
                                  provider=req.provider, model=req.model,
                                  project_id=req.project_id)
    return {"chat": chat.model_dump(), "session_id": session_id}


# ================================================================= projects
# A project is a folder over chats plus a scratchpad of standing knowledge.
# It owns no session and no files of its own — deleting one only unfiles its
# chats (see chat_store.delete_project), never destroys them.
def _project_or_404(project_id: str):
    project = chat_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"error": "no_such_project"})
    return project


@app.post("/api/projects")
def create_project(req: NewProjectRequest) -> dict:
    project = chat_store.create_project(req.name, icon=req.icon,
                                        knowledge=req.knowledge)
    return {"project": project.model_dump()}


@app.get("/api/projects")
def list_projects() -> dict:
    return {"projects": [p.model_dump() for p in chat_store.list_projects()]}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return {"project": _project_or_404(project_id).model_dump()}


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, req: PatchProjectRequest) -> dict:
    _project_or_404(project_id)
    project = chat_store.update_project(
        project_id, name=req.name, icon=req.icon, knowledge=req.knowledge,
    )
    return {"project": project.model_dump()}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Deletes the project only; its chats are pushed back to the top level."""
    _project_or_404(project_id)
    return {"deleted": chat_store.delete_project(project_id)}


# ================================================= unified conversation (§Phase 3)
class ChatRequest(BaseModel):
    """The one endpoint the workspace talks to (spec §"API Direction").

    The frontend no longer sequences analyze → resolve → generate → download by
    hand; it sends a message (and optionally the files it just uploaded, the draft
    on screen, and any selected text) and gets back Markdown plus structured
    actions."""

    project_id: str
    message: str
    chat_id: Optional[str] = None
    file_ids: Optional[list[str]] = None
    active_draft_id: Optional[str] = None
    selected_text: Optional[str] = None


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    from app.project import orchestrator

    resp = orchestrator.respond(
        req.project_id, req.message, chat_id=req.chat_id,
        active_draft_id=req.active_draft_id, selected_text=req.selected_text)
    return resp.model_dump()


@app.get("/api/projects/{project_id}/knowledge")
def get_project_knowledge(project_id: str) -> dict:
    """The project's current knowledge state — version, size, and the conflict gate.

    Read by the workspace on open to show the status pill and decide whether a
    report can be drafted yet."""
    from app.project import conflict_impact
    from app.project.json_repositories import default_repositories

    knowledge = default_repositories().knowledge.current(project_id)
    if knowledge is None:
        return {"exists": False, "version": 0, "entity_count": 0}
    return {
        "exists": True,
        "version": knowledge.version,
        "entity_count": knowledge.entity_count(),
        "conflict_state": conflict_impact.assess(knowledge).model_dump(),
    }


@app.post("/api/projects/{project_id}/files")
async def upload_project_files(project_id: str,
                               files: list[UploadFile] = File(...)) -> dict:
    """Continuous ingestion: every uploaded file becomes a source, the knowledge
    base re-derives incrementally, and affected drafts are flagged stale (§Phase 1)."""
    import tempfile

    from app.project import drafts as project_drafts
    from app.project import files as project_files
    from app.project.rebuild import rebuild

    settings = get_settings()
    limit = settings.upload_max_mb * 1024 * 1024
    ingested: list[dict] = []
    rejected: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        for upload_file in files:
            name = Path(upload_file.filename or "").name
            payload = await upload_file.read()
            if len(payload) > limit:
                rejected.append({"file": name,
                                 "reason": f"larger than {settings.upload_max_mb} MB"})
                continue
            tmp_path = Path(tmp) / name
            tmp_path.write_bytes(payload)
            record = project_files.ingest_file(project_id, tmp_path)
            ingested.append(record.model_dump())

    knowledge = rebuild(project_id, trigger="upload")
    stale = project_drafts.mark_stale_if_affected(project_id)
    return {
        "ingested": ingested,
        "rejected": rejected,
        "knowledge_version": knowledge.version,
        "stale_drafts": [{"draft_id": d.draft_id, "status": d.status} for d in stale],
    }


# ============================================================ editable drafts (§Phase 2)
class CreateDraftRequest(BaseModel):
    audience: Optional[str] = None
    audience_label: str = ""
    title: Optional[str] = None
    draft_type: str = "custom"
    chat_id: Optional[str] = None


class PatchDraftRequest(BaseModel):
    """A direct user edit. Either the whole text (`content`)/`title`, or one
    section (`section_id` + `text`). Every edit mints a new draft version."""

    title: Optional[str] = None
    content: Optional[str] = None
    section_id: Optional[str] = None
    text: Optional[str] = None
    chat_id: Optional[str] = None


class RegenerateSectionRequest(BaseModel):
    section_id: str
    chat_id: Optional[str] = None


class RestoreVersionRequest(BaseModel):
    version: int
    chat_id: Optional[str] = None


def _drafting():
    """Imported lazily so the draft layer's imports never slow app startup."""
    from app.project import drafting
    from app.project.drafting import DraftError

    return drafting, DraftError


@app.post("/api/projects/{project_id}/drafts")
def create_draft(project_id: str, req: CreateDraftRequest) -> dict:
    _project_or_404(project_id)
    drafting, DraftError = _drafting()
    try:
        draft = drafting.create_draft(
            project_id, audience=req.audience, audience_label=req.audience_label,
            title=req.title, draft_type=req.draft_type, chat_id=req.chat_id)
    except DraftError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)})
    return {"draft": draft.model_dump()}


@app.get("/api/projects/{project_id}/drafts")
def list_drafts(project_id: str) -> dict:
    _project_or_404(project_id)
    from app.project.json_repositories import default_repositories

    return {"drafts": [d.model_dump()
                       for d in default_repositories().drafts.list(project_id)]}


@app.get("/api/projects/{project_id}/drafts/{draft_id}")
def get_draft(project_id: str, draft_id: str) -> dict:
    from app.project.json_repositories import default_repositories

    draft = default_repositories().drafts.get(project_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail={"error": "no_such_draft"})
    return {"draft": draft.model_dump()}


@app.patch("/api/projects/{project_id}/drafts/{draft_id}")
def patch_draft(project_id: str, draft_id: str, req: PatchDraftRequest) -> dict:
    drafting, DraftError = _drafting()
    try:
        if req.section_id is not None and req.text is not None:
            draft = drafting.edit_section(project_id, draft_id, req.section_id,
                                          req.text, chat_id=req.chat_id)
        else:
            draft = drafting.edit_draft(project_id, draft_id, title=req.title,
                                        content=req.content, chat_id=req.chat_id)
    except DraftError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)})
    return {"draft": draft.model_dump()}


@app.post("/api/projects/{project_id}/drafts/{draft_id}/regenerate-section")
def regenerate_section(project_id: str, draft_id: str,
                       req: RegenerateSectionRequest) -> dict:
    drafting, DraftError = _drafting()
    try:
        draft = drafting.regenerate_section(project_id, draft_id, req.section_id,
                                            chat_id=req.chat_id)
    except DraftError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)})
    return {"draft": draft.model_dump()}


@app.get("/api/projects/{project_id}/drafts/{draft_id}/versions")
def list_draft_versions(project_id: str, draft_id: str) -> dict:
    from app.project.json_repositories import default_repositories

    versions = default_repositories().drafts.list_versions(project_id, draft_id)
    return {"versions": [v.model_dump() for v in versions]}


@app.post("/api/projects/{project_id}/drafts/{draft_id}/restore-version")
def restore_draft_version(project_id: str, draft_id: str,
                          req: RestoreVersionRequest) -> dict:
    drafting, DraftError = _drafting()
    try:
        draft = drafting.restore_version(project_id, draft_id, req.version,
                                         chat_id=req.chat_id)
    except DraftError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)})
    return {"draft": draft.model_dump()}


# ============================================================ export (§Phase 4)
class ExportRequest(BaseModel):
    format: str
    chat_id: Optional[str] = None


@app.post("/api/projects/{project_id}/drafts/{draft_id}/export")
def export_draft(project_id: str, draft_id: str, req: ExportRequest) -> dict:
    """Export the latest saved draft to a file (spec §"Report and Export Separation").

    The file is built from the saved draft, so it matches the approved text — it does
    not re-plan a different narrative (Scenario 6)."""
    from app.project import exporting

    try:
        path = exporting.export_draft(project_id, draft_id, req.format,
                                      chat_id=req.chat_id)
    except exporting.ExportError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    return {"file": path.name,
            "download_url": f"/api/projects/{project_id}/exports/{path.name}"}


@app.get("/api/projects/{project_id}/exports/{filename}")
def download_export(project_id: str, filename: str) -> FileResponse:
    from app.project import paths as project_paths

    # Guard against path traversal: only a bare filename inside the exports dir.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail={"error": "bad_filename"})
    path = project_paths.exports_dir(project_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"error": "no_such_export"})
    return FileResponse(str(path), filename=filename)


@app.get("/api/chats")
def list_chats(include_archived: bool = False) -> dict:
    return {"chats": [c.model_dump()
                      for c in chat_store.list_chats(include_archived=include_archived)]}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str) -> dict:
    """The whole transcript, for reopening a chat from the sidebar."""
    from app.agent import budget

    chat = _chat_or_404(chat_id)
    return {
        "chat": chat.model_dump(),
        # Compacted turns are included: the user can still read what was said,
        # even though a model no longer receives it.
        "messages": [m.model_dump() for m in chat_store.list_messages(chat_id)],
        "usage": budget.usage(chat),
    }


@app.patch("/api/chats/{chat_id}")
def patch_chat(chat_id: str, req: PatchChatRequest) -> dict:
    chat = _chat_or_404(chat_id)
    if req.title is not None:
        chat = chat_store.rename_chat(chat_id, req.title)
    if req.archived is not None:
        chat = chat_store.archive_chat(chat_id, req.archived)
    if req.provider is not None or req.model is not None:
        chat = chat_store.set_model(chat_id, provider=req.provider, model=req.model)
    return {"chat": chat.model_dump()}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict:
    """Deletes the conversation only.

    Uploads, the analysis and any generated files survive. Discarding an
    extraction — which cost real money in vision calls — because someone tidied
    their sidebar would be a far bigger consequence than "delete chat" implies.
    """
    _chat_or_404(chat_id)
    return {"deleted": chat_store.delete_chat(chat_id)}


@app.post("/api/chats/{chat_id}/messages")
def post_chat_message(chat_id: str, req: ChatMessageRequest) -> dict:
    """One conversational turn: record what the user said, act, reply."""
    from app.agent.conversation import Reply, respond

    chat = _chat_or_404(chat_id)
    user_message = chat_store.add_message(chat_id, "user", {"text": req.text})

    # A chat turn must never surface as a bare 500. The frontend has no way to
    # render one except as "something went wrong", which tells the user nothing
    # and loses the turn; a notice carrying the reason at least says what broke
    # and leaves the conversation usable.
    try:
        replies = respond(chat, req.text)
    except Exception as exc:                                  # noqa: BLE001
        log.exception("chat turn failed for %s", chat_id)
        replies = [Reply(kind="notice", content={
            "text": "I hit an error working on that, so nothing was changed.",
            "reasons": [f"{type(exc).__name__}: {exc}"],
        })]

    stored = [
        chat_store.add_message(chat_id, "agent", reply.content, kind=reply.kind)
        for reply in replies
    ]

    # Keep the conversation inside the chosen model's window. Done after the
    # turn rather than before it, so the reply the user is waiting for is never
    # delayed by housekeeping.
    from app.agent import budget

    refreshed = chat_store.get_chat(chat_id)
    compaction = budget.compact(refreshed) if budget.should_compact(refreshed) else None

    return {
        "messages": (
            [user_message.model_dump()]
            + [m.model_dump() for m in stored]
            + ([compaction.model_dump()] if compaction else [])
        ),
        "chat": chat_store.get_chat(chat_id).model_dump(),
        "usage": budget.usage(chat_store.get_chat(chat_id)),
    }


class CellEditRequest(BaseModel):
    """One cell of the preview, edited in place."""

    block_id: str
    row: int
    column: int
    value: str


@app.post("/api/content/{session_id}/cell")
def edit_cell(session_id: str, req: CellEditRequest) -> dict:
    """Write a preview edit **through to the data model**, then re-plan.

    The tempting shortcut is to patch the stored `ReportContent` and return it —
    it is one line and the preview updates immediately. It is also wrong: the
    deck, the workbook and the document are all planned from `PMIDataModel`, so
    the edited number would appear in the preview and nowhere else, and the
    formats would disagree about a figure the user had personally corrected.

    So the cell's `ref` is resolved back to an entity field, the value goes
    through the same `apply_and_persist` engine as every other correction (with
    the same provenance discipline — it is recorded as the user's), and the
    report is re-planned from the updated model. Every format then agrees,
    because there is still only one place any of them reads from.
    """
    from app.agent.corrections import apply_and_persist
    from app.models.quality import ValidationIssue

    analysis = _analysis_or_404(session_id)
    content = report_store.load(session_id)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_content",
                    "message": "Plan the report before editing it."},
        )

    cell = _find_cell(content, req.block_id, req.row, req.column)
    if cell is None:
        # A rejection is a normal outcome and comes back as a message, not a
        # 4xx the UI has to translate — the same discipline as `/issues/fill`.
        return {"applied": False,
                "message": "That cell is no longer in the report — it may have "
                           "been re-planned since you opened it."}

    if cell.ref is None or not cell.ref.field:
        return {"applied": False,
                "message": "This value is computed from other fields, so there "
                           "is nothing to write it back to. Correct the figures "
                           "it is derived from instead."}

    result = apply_and_persist(analysis, ValidationIssue(
        check_id="PREVIEW-EDIT",
        family="completeness",
        entity_type=cell.ref.entity_type,
        entity_id=cell.ref.entity_id,
        entity_label=cell.text,
        field=cell.ref.field,
        message="value corrected by the user in the preview",
    ), req.value)

    if not result.applied:
        return {"applied": False, "message": result.message}

    _record_user_value(session_id, cell, req.value, result)
    replanned = plan_content_route(session_id)
    return {"applied": True, "message": result.message, **replanned}


def _find_cell(content, block_id: str, row: int, column: int):
    for section in content.sections:
        for block in section.blocks:
            if block.block_id != block_id or block.kind != "table":
                continue
            if 0 <= row < len(block.rows) and 0 <= column < len(block.rows[row]):
                return block.rows[row][column]
    return None


def _record_user_value(session_id: str, cell, raw: str, result) -> None:
    """The KB half — so the value is known to be the user's next turn too, and
    so the fingerprint moves and any other draft is re-planned."""
    from app.agent import knowledge

    kb = knowledge.load(session_id)
    kb.record_value(knowledge.UserValue(
        entity_type=cell.ref.entity_type, entity_id=cell.ref.entity_id,
        label=cell.text, field=cell.ref.field or "",
        value=result.value, raw=raw,
    ))
    knowledge.save(kb)


class ProseEditRequest(BaseModel):
    """A card's narrative text, rewritten in the preview."""

    block_id: str
    text: str


@app.post("/api/content/{session_id}/prose")
def edit_prose(session_id: str, req: ProseEditRequest) -> dict:
    """Save the user's rewritten prose for one block, then re-plan.

    The split this enforces is the whole reason a card's text and its table are
    edited by different routes: **prose is the user's to write, data is not.**
    So the new text is checked against the figures the report already holds
    (`guard.check_text`, the §11 backstop) — a *number* the report does not state
    is refused with a pointer to the data edit that would make it true, which
    then reaches every format. Text that only rephrases is stored as an override
    in the knowledge base and survives the next re-plan, exactly like a supplied
    value does.
    """
    from app.agent import knowledge
    from app.report import guard

    analysis = _analysis_or_404(session_id)
    content = report_store.load(session_id)
    if content is None:
        return {"applied": False,
                "message": "Plan the report before editing it."}

    block = _find_prose_block(content, req.block_id)
    if block is None:
        return {"applied": False,
                "message": "That text is no longer in the report — it may have "
                           "been re-planned since you opened it."}

    # The user is rewriting text the report already shows, so a figure already in
    # this block is one the report already states — it must not be rejected as if
    # the user had just invented it. This matters most for the executive summary,
    # whose figures (the conflict percentages, milestone dates) drop out of the
    # fact corpus once the block has been LLM-revised or previously edited, which
    # would otherwise make the block impossible to edit against its own numbers. A
    # genuinely new number, absent from both the corpus and this block, is still
    # refused.
    allowed = content.numeric_corpus_cached() | guard.numbers_in(_block_text(block))
    offending = guard.check_text(req.text, allowed)
    if offending:
        return {"applied": False,
                "message": guard.describe(offending, req.text)
                + " Set it as data first — e.g. “the due date for the ERP "
                  "cutover is 12-08-2026” — and it will appear in every format."}

    kb = knowledge.load(session_id)
    kb.set_prose_override(req.block_id, req.text)
    knowledge.save(kb)

    replanned = plan_content_route(session_id)
    return {"applied": True,
            "message": "Saved your text — it will appear in every format.",
            **replanned}


def _find_prose_block(content, block_id: str):
    """The prose or bullets block with this id, or `None`. Tables and tiles are
    data, edited through the cell route, not here."""
    for section in content.sections:
        for block in section.blocks:
            if block.block_id == block_id and block.kind in ("prose", "bullets"):
                return block
    return None


def _block_text(block) -> str:
    """The block's current text as one string — bullets joined the way the
    preview edits them, prose as-is. Used to grant a prose edit the figures the
    block already shows."""
    if block.kind == "bullets":
        return "\n".join(item.text for item in block.items)
    return getattr(block, "text", "") or ""


@app.post("/api/chats/{chat_id}/files")
async def add_chat_files(chat_id: str, files: list[UploadFile] = File(...)) -> dict:
    """Uploading files mid-chat is a turn, with an answer.

    It used to be a silent side effect: `POST /api/upload` wrote the bytes, and
    the "3 files ready" line the user saw was invented client-side and vanished
    when the chat was reopened. Nothing server-side had happened, so the report
    stayed built from the original files while looking current — and the user had
    no way to tell.

    Now the turn is stored, every file is re-read (not just the new ones — a new
    tracker can contradict an old one, and a conflict only exists between two
    sources considered together), and the reply says what actually changed.
    """
    chat = _chat_or_404(chat_id)
    session_id = chat.session_id
    before = _session_snapshot(session_id)

    saved = await upload(session_id, files)
    names = saved["saved"]

    chat_store.add_message(chat_id, "user",
                           {"files": [{"name": n} for n in names],
                            "text": ""},
                           kind="files")

    replies = _merge_uploaded(chat, before, names, saved.get("rejected", []))
    stored = [chat_store.add_message(chat_id, "agent", reply.content,
                                     kind=reply.kind)
              for reply in replies]

    return {
        "saved": names,
        "rejected": saved.get("rejected", []),
        "files": saved["files"],
        "messages": [m.model_dump() for m in stored],
        "chat": chat_store.get_chat(chat_id).model_dump(),
    }


def _session_snapshot(session_id: str) -> dict:
    """What the session knew before the upload, for the "what changed" reply."""
    analysis = json_store.load_analysis(session_id)
    if analysis is None:
        return {}
    return {
        "entities": analysis.data_model.entity_count(),
        "conflicts": len(analysis.data_model.unresolved_conflicts()),
        "score": getattr(analysis.quality_report, "score", None),
        "files": list(analysis.data_model.source_files),
    }


def _merge_uploaded(chat, before: dict, added: list[str], rejected: list[dict]):
    """Re-read everything and say what moved."""
    from app.agent import knowledge
    from app.agent.conversation import Reply, _analyse, _found
    from app.report import chat_format as chat_fmt

    replies = []
    if rejected:
        replies.append(Reply(kind="notice", content={
            "text": f"I couldn't read {len(rejected)} of those.",
            "reasons": [f"{r['file']}: {r['reason']}" for r in rejected],
        }))

    if not added:
        return replies or [Reply(kind="text", content={
            "text": "Nothing was added, so nothing changed."})]

    if not before:
        # Nothing had been read yet: this is the first upload, and the useful
        # answer is "what do you need?", not a diff against nothing.
        return replies + [Reply(kind="text", content={"text": chat_fmt.reply(
            f"{chat_fmt.count(len(added), 'file')} ready",
            body=chat_fmt.bullets(added),
            action="Reading your files and analyzing the data now",
        )})]

    kb = knowledge.load(chat.session_id)
    prior = json_store.load_analysis(chat.session_id)
    analysis, needs_audience = _analyse(
        chat, prior.request_text if prior else "",
        kb.audience or (prior.audience if prior else None),
        kb.audience_label or (prior.audience_label if prior else ""),
    )
    if analysis is None:
        return replies + [Reply(kind="notice", content={
            "text": "I re-read the files but could not build a model from them.",
            "reasons": ["the audience is still unknown"] if needs_audience else [],
        })]

    after = _session_snapshot(chat.session_id)
    body = [
        f"**{len(after['files'])} file(s)** read, including "
        f"{len(added)} new: {', '.join(added)}.",
        _delta("items", before.get("entities"), after.get("entities")),
        _delta("open conflict(s)", before.get("conflicts"), after.get("conflicts")),
        _delta("data quality", before.get("score"), after.get("score"),
               fmt="{:.1f}"),
    ]

    action = "Ask me to re-plan so the report reflects the new files."
    if kb.outputs:
        formats = ", ".join(dict.fromkeys(o.format for o in kb.outputs))
        action = (f"You've already generated {formats} — say “regenerate” and "
                  f"I'll rebuild {'it' if len(kb.outputs) == 1 else 'them'} "
                  f"from the merged data.")

    replies.append(Reply(kind="text", content={"text": chat_fmt.reply(
        "Re-read everything", body=[line for line in body if line], action=action,
    )}))
    replies.extend(_found(chat, analysis))
    return replies


def _delta(label: str, before, after, *, fmt: str = "{:g}") -> str:
    """`14 → 18 items (+4)`, or nothing at all when it did not move.

    Reporting an unchanged figure as though it were news is the kind of noise
    that trains a reader to skip the whole message.
    """
    if before is None or after is None or before == after:
        return ""
    arrow = f"{fmt.format(before)} → {fmt.format(after)}"
    change = after - before
    return f"• **{label}**: {arrow} ({'+' if change > 0 else ''}{fmt.format(change)})"


class ReviseRequest(BaseModel):
    instruction: str


@app.post("/api/content/{session_id}/revise")
def revise_content(session_id: str, req: ReviseRequest) -> dict:
    """"Add a slide about the TSA", "put risks first", "drop the dependencies".

    A successful revision becomes a new version; the previous one stays on disk.
    Nothing is dropped silently — anything refused comes back with the reason,
    so the user learns the figure they asked for is not one the report holds.
    """
    from app.report.revise import revise

    analysis = _analysis_or_404(session_id)
    content = report_store.load(session_id)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_content",
                    "message": "Plan the report before revising it."},
        )

    result, warnings = revise(content, req.instruction)

    if result.content is None:
        # Refusing is a real outcome, not an error: the instruction was not
        # understood, or every op it implied was rejected. 200 with the reasons
        # beats a 4xx the UI has to translate.
        return {
            "changed": False,
            "version": content.version,
            "applied": [],
            "rejected": [r.model_dump() for r in result.rejected],
            "warnings": warnings,
            "markdown": render_markdown(content),
        }

    stored = report_store.save(result.content)
    payload = _content_payload(stored, analysis)
    payload.update({
        "changed": True,
        "applied": result.applied,
        "rejected": [r.model_dump() for r in result.rejected],
        "warnings": warnings,
    })
    return payload


class FillIssueRequest(BaseModel):
    issue_id: str
    value: str


@app.get("/api/issues/{session_id}")
def list_issues(session_id: str) -> dict:
    """The §8.2-8.4 findings, individually — not just a count.

    Conflicts already had a UI; these did not, so the one category of finding a
    person can actually answer was the one they could not see.
    """
    from app.agent.corrections import fillable

    analysis = _analysis_or_404(session_id)
    issues = analysis.data_model.validation_issues
    answerable = {i.issue_id for i in fillable(issues)}

    return {
        "issues": [
            {
                **issue.model_dump(mode="json"),
                # Whether *this user* can do anything about it. A recomputed
                # arithmetic error is already fixed; a blank due date is not.
                "fillable": issue.issue_id in answerable,
            }
            for issue in issues
        ],
        "fillable_count": len(answerable),
    }


@app.post("/api/issues/{session_id}/fill")
def fill_issue(session_id: str, req: FillIssueRequest) -> dict:
    """Supply a value the files never contained.

    Re-runs the checks and re-scores afterwards, because a gap the user has just
    closed must stop being reported — a quality score that ignores the fix is
    worse than no score. Any drafted report is left stale by the fingerprint
    change and gets re-planned before it is rendered.
    """
    from app.agent.corrections import apply_and_persist

    analysis = _analysis_or_404(session_id)
    model = analysis.data_model

    issue = next(
        (i for i in model.validation_issues if i.issue_id == req.issue_id), None
    )
    if issue is None:
        raise HTTPException(status_code=404,
                            detail={"error": "no_such_issue"})

    result = apply_and_persist(analysis, issue, req.value)
    if not result.applied:
        # A rejected value is a normal outcome, not an error: the user typed
        # something the field cannot hold and needs to be told what to type.
        return {"applied": False, "message": result.message,
                "issue_id": req.issue_id}

    return {
        "applied": True,
        "message": result.message,
        "issue_id": req.issue_id,
        "remaining": len(model.validation_issues),
        "quality_score": analysis.quality_report.score,
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
