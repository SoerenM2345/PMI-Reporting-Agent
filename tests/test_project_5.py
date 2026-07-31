"""Phase 5 — the HTTP surface the workspace frontend reads.

The React workspace talks to the backend only through these routes, so they are
the contract worth pinning: the knowledge-state probe (status pill + "can I draft
yet"), the file upload (continuous ingestion), and the export → download round
trip. Component rendering has no test harness here (per frontend/CLAUDE.md); the
guard is that the API shapes the UI depends on stay stable.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
PROJECT = "proj_p5"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    from app import main

    monkeypatch.setattr(main, "_project_or_404", lambda pid: {"project_id": pid})
    return TestClient(main.app), tmp_path


def _upload(client, name):
    with (SAMPLES / name).open("rb") as fh:
        return client.post(f"/api/projects/{PROJECT}/files",
                           files={"files": (name, fh.read())})


def test_knowledge_probe_before_and_after_upload(client):
    api, _ = client
    before = api.get(f"/api/projects/{PROJECT}/knowledge").json()
    assert before["exists"] is False and before["version"] == 0

    _upload(api, "milestone_tracker.csv")
    after = api.get(f"/api/projects/{PROJECT}/knowledge").json()
    assert after["exists"] is True and after["version"] >= 1
    assert after["entity_count"] > 0
    assert "conflict_state" in after and after["conflict_state"]["can_create_draft"]


def test_upload_reports_version_and_stale_drafts(client):
    api, _ = client
    body = _upload(api, "milestone_tracker.csv").json()
    assert body["knowledge_version"] >= 1
    assert body["ingested"] and body["stale_drafts"] == []


def test_export_then_download_roundtrip(client):
    api, _ = client
    _upload(api, "milestone_tracker.csv")
    draft = api.post(f"/api/projects/{PROJECT}/drafts",
                     json={"audience": "executive"}).json()["draft"]

    exported = api.post(
        f"/api/projects/{PROJECT}/drafts/{draft['draft_id']}/export",
        json={"format": "markdown"})
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["file"].endswith(".md")

    got = api.get(payload["download_url"])
    assert got.status_code == 200 and got.content
    # The export is the draft's own Markdown — it starts with the title heading.
    assert got.content.decode("utf-8").startswith("# ")


def test_download_rejects_path_traversal(client):
    api, _ = client
    resp = api.get(f"/api/projects/{PROJECT}/exports/..%2f..%2fsecrets")
    assert resp.status_code in (400, 404)


def test_bad_export_format_is_400(client):
    api, _ = client
    _upload(api, "milestone_tracker.csv")
    draft = api.post(f"/api/projects/{PROJECT}/drafts",
                     json={"audience": "executive"}).json()["draft"]
    resp = api.post(f"/api/projects/{PROJECT}/drafts/{draft['draft_id']}/export",
                    json={"format": "keynote"})
    assert resp.status_code == 400
