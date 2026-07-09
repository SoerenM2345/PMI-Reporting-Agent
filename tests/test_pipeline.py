"""End-to-end and unit tests. Run: pytest -q  (from repo root)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
sys.path.insert(0, str(ROOT))

from app.agent.consistency import detect_conflicts, resolve_conflicts  # noqa: E402
from app.agent.graph import run_agent  # noqa: E402
from app.agent.standardize import standardize  # noqa: E402
from app.extractors import extract_file  # noqa: E402
from app.extractors.base import (find_progress_mentions, normalize_header,  # noqa: E402
                                 normalize_status, parse_percent)
from app.models.pmi import Audience, Status  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def sample_files():
    if not (SAMPLES / "integration_tracker.xlsx").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sample_data.py")],
                       check=True)
    return SAMPLES


# ------------------------------------------------------------------ units
def test_header_mapping():
    assert normalize_header("Responsible") == "owner"
    assert normalize_header("Due Date") == "due_date"
    assert normalize_header("% Complete") == "progress_pct"
    assert normalize_header(None) is None


def test_status_normalization():
    assert normalize_status("Done") == Status.DONE
    assert normalize_status("in progress") == Status.IN_PROGRESS
    assert normalize_status("BLOCKED") == Status.BLOCKED
    assert normalize_status("???") == Status.UNKNOWN


def test_percent_parsing():
    assert parse_percent("82%") == 82
    assert parse_percent(0.75) == 75
    assert parse_percent(45) == 45


def test_progress_mentions():
    assert find_progress_mentions("Overall progress: 82% this week") == [82.0]
    assert find_progress_mentions("Overall progress = 75 %") == [75.0]


# ------------------------------------------------------------------ extractors
def test_excel_extraction(sample_files):
    recs = extract_file(sample_files / "integration_tracker.xlsx")
    types = {r["type"] for r in recs}
    assert {"task", "risk", "budget"} <= types
    assert any(r.get("name") == "Overall Progress" and r.get("value") == 82.0
               for r in recs if r["type"] == "kpi")


def test_pptx_extraction(sample_files):
    recs = extract_file(sample_files / "weekly_update.pptx")
    assert any(r.get("name") == "Overall Progress" and r.get("value") == 75.0
               for r in recs if r["type"] == "kpi")
    assert any(r["type"] == "milestone" for r in recs)
    assert any(r["type"] == "task" and r.get("owner") == "Marco Rossi" for r in recs)


def test_docx_extraction(sample_files):
    recs = extract_file(sample_files / "steerco_meeting_notes.docx")
    assert any(r["type"] == "task" and "privacy" in r["title"].lower() for r in recs)
    assert any(r["type"] == "kpi" for r in recs)


# ------------------------------------------------------------------ conflicts
def test_conflict_detection_and_priority(sample_files):
    recs = []
    for f in ("integration_tracker.xlsx", "weekly_update.pptx"):
        recs += extract_file(sample_files / f)
    model = standardize(recs, ["integration_tracker.xlsx", "weekly_update.pptx"])
    conflicts = detect_conflicts(model)
    progress = [c for c in conflicts if "progress" in c.entity_key.lower()]
    assert progress, "The 82% vs 75% conflict must be detected"
    resolved = resolve_conflicts(progress, strategy="priority")
    # Excel outranks PowerPoint
    assert resolved[0].resolved_from == "integration_tracker.xlsx"
    assert resolved[0].resolved_value == "82"


def test_conflict_ask_mode(sample_files):
    recs = []
    for f in ("integration_tracker.xlsx", "weekly_update.pptx"):
        recs += extract_file(sample_files / f)
    model = standardize(recs, ["a.xlsx", "b.pptx"])
    conflicts = [c for c in detect_conflicts(model) if c.critical]
    resolved = resolve_conflicts(conflicts, strategy="ask")
    assert any(c.resolved_value is None for c in resolved), \
        "ask-mode must leave critical conflicts for the user"


# ------------------------------------------------------------------ end to end
def test_full_agent_powerpoint(sample_files, tmp_path):
    result = run_agent({
        "session_id": "pytest",
        "file_paths": [str(sample_files / f) for f in
                       ("integration_tracker.xlsx", "weekly_update.pptx",
                        "steerco_meeting_notes.docx")],
        "request_text": "Create a SteerCo PowerPoint with tasks per owner",
        "audience": None,
        "conflict_strategy": "priority",
    })
    # "SteerCo" implies Executive -> no audience question
    assert result.get("needs_audience") is False
    assert result["output_files"], "PPTX must be generated"
    out = Path(result["output_files"][0])
    assert out.exists() and out.suffix == ".pptx"
    model = result["data_model"]
    assert len(model.tasks) >= 7
    assert len(model.risks) >= 3
    assert model.conflicts, "cross-source conflicts expected in sample data"
    assert "Anna Schmidt" in model.tasks_by_owner()


def test_full_agent_excel(sample_files):
    result = run_agent({
        "session_id": "pytest",
        "file_paths": [str(sample_files / "integration_tracker.xlsx")],
        "request_text": "Create a Finance Excel dashboard",
        "audience": None,
        "conflict_strategy": "priority",
    })
    assert result["output_files"][0].endswith(".xlsx")
    assert result["audience"] == Audience.FINANCE


def test_audience_question_when_unclear(sample_files):
    result = run_agent({
        "session_id": "pytest",
        "file_paths": [str(sample_files / "integration_tracker.xlsx")],
        "request_text": "Create a chart about risks",
        "audience": None,
        "conflict_strategy": "priority",
    })
    assert result.get("needs_audience") is True  # step 2 must trigger


def test_api_roundtrip(sample_files):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    sid = client.post("/api/session").json()["session_id"]
    with open(sample_files / "integration_tracker.xlsx", "rb") as f:
        r = client.post(f"/api/upload?session_id={sid}",
                        files={"files": ("integration_tracker.xlsx", f,
                                         "application/octet-stream")})
    assert r.status_code == 200 and r.json()["saved"]
    r = client.post("/api/report", json={
        "session_id": sid,
        "request_text": "Create a PMO Excel dashboard",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["outputs"] and body["stats"]["tasks"] > 0
    dl = client.get(f"/api/download/{sid}/{body['outputs'][0]}")
    assert dl.status_code == 200
