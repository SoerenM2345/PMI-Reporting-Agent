"""Phase 3 — conversation orchestrator, /api/chat, non-blocking conflicts.

Covers: message routing (fact vs question vs report vs export); Markdown replies
rather than cards (Scenario 4); the non-blocking conflict-impact model — a draft can
be created with an open critical conflict, but a *final* export is held back
(Scenario 5); and continuous ingestion — a file uploaded after a draft bumps the
knowledge version and flags the draft (Scenario 1).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.project import conflict_impact, drafting, orchestrator
from app.project import files as files_mod
from app.project.json_repositories import Repositories
from app.project.rebuild import rebuild

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
PROJECT = "proj_p3"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    repos = Repositories()
    src = tmp_path / "milestone_tracker.csv"
    shutil.copy2(SAMPLES / "milestone_tracker.csv", src)
    files_mod.ingest_file(PROJECT, src, repos=repos)
    kb = rebuild(PROJECT, repos=repos, trigger="upload")
    return repos, kb, tmp_path


# --------------------------------------------------------------- routing
def test_empty_project_asks_for_files(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    resp = orchestrator.respond("nothing", "how are we doing?", repos=Repositories())
    assert resp.intent == "empty"
    assert "files" in resp.message.lower()


def test_question_returns_markdown_not_cards(project):
    repos, _, _ = project
    resp = orchestrator.respond(PROJECT, "What are the main management concerns?",
                                repos=repos)
    assert resp.intent == "question"
    # Prose/markdown, not a list of typed cards.
    assert isinstance(resp.message, str) and resp.message.strip()
    assert resp.actions == []


def test_fact_updates_knowledge_and_flags_drafts(project):
    repos, kb, _ = project
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)
    name = kb.data_model.milestones[0].name

    resp = orchestrator.respond(PROJECT, f"{name} is now 15-09-2026", repos=repos)

    assert resp.intent == "fact"
    assert resp.knowledge_version and resp.knowledge_version > kb.version
    # The existing draft is flagged (not rewritten) via an action + warning.
    assert any(a["type"] == "draft_stale" and a["draft_id"] == draft.draft_id
               for a in resp.actions)


def test_create_report_makes_a_draft(project):
    repos, _, _ = project
    resp = orchestrator.respond(PROJECT, "Create an executive SteerCo report",
                                repos=repos)
    assert resp.intent == "create_report"
    assert resp.draft and resp.draft["updated"] is True
    assert any(a["type"] == "open_draft" for a in resp.actions)


def test_revise_regenerates_named_section(project):
    repos, _, _ = project
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)
    resp = orchestrator.respond(
        PROJECT, "rewrite the milestones section", active_draft_id=draft.draft_id,
        repos=repos)
    assert resp.intent == "revise"
    assert resp.draft["updated"] is True


# ------------------------------------------ non-blocking conflicts (Scenario 5)
def test_draft_allowed_but_final_export_blocked_with_critical_conflict(
        project, monkeypatch):
    repos, kb, _ = project

    # Inject an unresolved critical conflict into the knowledge model directly —
    # this test is about the *impact gate*, not conflict detection (covered in
    # the consistency suite).
    from app.models.pmi import Conflict, Severity, SourceFormat
    from app.models.quality import ConflictEvidence
    from app.models.source import SourceReference
    from app.project import paths
    from app.project.locks import atomic_write_text

    def _ev(file_name, fmt, value):
        return ConflictEvidence(
            source_reference=SourceReference(file_name=file_name, file_type=fmt),
            value=value)

    knowledge = repos.knowledge.current(PROJECT)
    knowledge.data_model.conflicts.append(Conflict(
        check_id="X-1", entity_type="milestone", entity_key="Overall completion",
        field="progress_percentage", severity=Severity.CRITICAL,
        evidence=[_ev("tracker.xlsx", SourceFormat.EXCEL, "82"),
                  _ev("steerco.pptx", SourceFormat.POWERPOINT, "75")]))
    # Persist in place (a real conflict would arrive via detection; here we inject).
    atomic_write_text(paths.knowledge_current_path(PROJECT),
                      knowledge.model_dump_json())

    state = conflict_impact.assess(repos.knowledge.current(PROJECT))
    assert state.can_create_draft is True
    assert state.can_export_final is False
    assert state.blocking_conflicts

    # A draft is still allowed…
    made = orchestrator.respond(PROJECT, "create a report", repos=repos)
    assert made.draft is not None
    # …but a final export is held back, in plain language.
    export = orchestrator.respond(PROJECT, "export it as PowerPoint",
                                  active_draft_id=made.draft["draft_id"], repos=repos)
    assert export.conflict_state["can_export_final"] is False
    assert any(a["type"] == "export_blocked" for a in export.actions)
    assert "82" in export.message and "75" in export.message


# ----------------------------------------- continuous ingestion (Scenario 1)
def test_uploading_a_file_bumps_version_and_flags_draft_via_api(project, monkeypatch):
    repos, kb, tmp_path = project
    from app import main

    monkeypatch.setattr(main, "_project_or_404", lambda pid: {"project_id": pid})
    client = TestClient(main.app)

    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)

    extra = SAMPLES / "integration_tracker.xlsx"
    with extra.open("rb") as fh:
        resp = client.post(f"/api/projects/{PROJECT}/files",
                           files={"files": ("integration_tracker.xlsx", fh.read())})
    assert resp.status_code == 200
    body = resp.json()
    assert body["knowledge_version"] > kb.version
    # The pre-existing draft is reported stale, not silently overwritten.
    assert any(d["draft_id"] == draft.draft_id for d in body["stale_drafts"])


def test_chat_endpoint_roundtrip(project, monkeypatch):
    from app import main

    client = TestClient(main.app)
    resp = client.post("/api/chat", json={"project_id": PROJECT,
                                          "message": "what are the concerns?"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "question"
    assert resp.json()["message"]
