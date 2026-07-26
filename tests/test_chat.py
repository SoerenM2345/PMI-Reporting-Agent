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


def _chat_with_samples(client, sample_files, *names: str) -> str:
    """A chat whose session already holds the §19 sample files. Returns its id."""
    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in (names or ("integration_tracker.xlsx", "weekly_update.pptx")):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})
    return chat_id


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


def test_renaming_a_chat_keeps_its_position_in_the_list(client):
    """A rename changes a chat's label, not its recency — it must not jump to the
    top of the sidebar, which is ordered by last activity."""
    ids = [client.post("/api/chats", json={}).json()["chat"]["chat_id"]
           for _ in range(3)]
    # Newest first: the last created sits at the top.
    before = [c["chat_id"] for c in client.get("/api/chats").json()["chats"]]

    # Rename the middle one (created second, so index 1 from the top).
    middle = before[1]
    client.patch(f"/api/chats/{middle}", json={"title": "Renamed in place"})

    after = [c["chat_id"] for c in client.get("/api/chats").json()["chats"]]
    assert after == before, "renaming reordered the sidebar"


def test_capabilities_are_explained_without_needing_files(client):
    """§9. "What can you do?" is a real question with a real answer, even before
    anything is uploaded."""
    chat_id = client.post("/api/chats", json={}).json()["chat"]["chat_id"]

    reply = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "what can you do?"}).json()["messages"][-1]
    assert reply["kind"] == "text"
    text = reply["content"]["text"].lower()
    assert "consolidate" in text and "generate" in text


def test_the_agent_can_list_the_conflicts_it_detected(client, sample_files):
    """§4. "2 conflicts detected" must be expandable into *which* — the findings
    live in the analysis, and the chat can recall and explain them."""
    chat_id = _chat_with_samples(client, sample_files)
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    reply = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "which conflicts do you see?"}).json()["messages"][-1]
    text = reply["content"]["text"].lower()
    # The 82-vs-75 conflict is named, not just counted.
    assert "conflict" in text
    assert "82" in text or "75" in text


def test_each_question_is_answered_from_its_own_source(client, sample_files):
    """"Gaps" is not a synonym for "data-quality issues".

    One handler used to answer every finding word with the validation-issue list,
    so a user asking what was *missing* got told what was *wrong* — and acted on
    the wrong finding. Each question now reads only the collection it names.
    """
    chat_id = _chat_with_samples(client, sample_files)
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    def ask(text: str) -> str:
        return client.post(f"/api/chats/{chat_id}/messages",
                           json={"text": text}).json()["messages"][-1]["content"]["text"]

    gaps = ask("what are the gaps?")
    assert "gap" in gaps.lower()
    # It reports absences, never the §8 check findings.
    assert "conflict" not in gaps.lower()

    conflicts = ask("where do the files disagree?")
    assert "conflict" in conflicts.lower()

    quality = ask("what data-quality issues did you find?")
    assert "data-quality issue" in quality.lower() or "no data-quality" in quality.lower()


def test_the_score_explains_itself(client, sample_files):
    """§5. A score nobody can account for is a number taken on faith.

    The components are the score's own arithmetic — `build_report` stores what
    `_score` computed — so the explanation cannot drift from the figure.
    """
    from app.storage import json_store

    chat_id = _chat_with_samples(client, sample_files)
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    reply = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": "why is the data-quality score what it is?"},
    ).json()["messages"][-1]
    text = reply["content"]["text"]

    chat_body = client.get(f"/api/chats/{chat_id}").json()["chat"]
    report = json_store.load_analysis(chat_body["session_id"]).quality_report

    assert f"{report.score:.0f}/100" in text
    for component in report.score_components:
        assert component.label in text

    # The components account for the score, not merely accompany it.
    total = sum(c.weight * c.ratio for c in report.score_components)
    expected = min(total, report.score_cap) if report.score_cap else total
    assert round(expected, 1) == report.score


def test_a_correction_in_chat_updates_the_model_and_offers_to_regenerate(
        client, sample_files):
    """§6/§7. A value typed in chat is written into the durable model, and the
    agent offers to rebuild rather than making the user start over."""
    from app.storage import json_store

    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    milestones = json_store.load_analysis(session_id).data_model.milestones
    target = next((m for m in milestones if m.name), None)
    if target is None:
        pytest.skip("no milestone to correct in this sample")

    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": f"{target.name} should be 02-06-2026"}
                          ).json()["messages"]
    joined = " ".join(m["content"].get("text", "") for m in replies).lower()
    assert "regenerate" in joined, "no offer to rebuild the report"

    from datetime import date
    updated = next(m for m in json_store.load_analysis(session_id).data_model.milestones
                   if m.milestone_id == target.milestone_id)
    assert date(2026, 6, 2) in (updated.planned_date, updated.forecast_date,
                                updated.actual_date), "the correction did not land"


def test_a_plain_present_tense_sentence_is_a_data_update(client, sample_files):
    """"Reporting date is 17-09-2026." used to be refused.

    The correction patterns matched "should be" / "is now" / "is actually" and
    nothing else, so the phrasing people actually type fell through to
    `revise_content`, hit `guard.check_text` — which correctly refuses *prose*
    stating a figure the report does not hold — and came back as "I didn't
    change anything." The user had supplied a value and been told nothing
    happened.

    Routing the sentence to `nl_updates` *before* revision fixes it without
    touching the guard: that guard is the §11 backstop for authored prose, and a
    revision still cannot write a number.
    """
    from datetime import date

    from app.storage import json_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": "Reporting date is 17-09-2026."}
                          ).json()["messages"]
    joined = " ".join(m["content"].get("text", "") for m in replies).lower()
    assert "didn't change anything" not in joined
    assert "17-09-2026" in joined

    # It reached `PMIProject`, not an entity — and everything derived from the
    # reporting date was recomputed rather than left pointing at the old one.
    assert json_store.load_project(session_id).reporting_date == date(2026, 9, 17)
    assert json_store.load_analysis(session_id).data_model.project.reporting_date \
        == date(2026, 9, 17)


def test_a_bare_follow_up_resolves_against_what_was_just_discussed(
        client, sample_files):
    """"The deadline is 12-08-2026." names no entity at all.

    Right after the agent asked about one, it plainly refers to that one. With
    no stored focus it resolved to nothing, and the turn dead-ended.
    """
    from app.agent import knowledge
    from app.storage import json_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    focus = knowledge.load(session_id).focus
    if focus is None:
        pytest.skip("this sample left no gaps to ask about")

    # A value of the kind the focused field holds — the field is chosen from the
    # value's shape, so a date typed into an owner field would (correctly) land
    # somewhere else and prove nothing about focus resolution.
    is_date_field = focus.field.endswith("_date") or focus.field == "deadline"
    supplied, expected = (("12-08-2026", "2026-08-12") if is_date_field
                          else ("Anna Schmidt", "Anna Schmidt"))

    reply = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": f"The {focus.field.replace('_', ' ')} is {supplied}."},
    ).json()["messages"]
    joined = " ".join(m["content"].get("text", "") for m in reply).lower()
    assert "couldn't tell" not in joined

    collection, id_attr, _label = _collection_for(focus.entity_type)
    model = json_store.load_analysis(session_id).data_model
    entity = next(e for e in getattr(model, collection)
                  if getattr(e, id_attr) == focus.entity_id)
    assert str(getattr(entity, focus.field)) == expected


def _collection_for(entity_type: str):
    from app.agent.nl_updates import LABELS

    return LABELS[entity_type]


def test_a_pasted_block_fills_many_due_dates_at_once(client, sample_files):
    """The "which 8 tasks have no due date?" case, answered in one paste.

    A user copies the agent's own "<title> — <owner> · due —" list, fills the
    dashes and pastes it back. That is not a single "X is Y" sentence, so the
    one-at-a-time parser never saw it and nothing was saved. `apply_bulk` routes
    each line through the same engine, so every date lands in the model with the
    same "supplied by the user" provenance.
    """
    from datetime import date

    from app.storage import json_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    model = json_store.load_analysis(session_id).data_model
    tasks = [t for t in model.tasks if t.title and t.owner][:3]
    if len(tasks) < 2:
        pytest.skip("this sample has too few owned tasks to paste")

    paste = "\n".join(f"{t.title} — {t.owner} · due — 12-08-2026" for t in tasks)
    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": paste}).json()["messages"]
    joined = " ".join(m["content"].get("text", "") for m in replies).lower()
    assert "saved" in joined and "regenerate" in joined

    updated = json_store.load_analysis(session_id).data_model
    for original in tasks:
        now = next(t for t in updated.tasks if t.task_id == original.task_id)
        assert now.due_date == date(2026, 8, 12), f"{original.title} did not land"


def test_editing_a_card_saves_the_users_text_and_survives_a_replan(
        client, sample_files):
    """§ editable prose. A card's narrative is the user's to rewrite, and the
    rewrite outlives the next re-plan — stored as an override in the KB, not only
    in the content version a re-plan would rebuild from the model."""
    from app.report import store as report_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    content = report_store.load(session_id)
    block = next((b for s in content.sections for b in s.blocks
                  if b.kind == "bullets" and b.items), None)
    if block is None:
        pytest.skip("this sample produced no bullet card to edit")

    mine = "Integration is on track for Day 1.\nNo blockers this week."
    body = client.post(f"/api/content/{session_id}/prose",
                       json={"block_id": block.block_id, "text": mine}).json()
    assert body["applied"] is True

    after = report_store.load(session_id)
    edited = next(b for s in after.sections for b in s.blocks
                  if b.block_id == block.block_id)
    assert [i.text for i in edited.items] == mine.splitlines()
    assert all(i.authored_by == "user" for i in edited.items)

    # A re-plan rebuilds every block from the model — the override must win.
    client.post(f"/api/content/{session_id}")
    replanned = next(b for s in report_store.load(session_id).sections
                     for b in s.blocks if b.block_id == block.block_id)
    assert [i.text for i in replanned.items] == mine.splitlines()


def test_editing_a_card_refuses_an_invented_figure(client, sample_files):
    """The split, enforced: prose is free, a *number* the report does not hold is
    not. Refusing it here keeps the deck and the workbook from disagreeing with a
    figure the user typed into one card's text — §11's whole point."""
    from app.report import store as report_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    content = report_store.load(session_id)
    block = next((b for s in content.sections for b in s.blocks
                  if b.kind == "bullets" and b.items), None)
    if block is None:
        pytest.skip("this sample produced no bullet card to edit")

    body = client.post(
        f"/api/content/{session_id}/prose",
        json={"block_id": block.block_id,
              "text": "We now have 4173 critical risks open."},
    ).json()
    assert body["applied"] is False
    assert "4173" in body["message"]
    # Nothing was stored — the card still reads as it did.
    unchanged = report_store.load(session_id)
    still = next(b for s in unchanged.sections for b in s.blocks
                 if b.block_id == block.block_id)
    assert [i.text for i in still.items] == [i.text for i in block.items]


def test_a_correction_leaves_a_drafted_report_stale(client, sample_files):
    """A value the user supplies must not survive into an unchanged draft.

    The KB's content revision is part of the report fingerprint, so anything the
    user tells us forces a re-plan before the report renders — the same
    discipline that already covers a resolved conflict. A report that looks
    current while stating a figure the user has since corrected is the worst
    output this system can produce.
    """
    from app.report import store as report_store
    from app.storage import json_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    analysis = json_store.load_analysis(session_id)
    drafted = report_store.load(session_id)
    assert not report_store.is_stale(drafted, analysis.data_model,
                                     analysis.quality_report)

    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "Reporting date is 17-09-2026."})

    fresh = json_store.load_analysis(session_id)
    assert report_store.is_stale(drafted, fresh.data_model, fresh.quality_report)


def test_a_skipped_gap_is_not_asked_about_again(client, sample_files):
    """A skip used to live only in `pending.json` and die with the exchange, so
    the same question came back the next time collection started."""
    from app.agent import knowledge

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    first = knowledge.load(session_id).focus
    if first is None:
        pytest.skip("this sample left no gaps to ask about")

    client.post(f"/api/chats/{chat_id}/messages", json={"text": "next"})
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "stop"})

    kb = knowledge.load(session_id)
    assert kb.declined_gaps, "the skip was not recorded durably"

    # Restarting collection moves past it rather than re-asking.
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "fill the gaps"})
    resumed = knowledge.load(session_id).focus
    assert resumed is None or resumed.entity_id != first.entity_id \
        or resumed.field != first.field


def test_a_requested_structure_drives_the_order_in_every_format(client, sample_files):
    """§17. A structure the user describes replaces the house deck — and because
    every format plans from the same content, it applies to all of them, not
    just the one they happened to ask for first."""
    from app.report import store as report_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]

    client.post(f"/api/chats/{chat_id}/messages", json={
        "text": "Create a status report for the steering committee with the "
                "following sections: 1. Risks 2. Budget 3. Milestones",
    })

    order = [s.section_id for s in report_store.load(session_id).narrative()]
    # The requested three, in order, between the always-present bookends.
    assert order[0] == "summary.executive"
    assert order[-1] == "quality.limitations"
    middle = [s for s in order if s not in ("summary.executive",
                                            "quality.limitations")]
    assert middle == ["risks.critical", "finance.budget_detail", "milestones"]


def test_uploading_files_mid_chat_is_a_turn_with_an_answer(client, sample_files):
    """An upload used to be a silent side effect.

    `POST /api/upload` wrote the bytes; the "3 files ready" line was invented
    client-side and vanished when the chat was reopened. Nothing server-side had
    re-read anything, so the report stayed built from the original files while
    looking current — and the user had no way to tell.
    """
    from app.storage import json_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "give me a SteerCo deck"})

    before = json_store.load_analysis(session_id)

    extra = "synergy_tracker.xlsx"
    if not (sample_files / extra).exists():
        pytest.skip(f"no {extra} in the sample set")

    with open(sample_files / extra, "rb") as handle:
        body = client.post(
            f"/api/chats/{chat_id}/files",
            files={"files": (extra, handle, "application/octet-stream")},
        ).json()

    # The upload is stored in the transcript, so it survives a reopen.
    transcript = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert any(m["kind"] == "files" and m["role"] == "user" for m in transcript)

    # …and it was answered, with what actually changed.
    joined = " ".join(m["content"].get("text", "") for m in body["messages"])
    assert extra in joined

    # Everything was re-read, not just the new file — a conflict only exists
    # between two sources considered together.
    after = json_store.load_analysis(session_id)
    assert extra in after.data_model.source_files
    assert set(before.data_model.source_files) <= set(after.data_model.source_files)


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


def test_a_picture_is_a_format_the_agent_recognises():
    """"Generate an image…" had no format entry and no renderer branch, so it
    fell through to a re-plan and handed back the data-quality report labelled
    as the file the user asked for."""
    from app.agent.conversation import _classify_by_keyword
    from app.agent.graph import _canonical_format

    turn = _classify_by_keyword(
        "Generate an image describing the current milestones and project plan"
    )
    assert turn.intent == "render"
    assert _canonical_format(turn.output_format) == "chart"


def test_dashboard_in_excel_reaches_excel_not_the_html_dashboard():
    """Both formats claim the word "dashboard"; the one the user named wins."""
    from app.agent.conversation import _classify_by_keyword

    assert _classify_by_keyword("generate a dashboard in excel").output_format \
        == "excel"


def test_an_obvious_audience_is_never_asked_about():
    """§4 says to ask when the audience *cannot be inferred*. A request that
    names its reader in plain words has already answered the question."""
    from app.agent.conversation import _match_audience
    from app.models.pmi import Audience

    assert _match_audience("a pack for the integration director") is Audience.EXECUTIVE
    assert _match_audience("for the steering committee") is Audience.EXECUTIVE
    assert _match_audience("the imo needs this") is Audience.PMO
    # "workstream" used to be filed under PMO, so every workstream request
    # produced an IMO document.
    assert _match_audience("for the hr workstream leads") is Audience.WORKSTREAM


def test_the_users_own_words_title_the_report(client, sample_files):
    """A deck headed "IMO / PMO" for someone who answered "Integration Director"
    tells them it was written for somebody else.

    `Audience` stays the internal planning key — there are four report shapes and
    no more — but the title page carries the label the user used.
    """
    from app.report import store as report_store

    chat_id = _chat_with_samples(client, sample_files)
    session_id = client.get(f"/api/chats/{chat_id}").json()["chat"]["session_id"]

    # The agent asks who it is for, openly rather than as a closed list…
    asked = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "build me a report"}).json()["messages"][-1]
    assert asked["kind"] == "audience_choice"
    assert asked["content"]["free_text"] is True

    # …and the answer is not one of the four chips.
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "Integration Director"})

    content = report_store.load(session_id)
    assert content is not None
    assert content.audience_label == "Integration Director"
    assert "Integration Director" in content.subtitle


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
def test_completeness_gaps_are_collected_one_at_a_time(client, loaded):
    """§5. Gaps are no longer a batch form card — after a draft exists the agent
    asks for each missing value in prose, one turn at a time."""
    chat_id, session_id = loaded

    replies = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": "give me a SteerCo deck"}).json()["messages"]
    assert any(m["kind"] == "preview" for m in replies), "no draft was produced"

    prompts = [m for m in replies
               if m["kind"] == "text" and "type 'next' to skip" in m["content"]["text"]]
    if not prompts:
        pytest.skip("this sample produced no fillable gaps")

    # 'next' skips the current field and moves on to the next question.
    skipped = client.post(f"/api/chats/{chat_id}/messages",
                          json={"text": "next"}).json()["messages"][-1]
    assert skipped["kind"] == "text"

    # A supplied value is saved straight into the durable model and re-scored.
    before = client.get(f"/api/quality/{session_id}").json().get("score")
    saved = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "Anna Schmidt"}).json()["messages"]
    assert saved, "the value produced no reply"
    after = client.get(f"/api/quality/{session_id}").json().get("score")
    # Filling a gap can only hold or improve the score, never lose it.
    if before is not None and after is not None:
        assert after >= before


def test_the_rest_endpoint_still_fills_a_gap(client, loaded):
    """The chat path and `/api/issues/{sid}/fill` share one engine; the REST
    route stays available for programmatic use."""
    chat_id, session_id = loaded
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})

    issues = client.get(f"/api/issues/{session_id}").json()["issues"]
    fillable = [i for i in issues if i["fillable"]]
    if not fillable:
        pytest.skip("this sample produced no fillable gaps")

    issue = fillable[0]
    filled = client.post(f"/api/issues/{session_id}/fill",
                         json={"issue_id": issue["issue_id"],
                               "value": "Anna Schmidt"}).json()
    if filled["applied"]:
        assert "quality_score" in filled
        assert client.post(f"/api/issues/{session_id}/fill",
                           json={"issue_id": issue["issue_id"], "value": "x"}
                           ).status_code == 404, "a closed gap is still offered"
