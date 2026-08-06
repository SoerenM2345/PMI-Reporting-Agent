"""The required format -> full preview -> revise -> approve -> generate loop."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    monkeypatch.setattr("app.config.settings.output_dir", tmp_path / "outputs")
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def _chat(client, sample_files, *names):
    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in names or ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            client.post(
                f"/api/upload?session_id={session_id}",
                files={"files": (name, handle, "application/octet-stream")},
            )
    return chat_id, session_id


def _reply(response):
    messages = [m for m in response.json()["messages"] if m["role"] == "agent"]
    assert len(messages) == 1
    return messages[0]["content"]


def _actions(content, kind):
    return [a for a in content.get("actions", []) if a["type"] == kind]


def test_missing_format_is_asked_first_and_generation_waits(client, sample_files):
    chat_id, session_id = _chat(client, sample_files)

    asked = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a status report for the Steering Committee"},
    ))
    assert _actions(asked, "choose_format")
    assert not asked.get("artifacts")

    previewed = _reply(client.post(
        f"/api/chats/{chat_id}/messages", json={"text": "PDF"},
    ))
    opened = _actions(previewed, "open_preview")
    assert opened and opened[0]["selected_format"] == "pdf"
    assert opened[0]["open_by_default"] is True
    assert not previewed.get("artifacts")

    preview = client.get(f"/api/content/{session_id}").json()
    assert preview["selected_format"] == "pdf"
    assert preview["format_preview"]["pages"]
    assert all(page["label"] == "Page"
               for page in preview["format_preview"]["pages"])
    assert preview["approval"]["approved"] is False

    generated = _reply(client.post(
        f"/api/chats/{chat_id}/messages", json={"text": "Generate now"},
    ))
    assert any(item["filename"].endswith(".pdf")
               for item in generated.get("artifacts", []))


def test_an_explicit_format_from_an_earlier_turn_is_remembered(client, sample_files):
    chat_id, _session_id = _chat(client, sample_files)
    client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "My output format should be PDF"},
    )
    report = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a status report for the Steering Committee"},
    ))
    opened = _actions(report, "open_preview")
    assert opened and opened[0]["selected_format"] == "pdf"
    assert not _actions(report, "choose_format")


def test_an_editorial_audience_label_does_not_stale_a_new_draft(
        client, sample_files):
    """The planner may turn an inferred reader into a polished display label.

    That label belongs on the document; it is not a new user request.  Using it
    to reconstruct the planning fingerprint made an HTML preview for "CHRO"
    report itself stale immediately and disabled the Generate button.
    """
    chat_id, session_id = _chat(client, sample_files)

    report = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a CHRO report in HTML"},
    ))
    assert _actions(report, "open_preview")

    preview = client.get(f"/api/content/{session_id}").json()
    assert preview["audience"]
    assert preview["stale"] is False

    approved = client.post(f"/api/content/{session_id}/approve", json={
        "version": preview["version"], "format": "html",
    })
    assert approved.status_code == 200


def test_a_standalone_format_from_an_earlier_turn_is_remembered(
        client, sample_files):
    chat_id, _session_id = _chat(client, sample_files)
    client.post(
        f"/api/chats/{chat_id}/messages", json={"text": "Word"},
    )
    report = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a status report for the Steering Committee"},
    ))
    opened = _actions(report, "open_preview")
    assert opened and opened[0]["selected_format"] == "word"
    assert not _actions(report, "choose_format")


def test_approval_is_bound_to_version_and_format(client, sample_files):
    chat_id, session_id = _chat(client, sample_files)
    _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a PowerPoint report for the Steering Committee"},
    ))
    preview = client.get(f"/api/content/{session_id}").json()
    approval = client.post(f"/api/content/{session_id}/approve", json={
        "version": preview["version"], "format": "powerpoint",
    }).json()

    revised = client.post(f"/api/content/{session_id}/revise", json={
        "instruction": "rename the Risks page to Risk outlook",
    }).json()
    if not revised.get("changed"):
        pytest.skip("this deterministic plan did not contain a Risks page")

    refused = client.post("/api/generate", json={
        "session_id": session_id,
        "format": "powerpoint",
        "version": preview["version"],
        "approval_id": approval["approval_id"],
        "force": True,
    })
    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "approval_required"


def test_layout_table_and_exact_text_references_reach_preview(
        client, sample_files):
    chat_id, session_id = _chat(
        client, sample_files,
        "integration_tracker.xlsx", "weekly_update.pptx",
        "steerco_meeting_notes.docx",
    )
    content = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": (
            "Create a PowerPoint report for the Steering Committee. "
            "Use the layout from weekly_update.pptx; "
            "use the table from integration_tracker.xlsx; "
            "use the exact text from steerco_meeting_notes.docx."
        )},
    ))
    assert _actions(content, "open_preview")

    preview = client.get(f"/api/content/{session_id}").json()
    references = preview["source_use_constraints"]
    assert {(item["kind"], item["source_file"]) for item in references} == {
        ("layout", "weekly_update.pptx"),
        ("table", "integration_tracker.xlsx"),
        ("exact_text", "steerco_meeting_notes.docx"),
    }
    pages = preview["format_preview"]["pages"]
    assert any("Referenced table" in page["title"] for page in pages)
    assert any("Exact text" in page["title"] for page in pages)
    assert all(item["checksum"] for item in references)

    approval = client.post(f"/api/content/{session_id}/approve", json={
        "version": preview["version"], "format": "powerpoint",
    }).json()
    generated = client.post("/api/generate", json={
        "session_id": session_id, "format": "powerpoint", "force": True,
        "version": preview["version"], "approval_id": approval["approval_id"],
    }).json()
    assert any(name.endswith(".pptx") for name in generated["outputs"])


def test_html_preview_describes_layout_before_generation(client, sample_files):
    chat_id, session_id = _chat(client, sample_files)
    content = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create an HTML report for the Steering Committee"},
    ))
    assert _actions(content, "open_preview")
    preview = client.get(f"/api/content/{session_id}").json()["format_preview"]
    assert preview["format"] == "html"
    assert preview["layout"]["header"]
    assert preview["layout"]["responsive"]
    assert preview["pages"]


def test_chart_preview_and_png_use_the_same_stored_spec(client, sample_files):
    chat_id, session_id = _chat(client, sample_files, "integration_tracker.xlsx")
    content = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a chart of workstream progress for the PMO"},
    ))
    assert _actions(content, "open_preview")
    preview = client.get(f"/api/content/{session_id}").json()
    charts = preview["format_preview"]["charts"]
    assert charts and charts[0]["series"]
    assert charts[0]["series"][0]["points"]

    approval = client.post(f"/api/content/{session_id}/approve", json={
        "version": preview["version"], "format": "chart",
    }).json()
    generated = client.post("/api/generate", json={
        "session_id": session_id, "format": "chart", "force": True,
        "version": preview["version"], "approval_id": approval["approval_id"],
    }).json()
    assert any(name.endswith(".png") for name in generated["outputs"])


def test_a_reference_can_be_added_during_revision_and_is_previewed_again(
        client, sample_files):
    chat_id, session_id = _chat(
        client, sample_files,
        "integration_tracker.xlsx", "steerco_meeting_notes.docx",
    )
    first = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Create a PowerPoint report for the PMO"},
    ))
    first_version = _actions(first, "open_preview")[0]["version"]

    revised = _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "Use the exact text from steerco_meeting_notes.docx"},
    ))
    opened = _actions(revised, "open_preview")
    assert opened and opened[0]["version"] > first_version
    preview = client.get(f"/api/content/{session_id}").json()
    assert any(item["kind"] == "exact_text"
               for item in preview["source_use_constraints"])
    assert preview["approval"]["approved"] is False


def test_changing_a_reused_source_invalidates_approval(client, sample_files):
    chat_id, session_id = _chat(
        client, sample_files,
        "integration_tracker.xlsx", "steerco_meeting_notes.docx",
    )
    _reply(client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": (
            "Create a Word report for the PMO using the exact text from "
            "steerco_meeting_notes.docx"
        )},
    ))
    preview = client.get(f"/api/content/{session_id}").json()
    approval = client.post(f"/api/content/{session_id}/approve", json={
        "version": preview["version"], "format": "word",
    }).json()

    client.post(
        f"/api/upload?session_id={session_id}",
        files={"files": (
            "steerco_meeting_notes.docx", b"replacement source bytes",
            "application/octet-stream",
        )},
    )
    stale = client.get(f"/api/content/{session_id}").json()
    assert stale["stale"] is True
    assert "source file" in stale["stale_reason"].lower()

    refused = client.post("/api/generate", json={
        "session_id": session_id, "format": "word", "force": True,
        "version": preview["version"], "approval_id": approval["approval_id"],
    })
    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "stale_content"
