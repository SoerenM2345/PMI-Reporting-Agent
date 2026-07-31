"""One turn is one request, and it can be stopped.

Two things this pins.

**The turn is atomic.** The client used to post files, then the message. The
ordering was the bug: `/files` re-runs the whole analysis synchronously, so when
it threw the second call never fired and the user's typed sentence was silently
dropped — already cleared from the composer. One request also means one thing to
cancel; Stop could not have covered a turn that was two calls with a gap.

**Stopping leaves nothing half-finished.** Cancellation is checked at stage
boundaries, never forced. A killed render leaves a `.pptx` on disk that opens
and is wrong, which is worse than not stopping at all.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent.cancellation import Cancelled, NullToken, Token
from app.main import app


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def chat(client):
    body = client.post("/api/chats", json={}).json()
    return body["chat"]["chat_id"], body["session_id"]


def prose(message) -> str:
    return (message.get("content") or {}).get("content", "")


# ============================================================ the token itself
def test_a_token_reports_and_latches():
    token = Token()
    assert token.is_set() is False
    token.check("planning")                    # does not raise

    token.cancel()
    assert token.is_set() is True
    with pytest.raises(Cancelled) as stop:
        token.check("planning")
    assert stop.value.stage == "planning"


def test_a_token_can_watch_an_external_signal():
    disconnected = {"yes": False}
    token = Token(source=lambda: disconnected["yes"])

    assert token.is_set() is False
    disconnected["yes"] = True
    assert token.is_set() is True
    # Latched: the source is not consulted again once it has fired.
    disconnected["yes"] = False
    assert token.is_set() is True


def test_the_null_token_is_never_set():
    assert NullToken().is_set() is False
    NullToken().check("anything")


# =================================================== a stopped turn is an answer
def test_a_cancelled_turn_comes_back_stopped_not_failed(client, chat,
                                                        sample_files):
    """The user asked for this. Reporting it as an error would tell them
    something went wrong when nothing did."""
    from app.agent import conversation

    chat_id, session_id = chat
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        client.post(f"/api/upload?session_id={session_id}",
                    files={"files": ("integration_tracker.xlsx", handle,
                                     "application/octet-stream")})

    token = Token()
    token.cancel()
    answer = conversation.respond(
        __import__("app.storage.chat_store", fromlist=["x"]).get_chat(chat_id),
        "give me a SteerCo deck", cancel=token)

    assert answer.status == "stopped"
    assert answer.content == "Generation stopped."
    assert answer.artifacts == [], "a stopped turn must offer no file"


def test_a_stopped_build_never_becomes_a_version(client, chat, sample_files):
    """`engine.build` writes nothing, so a stopped plan leaves no draft behind —
    which is the point of stopping between stages rather than inside one."""
    from app.deliverable import session as session_plan
    from app.storage import chat_store, json_store

    from app.agent import conversation

    chat_id, session_id = chat
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        client.post(f"/api/upload?session_id={session_id}",
                    files={"files": ("integration_tracker.xlsx", handle,
                                     "application/octet-stream")})
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})
    before = session_plan.load(session_id)
    assert before is not None, "nothing was drafted to compare against"

    # Now stop a re-plan part-way.
    token = Token()
    token.cancel()
    answer = conversation.respond(chat_store.get_chat(chat_id),
                                  "give me a board update", cancel=token)

    assert answer.status == "stopped"
    after = session_plan.load(session_id)
    assert after.version == before.version, \
        "a stopped plan was saved as a new version"


# ================================================= one request carries the turn
def test_a_turn_carries_text_and_files_together(client, chat, sample_files):
    chat_id, session_id = chat
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        body = client.post(
            f"/api/chats/{chat_id}/turn",
            data={"text": "what are the risks?"},
            files={"files": ("integration_tracker.xlsx", handle,
                             "application/octet-stream")},
        ).json()

    assert body["saved"] == ["integration_tracker.xlsx"]

    roles = [m["role"] for m in body["messages"]]
    assert roles.count("user") == 2, "the upload and the message are both turns"
    assert "agent" in roles, "the turn was not answered"

    # The user's own sentence is in the transcript, in order, before the answer.
    texts = [m["content"].get("text", "") for m in body["messages"]
             if m["role"] == "user"]
    assert "what are the risks?" in texts


def test_a_turn_can_be_files_only(client, chat, sample_files):
    chat_id, session_id = chat
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        body = client.post(
            f"/api/chats/{chat_id}/turn",
            files={"files": ("integration_tracker.xlsx", handle,
                             "application/octet-stream")},
        ).json()

    assert body["saved"] == ["integration_tracker.xlsx"]
    assert any(m["role"] == "agent" for m in body["messages"])


def test_a_turn_can_be_text_only(client, chat, sample_files):
    chat_id, session_id = chat
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        client.post(f"/api/upload?session_id={session_id}",
                    files={"files": ("integration_tracker.xlsx", handle,
                                     "application/octet-stream")})

    body = client.post(f"/api/chats/{chat_id}/turn",
                       data={"text": "what are the risks?"}).json()

    assert body["saved"] == []
    assert any(prose(m) for m in body["messages"] if m["role"] == "agent")


def test_an_empty_turn_is_refused(client, chat):
    chat_id, _ = chat
    response = client.post(f"/api/chats/{chat_id}/turn", data={"text": "  "})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "empty_turn"


def test_an_internal_turn_failure_is_a_visible_answer_not_http_500(
        client, chat, monkeypatch):
    from app.agent import conversation

    monkeypatch.setattr(
        conversation, "respond",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("planning schema rejected")),
    )
    chat_id, _ = chat

    response = client.post(
        f"/api/chats/{chat_id}/turn", data={"text": "create a deck"})

    assert response.status_code == 200
    reply = next(m for m in response.json()["messages"]
                 if m["role"] == "agent")
    assert reply["content"]["status"] == "failed"
    assert "planning schema rejected" in prose(reply)


# ============================================ what the user sent, on the message
def test_the_uploaded_files_are_named_on_the_users_own_message(client, chat,
                                                               sample_files):
    """The filenames were stored all along and thrown away on the way to the
    screen, which is why an upload rendered as an empty black pill."""
    chat_id, session_id = chat
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        client.post(
            f"/api/chats/{chat_id}/turn",
            files={"files": ("integration_tracker.xlsx", handle,
                             "application/octet-stream")})

    transcript = client.get(f"/api/chats/{chat_id}").json()["messages"]
    upload = next(m for m in transcript
                  if m["role"] == "user" and m["content"].get("files"))
    attached = upload["content"]["files"][0]

    assert attached["filename"] == "integration_tracker.xlsx"
    assert attached["extension"] == "xlsx"
    assert attached["status"] == "ready"
    assert attached["size"] > 0
    assert attached["download_url"].endswith("/integration_tracker.xlsx")


def test_a_rejected_file_is_shown_as_failed_with_its_reason(client, chat,
                                                            tmp_path):
    chat_id, _ = chat
    bad = tmp_path / "notes.exe"
    bad.write_bytes(b"nope")
    with open(bad, "rb") as handle:
        client.post(f"/api/chats/{chat_id}/turn",
                    data={"text": "read this"},
                    files={"files": ("notes.exe", handle,
                                     "application/octet-stream")})

    transcript = client.get(f"/api/chats/{chat_id}").json()["messages"]
    upload = next(m for m in transcript
                  if m["role"] == "user" and m["content"].get("files"))
    attached = upload["content"]["files"][0]

    assert attached["filename"] == "notes.exe"
    assert attached["status"] == "failed"
    assert "unsupported" in attached["error"]
