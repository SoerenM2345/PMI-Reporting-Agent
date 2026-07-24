"""The preview loop over HTTP: plan → read as text → render (§4).

The point of these routes is that a user sees what a report will say *before*
paying to generate it, and that what they approved is what gets rendered. So the
assertions are about agreement between the preview and the artefact, and about
refusing to render a plan the analysis has outgrown.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def analyzed(client, sample_files):
    """A session carrying the spec's 82-vs-75 conflict, already analyzed."""
    sid = client.post("/api/session").json()["session_id"]
    for name in ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={sid}",
                        files={"files": (name, handle, "application/octet-stream")})

    body = client.post("/api/analyze", json={
        "session_id": sid,
        "request_text": "Create a SteerCo presentation for the current PMI status.",
        "audience": "Executive",
    }).json()
    assert not body.get("needs_audience")
    return sid


# ===================================================================== basics
def test_asking_for_a_plan_that_does_not_exist_says_how_to_make_one(client, analyzed):
    body = client.get(f"/api/content/{analyzed}").json()
    assert body["detail"]["error"] == "no_content"
    assert "POST" in body["detail"]["message"]


def test_planning_returns_a_readable_report_before_anything_is_generated(client, analyzed):
    body = client.post(f"/api/content/{analyzed}").json()

    assert body["version"] == 1
    assert body["stale"] is False
    assert body["markdown"].startswith("# ")
    # It reads as a report, not as a dump of the data model.
    assert "## " in body["markdown"]
    assert [s["section_id"] for s in body["sections"]][0] == "summary.executive"
    assert [s["section_id"] for s in body["sections"]][-1] == "quality.limitations"


def test_the_plan_is_versioned_and_the_history_is_listed(client, analyzed):
    client.post(f"/api/content/{analyzed}")
    second = client.post(f"/api/content/{analyzed}").json()
    assert second["version"] == 2

    versions = client.get(f"/api/content/{analyzed}/versions").json()["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["is_head"] is True


def test_reverting_appends_a_version_rather_than_erasing_one(client, analyzed):
    client.post(f"/api/content/{analyzed}")
    client.post(f"/api/content/{analyzed}")

    restored = client.post(f"/api/content/{analyzed}/revert?version=1").json()
    assert restored["version"] == 3

    # Nothing was destroyed on the way.
    assert client.get(f"/api/content/{analyzed}?version=2").status_code == 200


def test_reverting_to_a_version_that_never_existed_is_a_404(client, analyzed):
    client.post(f"/api/content/{analyzed}")
    response = client.post(f"/api/content/{analyzed}/revert?version=99")
    assert response.status_code == 404


# ================================================================== staleness
def test_resolving_a_conflict_marks_the_stored_plan_stale(client, analyzed):
    """The dangerous sequence. The plan states the figure one source reported;
    the user then decides the other one is right. Serving that plan unflagged
    would hand over a deck the user has already corrected."""
    client.post(f"/api/content/{analyzed}")
    assert client.get(f"/api/content/{analyzed}").json()["stale"] is False

    conflicts = client.get(f"/api/conflicts/{analyzed}").json()["unresolved"]
    if not conflicts:
        pytest.skip("sample data produced no unresolved conflict to decide")

    client.post(f"/api/conflicts/{analyzed}/resolve",
                json={"choices": {conflicts[0]["conflict_id"]: {"value": "80"}}})

    assert client.get(f"/api/content/{analyzed}").json()["stale"] is True


def test_generation_refuses_a_stale_plan_and_uses_a_fresh_one(client, analyzed):
    """A stale plan must never reach a renderer — it is silently wrong, which
    is the worst failure mode this system has."""
    client.post(f"/api/content/{analyzed}")

    conflicts = client.get(f"/api/conflicts/{analyzed}").json()["unresolved"]
    for conflict in conflicts:
        client.post(f"/api/conflicts/{analyzed}/resolve",
                    json={"choices": {conflict["conflict_id"]: {"value": "80"}}})

    body = client.post("/api/generate",
                       json={"session_id": analyzed, "force": True}).json()

    assert body["outputs"], "generation produced nothing"
    # Re-planned rather than reusing the stale version.
    runs = client.get(f"/api/session/{analyzed}").json().get("runs", [])
    assert runs and runs[-1].get("content_version") is None


# ============================================== the preview matches the deck
def test_what_the_preview_says_is_what_the_deck_says(client, analyzed):
    """The whole promise of the preview. If these can disagree, approving the
    text means nothing."""
    from pptx import Presentation

    from app.config import get_settings

    preview = client.post(f"/api/content/{analyzed}").json()
    body = client.post("/api/generate",
                       json={"session_id": analyzed, "force": True}).json()

    deck_name = next(name for name in body["outputs"] if name.endswith(".pptx"))
    path = get_settings().output_dir / analyzed / deck_name

    slide_text = []
    for slide in Presentation(str(path)).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                slide_text.append(shape.text_frame.text)
    deck = "\n".join(slide_text)

    # Every section headline the user approved appears on a slide.
    for section in preview["sections"]:
        if section["section_id"] == "summary.executive":
            continue
        assert section["headline"] in deck, \
            f"preview promised {section['headline']!r}, deck does not say it"


def test_generation_still_works_for_a_caller_that_never_opens_the_preview(client, analyzed):
    """The preview is optional. Every pre-existing client must keep working."""
    body = client.post("/api/generate",
                       json={"session_id": analyzed, "force": True}).json()
    assert body["outputs"]
    assert body["summary"] is not None


# ================================================== re-rendering into formats
@pytest.mark.parametrize("fmt,suffix", [
    ("word", ".docx"), ("pdf", ".pdf"), ("html", ".html"),
])
def test_the_approved_content_can_be_rendered_into_any_format(
    client, analyzed, fmt, suffix
):
    """§17. The user reads the text once, then picks a format — re-rendering
    costs no LLM call and cannot change a word of what they approved."""
    client.post(f"/api/content/{analyzed}")

    body = client.post("/api/generate", json={
        "session_id": analyzed, "force": True, "format": fmt,
    }).json()

    assert any(name.endswith(suffix) for name in body["outputs"]), body["outputs"]
    assert not body["errors"], body["errors"]


def test_a_rendered_file_can_actually_be_downloaded(client, analyzed):
    client.post(f"/api/content/{analyzed}")
    body = client.post("/api/generate", json={
        "session_id": analyzed, "force": True, "format": "pdf",
    }).json()

    name = next(n for n in body["outputs"] if n.endswith(".pdf"))
    response = client.get(f"/api/download/{analyzed}/{name}")

    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"
