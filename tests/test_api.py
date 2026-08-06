"""P5: the API, the analyze -> resolve -> generate round trip, and the traversal fix."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def session(client, sample_files):
    """A session with the masterplan and the SteerCo deck — i.e. the 82/75 conflict."""
    sid = client.post("/api/session").json()["session_id"]

    for name in ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            response = client.post(
                f"/api/upload?session_id={sid}",
                files={"files": (name, handle, "application/octet-stream")},
            )
        assert response.status_code == 200

    return sid


# ------------------------------------------------------------------- uploads
def test_unsupported_files_are_rejected_with_a_reason(client, tmp_path):
    sid = client.post("/api/session").json()["session_id"]
    bad = tmp_path / "notes.txt"
    bad.write_text("not a PMI file")

    with open(bad, "rb") as handle:
        body = client.post(
            f"/api/upload?session_id={sid}",
            files={"files": ("notes.txt", handle, "text/plain")},
        ).json()

    assert body["saved"] == []
    assert body["rejected"][0]["file"] == "notes.txt"
    assert "unsupported type" in body["rejected"][0]["reason"]


@pytest.mark.parametrize("filename", ["meeting.msg", "note.eml", "plan.mpp"])
def test_msg_eml_mpp_are_explicitly_rejected_not_silently_skipped(client, tmp_path, filename):
    """REQ-5: .msg/.eml/.mpp must return a clear 'unsupported format' message, never a
    silent failure. The rejection mechanism is generic (any extension outside
    SUPPORTED_EXTENSIONS), but these three specific extensions were never named in any
    test or doc before this — see the REQ-5 coverage audit."""
    sid = client.post("/api/session").json()["session_id"]
    bad = tmp_path / filename
    bad.write_bytes(b"not a real file, just proving the extension is rejected")

    with open(bad, "rb") as handle:
        body = client.post(
            f"/api/upload?session_id={sid}",
            files={"files": (filename, handle, "application/octet-stream")},
        ).json()

    assert body["saved"] == []
    assert body["rejected"][0]["file"] == filename
    assert "unsupported type" in body["rejected"][0]["reason"]


def test_analyze_requires_files(client):
    sid = client.post("/api/session").json()["session_id"]
    response = client.post("/api/analyze",
                           json={"session_id": sid, "request_text": "SteerCo deck"})
    assert response.status_code == 400


# -------------------------------------------------------------- §4: the ask
def test_an_ambiguous_request_asks_rather_than_guessing(client, session):
    """§4: 'If the audience cannot be inferred, the agent asks.' The audience reshapes
    the whole report — a guess is not a cheap mistake."""
    body = client.post("/api/analyze", json={
        "session_id": session,
        "request_text": "Create a chart about risks",
    }).json()

    assert body["needs_audience"] is True
    assert set(body["options"]) == {"Executive", "PMO", "Finance", "Workstream"}


def test_steerco_implies_executive(client, session):
    body = client.post("/api/analyze", json={
        "session_id": session,
        "request_text": "Create a SteerCo presentation for the current PMI status",
    }).json()

    assert body["needs_audience"] is False
    assert body["audience"] == "Executive"
    assert body["output_type"] == "powerpoint"


# ------------------------------------------- §9 Mode C: the round trip
def test_analyze_surfaces_the_critical_conflict_without_resolving_it(client, session):
    body = client.post("/api/analyze", json={
        "session_id": session,
        "request_text": "Create a SteerCo presentation",
    }).json()

    blocking = body["blocking_conflicts"]
    assert len(blocking) == 1

    conflict = next(c for c in body["conflicts"] if c["conflict_id"] == blocking[0])
    assert conflict["severity"] == "critical"
    assert conflict["values"] == {
        "integration_tracker.xlsx": "82",
        "weekly_update.pptx": "75",
    }
    assert conflict["resolved_value"] is None


def test_generate_refuses_while_a_critical_conflict_is_open(client, session):
    """The gate that makes Mode C mean something. A deck that silently picked one of
    two contradictory figures is the worst thing this system could produce."""
    client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    })

    response = client.post("/api/generate", json={"session_id": session})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "unresolved_critical_conflicts"
    assert len(detail["conflicts"]) == 1


def test_resolving_the_conflict_unblocks_generation(client, session):
    """§20 steps 9-11: the system asks, the user picks 82%, the deck is produced."""
    analysis = client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    }).json()
    conflict_id = analysis["blocking_conflicts"][0]

    resolved = client.post(
        f"/api/conflicts/{session}/resolve",
        json={"choices": {conflict_id: "integration_tracker.xlsx"}},
    ).json()

    assert resolved["blocking_conflicts"] == []
    winner = next(c for c in resolved["conflicts"] if c["conflict_id"] == conflict_id)
    assert winner["resolved_value"] == "82"

    generated = client.post("/api/generate", json={"session_id": session})
    assert generated.status_code == 200

    outputs = generated.json()["outputs"]
    assert any(o.endswith(".pptx") for o in outputs)
    # §18.18-19: both reports ship with every run, not only on request.
    assert any("conflict_report" in o for o in outputs)
    assert any("data_quality_report" in o for o in outputs)


def test_the_user_can_supply_a_figure_neither_source_holds(client, session):
    """§9 Mode A asks which *value* to use, not which file to prefer. When both are
    stale, choosing the least-wrong one is not a resolution."""
    analysis = client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    }).json()
    conflict_id = analysis["blocking_conflicts"][0]

    resolved = client.post(
        f"/api/conflicts/{session}/resolve",
        json={"choices": {conflict_id: {"value": "80"}}},
    ).json()

    winner = next(c for c in resolved["conflicts"] if c["conflict_id"] == conflict_id)
    assert winner["resolved_value"] == "80"
    assert winner["resolution"] == "user_value"


def test_force_generates_anyway_and_records_that_it_did(client, session):
    client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    })

    body = client.post(
        "/api/generate", json={"session_id": session, "force": True}
    ).json()

    assert body["outputs"]
    # The deck exists, but the run does not pretend the conflict went away.
    assert body["generated_with_unresolved_conflicts"]


def test_generation_does_not_re_extract(client, session, monkeypatch):
    """The whole reason analysis and generation are separate endpoints: re-extracting
    would re-pay for the §5.6 vision calls and could change the answer underneath the
    user between the question and their reply."""
    client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    })

    calls = []
    import app.agent.graph as graph

    monkeypatch.setattr(
        graph, "extract_file",
        lambda path: calls.append(path) or [],
    )

    client.post("/api/generate", json={"session_id": session, "force": True})
    assert calls == []


# ------------------------------------------------------------- data quality
def test_the_quality_endpoint_reports_what_the_run_could_not_do(client, session):
    client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    })
    body = client.get(f"/api/quality/{session}").json()

    assert 0 <= body["report"]["score"] <= 100
    assert body["summary"]
    assert "validation_issues" in body
    # Analysis routing is deterministic and performs no semantic writing, so it
    # must not claim that a model-authored summary fell back. Report planning
    # records its own fallback later, when a report is actually requested.
    warnings = client.get(
        f"/api/session/{session}").json().get("warnings", [])
    assert not any("parse_request" in w and "fallback" in w for w in warnings)


# ---------------------------------------------------------------- security
@pytest.mark.parametrize("attack", [
    "../../../../etc/passwd",
    "..%2F..%2Fetc%2Fpasswd",
    "....//....//etc/passwd",
])
def test_download_rejects_path_traversal(client, session, attack):
    """The original guard checked `".." in filename` *after* stat-ing the path — and a
    single URL segment never literally contains "..", so it never fired."""
    response = client.get(f"/api/download/{session}/{attack}")
    assert response.status_code == 404


def test_download_serves_a_real_output(client, session):
    client.post("/api/analyze", json={
        "session_id": session, "request_text": "Create a SteerCo presentation",
    })
    outputs = client.post(
        "/api/generate", json={"session_id": session, "force": True}
    ).json()["outputs"]

    response = client.get(f"/api/download/{session}/{outputs[0]}")
    assert response.status_code == 200
    assert response.content


# ------------------------------------------------------------------ project
def test_project_metadata_enables_the_checks_that_depend_on_it(client, session):
    """§4 step 1. Without a Day 1 date, TIME-004 cannot run — and the report says so
    rather than quietly skipping it."""
    client.post("/api/project", json={
        "session_id": session,
        "project_name": "Project Aurora",
        "reporting_date": "2026-07-01",
        "day_1_date": "2026-06-15",
    })

    body = client.get(f"/api/session/{session}").json()
    assert body["project"]["project_name"] == "Project Aurora"
    assert body["project"]["day_1_date"] == "2026-06-15"


def test_one_sessions_trust_override_does_not_leak_into_another(client, sample_files):
    """§9 lets a user say "this client's tracker is unreliable". That judgement
    belongs to one engagement.

    It used to be written into the settings singleton, so the next session in
    the same process resolved its conflicts by someone else's ranking — and kept
    doing so until restart. The override now lives on the project.
    """
    from app.config import get_settings
    from app.storage import json_store

    before = dict(get_settings().source_priority)

    first = client.post("/api/session").json()["session_id"]
    client.post("/api/project", json={
        "session_id": first,
        "project_name": "Distrusts its tracker",
        "source_priority": {"excel": 5, "image": 1},
    })

    # The process-wide default is untouched...
    assert get_settings().source_priority == before

    # ...the override is persisted against the project that asked for it...
    assert json_store.load_project(first).source_priority == {"excel": 5, "image": 1}

    # ...and a second session gets the defaults, not the first one's ranking.
    second = client.post("/api/session").json()["session_id"]
    client.post("/api/project", json={"session_id": second,
                                      "project_name": "Unrelated"})
    assert json_store.load_project(second).source_priority is None


def test_a_project_override_actually_changes_how_conflicts_resolve():
    """Otherwise the field is decoration."""
    from app.agent.consistency import resolve_conflicts
    from app.extractors.base import make_source
    from app.models.pmi import Conflict, ConflictEvidence, Severity, SourceFormat

    def evidence(name, fmt, value):
        return ConflictEvidence(
            source_reference=make_source(name, fmt), value=value
        )

    def conflict():
        return Conflict(
            check_id="PMI-002", entity_type="kpi", entity_key="Overall Progress",
            field="value", severity=Severity.LOW,
            evidence=[evidence("tracker.xlsx", SourceFormat.EXCEL, "82"),
                      evidence("dashboard.png", SourceFormat.IMAGE, "75")],
        )

    # Default ranking trusts the spreadsheet over the screenshot.
    assert resolve_conflicts([conflict()], strategy="priority")[0].resolved_value == "82"

    # A project that distrusts its own tracker flips that, without touching
    # anyone else's ranking.
    flipped = resolve_conflicts([conflict()], strategy="priority",
                                priority_override={"excel": 5, "image": 1})
    assert flipped[0].resolved_value == "75"
