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
from app.report import store as report_store
from app.report.planner import plan as plan_report
from app.report.render.markdown import render_markdown
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
        "warnings": content.warnings,
    }


@app.post("/api/content/{session_id}")
def plan_content_route(session_id: str) -> dict:
    """Plan (or re-plan) the report and store it as a new version."""
    analysis = _analysis_or_404(session_id)
    model, quality = analysis.data_model, analysis.quality_report

    bullets: list[str] = []
    existing = report_store.load(session_id)
    if existing is not None:
        # Keep the prose we already paid for; only the structure is re-derived.
        section = existing.section("summary.executive")
        if section and section.blocks:
            bullets = [item.text for item in section.blocks[0].items]

    content = plan_report(
        model, analysis.audience or Audience.PMO,
        session_id=session_id,
        topic=analysis.topic,
        bullets=bullets,
        quality=quality,
        fingerprint=report_store.fingerprint(model, quality),
    )
    stored = report_store.save(content)
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
                                  provider=req.provider, model=req.model)
    return {"chat": chat.model_dump(), "session_id": session_id}


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
    from app.agent.conversation import respond

    chat = _chat_or_404(chat_id)
    user_message = chat_store.add_message(chat_id, "user", {"text": req.text})
    replies = respond(chat, req.text)

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
    from app.agent.consistency import run_checks
    from app.agent.corrections import apply_correction
    from app.agent.data_quality import build_report

    analysis = _analysis_or_404(session_id)
    model = analysis.data_model

    issue = next(
        (i for i in model.validation_issues if i.issue_id == req.issue_id), None
    )
    if issue is None:
        raise HTTPException(status_code=404,
                            detail={"error": "no_such_issue"})

    result = apply_correction(model, issue, req.value)
    if not result.applied:
        # A rejected value is a normal outcome, not an error: the user typed
        # something the field cannot hold and needs to be told what to type.
        return {"applied": False, "message": result.message,
                "issue_id": req.issue_id}

    results = run_checks(model)
    model.conflicts = results.conflicts
    model.validation_issues = results.issues
    analysis.quality_report = build_report(
        model,
        failed_files=_failed(analysis.errors),
        warnings=analysis.warnings,
    )
    json_store.save_analysis(analysis)

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
