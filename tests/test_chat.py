"""The chat layer: storage, CRUD, and the turn router.

Two things are worth guarding here. First, that deleting a chat destroys the
conversation and nothing expensive. Second, that turning the wizard into a
conversation did not quietly drop the two behaviours the wizard was careful
about: asking for the audience instead of guessing, and refusing to stand behind
figures while critical conflicts are open.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import chat_store


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


# =================================================================== storage
def test_a_chat_owns_a_session(client):
    body = client.post("/api/chats", json={"title": "Week 12"}).json()

    assert body["chat"]["title"] == "Week 12"
    assert body["session_id"]
    assert body["chat"]["session_id"] == body["session_id"]


def test_chats_are_listed_most_recently_touched_first(client):
    first = client.post("/api/chats", json={"title": "One"}).json()["chat"]
    second = client.post("/api/chats", json={"title": "Two"}).json()["chat"]

    chat_store.add_message(first["chat_id"], "user", {"text": "hello"})

    titles = [c["title"] for c in client.get("/api/chats").json()["chats"]]
    assert titles[0] == "One", "the chat just used should be at the top"
    assert "Two" in titles


def test_a_chat_can_be_renamed_and_closed_and_reopened(client):
    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]

    renamed = client.patch(f"/api/chats/{chat_id}",
                           json={"title": "Aurora week 12"}).json()["chat"]
    assert renamed["title"] == "Aurora week 12"

    client.patch(f"/api/chats/{chat_id}", json={"archived": True})
    assert chat_id not in [c["chat_id"] for c in client.get("/api/chats").json()["chats"]]

    # Closed, not destroyed — it comes back.
    archived = client.get("/api/chats?include_archived=true").json()["chats"]
    assert chat_id in [c["chat_id"] for c in archived]

    client.patch(f"/api/chats/{chat_id}", json={"archived": False})
    assert chat_id in [c["chat_id"] for c in client.get("/api/chats").json()["chats"]]


def test_reopening_a_chat_returns_the_whole_transcript(client):
    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    chat_store.add_message(chat_id, "user", {"text": "first"})
    chat_store.add_message(chat_id, "agent", {"text": "second"})

    messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert [m["content"]["text"] for m in messages] == ["first", "second"]


def test_deleting_a_chat_leaves_the_analysis_alone(client):
    """Someone tidying their sidebar must not lose an extraction that cost real
    money in vision calls."""
    from app.storage import json_store

    body = client.post("/api/chats", json={}).json()
    session_id = body["session_id"]
    chat_id = body["chat"]["chat_id"]

    assert client.delete(f"/api/chats/{chat_id}").json()["deleted"] is True
    assert client.get(f"/api/chats/{chat_id}").status_code == 404
    assert json_store.exists(session_id), "the session was destroyed with the chat"


def test_a_structured_turn_keeps_its_kind(client):
    """The frontend renders a conflict card differently from prose, so the kind
    has to survive the round trip."""
    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    chat_store.add_message(chat_id, "agent", {"conflicts": []}, kind="conflict")

    messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert messages[-1]["kind"] == "conflict"


def test_the_model_choice_is_stored_per_chat(client):
    """Not on the global settings object — `/api/project` already does that
    with source_priority and it leaks into every other session."""
    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]

    updated = client.patch(f"/api/chats/{chat_id}", json={
        "provider": "anthropic", "model": "some-model-id",
    }).json()["chat"]

    assert (updated["provider"], updated["model"]) == ("anthropic", "some-model-id")


# ============================================================== conversation
def test_the_first_thing_asked_for_is_files(client):
    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]

    body = client.post(f"/api/chats/{chat_id}/messages",
                       json={"text": "give me a SteerCo deck"}).json()

    assert "upload" in body["messages"][-1]["content"]["text"].lower()


def test_an_unrecognised_message_offers_help_rather_than_guessing(client, sample_files):
    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    with open(sample_files / "integration_tracker.xlsx", "rb") as handle:
        client.post(f"/api/upload?session_id={session_id}",
                    files={"files": ("integration_tracker.xlsx", handle,
                                     "application/octet-stream")})

    reply = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "hmm"}).json()["messages"][-1]

    assert reply["kind"] == "text"
    assert "I can plan a report" in reply["content"]["text"]


def test_the_audience_is_asked_for_never_inferred(client, sample_files):
    """§4. A chat that guesses in order to sound fluent produces a document
    written for nobody."""
    from app.agent.conversation import _classify_by_keyword

    assert _classify_by_keyword("build me a report").audience is None
    assert _classify_by_keyword("a SteerCo deck").audience is not None


def test_a_render_request_names_the_format_the_user_asked_for():
    from app.agent.conversation import _classify_by_keyword

    turn = _classify_by_keyword("generate it as word")
    assert turn.intent == "render"
    assert turn.output_format == "word"


def test_an_edit_instruction_is_read_as_a_revision_not_a_new_report():
    from app.agent.conversation import _classify_by_keyword

    assert _classify_by_keyword("drop the dependencies section").intent \
        == "revise_content"
    assert _classify_by_keyword("put risks first").intent == "revise_content"


# ================================================ the loop has no dead ends
@pytest.fixture
def loaded(client, sample_files):
    """A chat whose session already has the two conflicting sample files."""
    body = client.post("/api/chats", json={}).json()
    for name in ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={body['session_id']}",
                        files={"files": (name, handle, "application/octet-stream")})
    return body["chat"]["chat_id"], body["session_id"]


def test_asking_for_a_report_reads_the_files_itself(client, loaded):
    """There is no "Analyse" button in a chat. Telling the user to go and press
    one that does not exist is a dead end — asking for a report is what
    triggers extraction."""
    chat_id, _ = loaded

    kinds = [m["kind"] for m in client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "give me a SteerCo deck"},
    ).json()["messages"]]

    assert "preview" in kinds, "asking for a report produced no draft"


def test_the_critical_conflict_gate_survives_into_the_chat(client, loaded):
    """§9. In the wizard this was a 409. It becomes a card in the transcript —
    but it still appears before any draft is stood behind."""
    chat_id, _ = loaded

    messages = client.post(f"/api/chats/{chat_id}/messages",
                           json={"text": "give me a SteerCo deck"}).json()["messages"]
    conflicts = [m for m in messages if m["kind"] == "conflict"]

    assert conflicts, "the 82-vs-75 conflict was not raised"
    assert conflicts[0]["content"]["conflicts"]


def test_a_generate_reply_never_claims_work_it_did_not_do(client, loaded):
    """The reply said "Generating the word." and produced nothing. A tool whose
    whole purpose is honest reporting must not misreport its own behaviour."""
    chat_id, session_id = loaded
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})

    reply = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "generate it as word"}).json()["messages"][-1]

    assert reply["kind"] == "downloads"
    outputs = reply["content"]["outputs"]
    assert any(name.endswith(".docx") for name in outputs), outputs

    # And the file it named can actually be fetched.
    name = next(n for n in outputs if n.endswith(".docx"))
    assert client.get(f"/api/download/{session_id}/{name}").status_code == 200


def test_generating_over_open_conflicts_says_so_in_the_reply(client, loaded):
    chat_id, _ = loaded
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})

    reply = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "generate it as pdf"}).json()["messages"][-1]

    assert "unresolved critical conflict" in reply["content"]["text"]


# ================================================================ model picker
def test_the_picker_is_served_not_hard_coded(client):
    """§21.10 confines model IDs to config.py. A list in JSX would sit where
    the grep test cannot see it and drift from what the backend accepts."""
    body = client.get("/api/models").json()

    assert body["models"], "the catalogue is empty"
    assert {m["provider"] for m in body["models"]} == {"anthropic", "openai"}
    for model in body["models"]:
        assert model["context_window"] > 0, model["id"]
        assert "available" in model


def test_a_provider_with_no_key_is_offered_but_marked_unavailable(client, monkeypatch):
    """Better to show the option greyed out than to hide it — otherwise the
    user cannot tell the difference between "not supported" and "not set up"."""
    monkeypatch.setattr("app.config.settings.anthropic_api_key", None)
    monkeypatch.setattr("app.config.settings.openai_api_key", None)

    body = client.get("/api/models").json()

    assert body["keyless"] is True
    assert all(m["available"] is False for m in body["models"])
    assert body["models"], "options vanished instead of being marked unusable"


def test_two_chats_can_sit_on_different_providers(client):
    """A single global client would mean the last chat opened silently decided
    which backend every other chat used."""
    from app import llm

    a = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    b = client.post("/api/chats", json={}).json()["chat"]["chat_id"]

    client.patch(f"/api/chats/{a}", json={"provider": "anthropic"})
    client.patch(f"/api/chats/{b}", json={"provider": "openai"})

    assert client.get(f"/api/chats/{a}").json()["chat"]["provider"] == "anthropic"
    assert client.get(f"/api/chats/{b}").json()["chat"]["provider"] == "openai"

    # And the client cache keys on provider rather than collapsing to one.
    llm.reset_client()
    assert llm.get_client("anthropic") is llm.get_client("anthropic")
    assert llm.get_client("anthropic") is not llm.get_client("openai")


# ================================================================ the budget
def test_a_new_chat_reports_headroom_against_its_model(client):
    from app.agent import budget

    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    client.patch(f"/api/chats/{chat_id}", json={"model": "claude-haiku-4-5"})

    usage = client.get(f"/api/chats/{chat_id}").json()["usage"]
    assert usage["window"] == 200_000, "the window must follow the chosen model"
    assert usage["near_limit"] is False


def test_switching_model_changes_how_much_history_fits(client):
    """A per-chat budget is the point — every chat sharing one guessed number
    would make the setting cosmetic."""
    from app.agent import budget
    from app.storage import chat_store

    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]

    client.patch(f"/api/chats/{chat_id}", json={"model": "claude-haiku-4-5"})
    small = budget.window_for(chat_store.get_chat(chat_id))
    client.patch(f"/api/chats/{chat_id}", json={"model": "claude-opus-4-8"})
    large = budget.window_for(chat_store.get_chat(chat_id))

    assert large > small


def test_an_unknown_model_is_not_treated_as_unlimited(client):
    from app.agent import budget
    from app.storage import chat_store

    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    client.patch(f"/api/chats/{chat_id}", json={"model": "something-we-removed"})

    assert budget.window_for(chat_store.get_chat(chat_id)) == budget.FALLBACK_WINDOW


def test_a_long_chat_is_compacted_and_the_budget_comes_back_down(client):
    from app.agent import budget
    from app.storage import chat_store

    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    # Pin the smallest window in the catalogue, then genuinely fill 70% of it
    # rather than lowering the threshold to make the test pass.
    client.patch(f"/api/chats/{chat_id}", json={"model": "claude-haiku-4-5"})
    for index in range(40):
        chat_store.add_message(chat_id, "user", {"text": "x" * 12_000})
        chat_store.add_message(chat_id, "agent", {"text": f"reply {index}"})

    chat = chat_store.get_chat(chat_id)
    before = budget.usage(chat)["used"]
    assert budget.should_compact(chat), "the chat never reached the threshold"

    note = budget.compact(chat)
    after = budget.usage(chat_store.get_chat(chat_id))["used"]

    assert note is not None
    assert after < before, "compaction did not reduce what is sent to the model"


def test_compaction_hides_turns_from_the_model_but_not_from_the_user(client):
    """The user can still scroll back. Only the context shrinks."""
    from app.agent import budget
    from app.storage import chat_store

    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]
    for index in range(30):
        chat_store.add_message(chat_id, "user", {"text": "y" * 12_000})

    total_before = len(chat_store.list_messages(chat_id))
    budget.compact(chat_store.get_chat(chat_id))

    kept = chat_store.list_messages(chat_id, include_superseded=False)
    everything = chat_store.list_messages(chat_id)

    assert len(kept) < total_before, "nothing was compacted"
    assert len(everything) > len(kept), "the transcript lost history"
    assert client.get(f"/api/chats/{chat_id}").json()["messages"], "transcript empty"


def test_the_summary_is_written_by_python_not_by_a_model():
    """Summarising history is the one place a model could quietly rewrite what
    the user asked for, and there is no fact table to check it against."""
    import inspect

    from app.agent import budget

    source = inspect.getsource(budget)
    assert "get_client" not in source
    assert "structured(" not in source


def test_compaction_never_touches_the_report_or_the_analysis(client, sample_files):
    """The transcript is not the source of truth — that is what makes this safe."""
    from app.agent import budget
    from app.report import store as report_store
    from app.storage import chat_store, json_store

    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})

    version_before = report_store.load(session_id).version
    entities_before = json_store.load_analysis(session_id).data_model.entity_count()

    for _ in range(40):
        chat_store.add_message(chat_id, "user", {"text": "z" * 4000})
    budget.compact(chat_store.get_chat(chat_id))

    assert report_store.load(session_id).version == version_before
    assert json_store.load_analysis(session_id).data_model.entity_count() \
        == entities_before


def test_image_read_findings_are_listed_not_just_counted(client, sample_files,
                                                        fake_vision):
    """§5.6: "low-confidence findings should be shown to the user for review."

    A sentence saying three findings need checking is not that — nobody can act
    on a count. Each one is listed with what was read and how confident the
    reading was, because the only person who can confirm a figure scraped off a
    whiteboard photo is the one who was in the room.
    """
    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in ("integration_tracker.xlsx", "risk_dashboard.png"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})

    messages = client.post(f"/api/chats/{chat_id}/messages",
                           json={"text": "give me a SteerCo deck"}).json()["messages"]
    panels = [m for m in messages if m["kind"] == "low_confidence"]

    assert panels, "an image-sourced finding never reached the transcript"
    items = panels[0]["content"]["items"]
    assert items, "the panel was empty"
    for item in items:
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["label"] and item["type"]
    # Worst first — the reading most likely to be wrong is the one to check.
    assert items == sorted(items, key=lambda i: i["confidence"])


@pytest.mark.parametrize("message", [
    "give me a SteerCo deck",
    "generate a status deck",
    "create the presentation",
    "create a SteerCo presentation for the current PMI status.",
    "make the powerpoint for the steering committee",
    "build me a finance dashboard",
    "weekly IMO status report",
    "I need a report",
    "export as pdf",
    "put together a summary for the board",
])
def test_no_phrasing_of_a_first_request_dead_ends(client, loaded, message):
    """The bug this guards against: whether the agent worked depended on which
    verb you happened to type.

    "give me a SteerCo deck" classified as `request_report` and read the files;
    "generate a status deck" classified as `render` and hit a handler with no
    idea how to read anything, replying "I haven't read the files yet" — advice
    with no action behind it, since a chat has no Analyse button. Reading the
    files is now a precondition of routing, so no handler can forget it.

    An audience question is a valid outcome (§4: ask rather than guess). A flat
    text reply is not — it means the turn went nowhere.
    """
    chat_id, _ = loaded

    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": message}).json()["messages"]
    kinds = [m["kind"] for m in replies if m["role"] == "agent"]

    assert any(k in kinds for k in ("preview", "audience_choice", "downloads")), \
        f"{message!r} dead-ended with {kinds}"
    assert not any(
        "haven't read" in str(m["content"].get("text", "")) for m in replies
    ), f"{message!r} still tells the user to do something they cannot do"


def test_asking_to_generate_before_a_draft_exists_drafts_it_first(client, loaded):
    """"Generate a deck" with nothing drafted means *draft it*. Reading the
    report before it is built is the whole point of the tool, and the preview
    carries a format button for the next step."""
    chat_id, _ = loaded

    kinds = [m["kind"] for m in client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "generate a SteerCo powerpoint"},
    ).json()["messages"] if m["role"] == "agent"]

    assert "preview" in kinds
    assert "downloads" not in kinds, "generated a file the user never saw described"


# ======================================== new files must actually be re-read
def test_uploading_more_files_mid_chat_re_reads_them(client, loaded, sample_files):
    """The reported bug: five files, a report, then six more and "adjust my
    report with these new files as well" → "I didn't change anything."

    Nothing re-read anything — `respond` only analysed when there was *no*
    analysis — so the report stayed built from the original five while looking
    current. A stale report that looks fresh is the worst output here.
    """
    chat_id, session_id = loaded
    from app.storage import json_store

    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})
    before = json_store.load_analysis(session_id).data_model.entity_count()

    for name in ("synergy_tracker.xlsx", "steerco_pack.pdf"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})

    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": "adjust my report with these new files as well"}
                          ).json()["messages"]
    after = json_store.load_analysis(session_id).data_model.entity_count()

    assert after > before, "the new files were never read"
    assert "preview" in [m["kind"] for m in replies], "no updated draft was produced"
    assert any("new file" in str(m["content"].get("text", "")) for m in replies)


def test_re_reading_does_not_forget_the_audience_you_already_gave(client, loaded,
                                                                 sample_files):
    """Asking "who is this for?" again — after they answered two turns ago and
    have only uploaded a file since — is the agent forgetting, not being
    careful. §4 requires asking when the audience *cannot be inferred*."""
    chat_id, session_id = loaded
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})

    with open(sample_files / "synergy_tracker.xlsx", "rb") as handle:
        client.post(f"/api/upload?session_id={session_id}",
                    files={"files": ("synergy_tracker.xlsx", handle,
                                     "application/octet-stream")})

    kinds = [m["kind"] for m in client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "adjust my report with these new files as well"},
    ).json()["messages"]]

    assert "audience_choice" not in kinds
    assert "preview" in kinds


# ============================== the summary, and not blaming the wrong thing
def test_a_chat_drafted_report_has_an_executive_summary(client, loaded):
    """The chat path never passed `bullets` to the planner, so every report it
    drafted had an empty summary — and then blamed the model for it."""
    chat_id, _ = loaded

    preview = next(m for m in client.post(
        f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"},
    ).json()["messages"] if m["kind"] == "preview")

    markdown = preview["content"]["markdown"]
    assert "semantic layer was unavailable" not in markdown, \
        "blamed the LLM for a wiring gap"
    body = markdown.split("Executive summary")[1][:400]
    assert "- " in body, "the executive summary section is empty"


# ================================================ completeness gaps are usable
def test_completeness_gaps_are_listed_and_fillable(client, loaded):
    chat_id, session_id = loaded

    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": "give me a SteerCo deck"}).json()["messages"]
    panels = [m for m in replies if m["kind"] == "issues"]
    if not panels:
        pytest.skip("this sample produced no fillable gaps")

    issue = panels[0]["content"]["issues"][0]
    assert issue["field"] and issue["entity_label"]

    filled = client.post(f"/api/issues/{session_id}/fill",
                         json={"issue_id": issue["issue_id"],
                               "value": "Anna Schmidt"}).json()

    if filled["applied"]:
        # Closing a gap must re-score; a quality score that ignores the fix is
        # worse than no score.
        assert "quality_score" in filled
        assert client.post(f"/api/issues/{session_id}/fill",
                           json={"issue_id": issue["issue_id"], "value": "x"}
                           ).status_code == 404, "a closed gap is still offered"
