"""A correction is authoritative, and stays authoritative.

The session stack could take a correction and lose it. `covers()` is false the
moment one new file appears, so an upload forced a full re-extraction and
`standardize` built a brand-new model straight from the files — reverting every
entity value the user had personally overruled, silently, while the report went
on looking current.

`tests/test_project_1b.py::test_confirmed_correction_survives_a_later_rebuild`
has guarded this on the *project* stack all along. These are its session twin,
plus the phrasings that used to defeat detection before anything was written at
all.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent import knowledge, nl_updates
from app.main import app
from app.storage import json_store


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def _chat_with(client, sample_files, *names):
    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in names:
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})
    return chat_id, session_id


def _upload(client, session_id, sample_files, name):
    with open(sample_files / name, "rb") as handle:
        client.post(f"/api/upload?session_id={session_id}",
                    files={"files": (name, handle, "application/octet-stream")})


# ================================================= C1: the phrasings people use
@pytest.mark.parametrize("sentence", [
    "Correction: the target is HealthSystems AG",
    "correction — the target is HealthSystems AG",
    "Actually, the target is HealthSystems AG",
    "To be clear, the target is HealthSystems AG",
    "No, the target is HealthSystems AG",
])
def test_a_correction_prefix_does_not_hide_the_correction(sentence):
    """The most natural way to signal an override was the one phrasing
    guaranteed to be ignored: the prefix became part of the left-hand side, so
    it matched no field, and the turn dead-ended at an apology."""
    update = nl_updates.parse(sentence)
    assert update is not None, f"{sentence!r} was not read as an update"
    assert nl_updates.match_project_field(update.target) == "target_name"
    assert update.value == "HealthSystems AG"


def test_a_long_company_name_is_still_a_value():
    """Four words was a person's name. Companies are longer, and at five tokens
    the sentence stopped being read as an update at all."""
    update = nl_updates.parse(
        "The target is Health Systems Deutschland Holding AG")
    assert update is not None
    assert update.value == "Health Systems Deutschland Holding AG"

    assert nl_updates.is_name("Müller, Weber & Partner")


def test_prose_is_still_not_mistaken_for_a_correction():
    """The prefix strip must not turn opinions into data edits.

    `parse` is shape-matching only, so "the summary is too long" does come back
    as a candidate update — "too long" is two word-like tokens. What stops it
    becoming an edit is `apply`: nothing in the model resembles "summary", so it
    returns `None` and the turn is answered rather than apologised at.
    """
    assert nl_updates.parse("Correction: this reads badly") is None

    from app.models.pmi import PMIDataModel
    from app.storage.json_store import SessionAnalysis

    analysis = SessionAnalysis(session_id="s1", request_text="",
                               data_model=PMIDataModel())
    assert nl_updates.apply(analysis, "Actually, the summary is too long") is None


# ============================================== C2: it survives a re-extraction
def test_a_corrected_value_survives_a_later_upload(client, sample_files):
    """The session twin of `test_project_1b.py:108`, and the whole point of
    this file. Correct a value, add a file, and the correction is still there —
    it used to revert to whatever the file said."""
    from datetime import date

    chat_id, session_id = _chat_with(client, sample_files,
                                     "integration_tracker.xlsx")
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})

    model = json_store.load_analysis(session_id).data_model
    target = next((t for t in model.tasks if t.title), None)
    if target is None:
        pytest.skip("no task to correct in this sample")

    applied = client.post(
        f"/api/chats/{chat_id}/messages",
        json={"text": f"the due date for {target.title} is 12-08-2026"}).json()
    assert applied["messages"], "the correction turn produced nothing"

    after = json_store.load_analysis(session_id)
    corrected = next(t for t in after.data_model.tasks
                     if t.title == target.title)
    assert corrected.due_date == date(2026, 8, 12), "the correction never landed"

    # …now add a file, which forces a full re-extraction.
    _upload(client, session_id, sample_files, "weekly_update.pptx")
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "what changed?"})

    reread = json_store.load_analysis(session_id)
    assert "weekly_update.pptx" in reread.data_model.source_files, "no re-read"
    survivor = next(t for t in reread.data_model.tasks
                    if t.title == target.title)
    assert survivor.due_date == date(2026, 8, 12), \
        "the re-read reverted a value the user personally corrected"


def test_the_run_says_that_it_put_the_corrections_back(client, sample_files):
    chat_id, session_id = _chat_with(client, sample_files,
                                     "integration_tracker.xlsx")
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})
    model = json_store.load_analysis(session_id).data_model
    target = next((t for t in model.tasks if t.title), None)
    if target is None:
        pytest.skip("no task to correct in this sample")
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": f"the due date for {target.title} is 12-08-2026"})

    _upload(client, session_id, sample_files, "weekly_update.pptx")
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "what changed?"})

    warnings = " ".join(json_store.load_analysis(session_id).warnings)
    assert "Re-applied" in warnings and "you supplied earlier" in warnings


def test_a_replay_matches_on_the_label_not_the_id():
    """Ids are reassigned by every standardize, so the replay cannot use them.

    This is the rule `app/project/rebuild.py::_apply_confirmed_values` follows
    and the reason `UserValue.label` is load-bearing.
    """
    from datetime import date

    from app.agent.analysis import replay_user_values
    from app.models.entities import PMIProject
    from app.models.pmi import PMIDataModel, Task

    kb = knowledge.KnowledgeBase(session_id="s1")
    kb.record_value(knowledge.UserValue(
        entity_type="task", entity_id="T1", label="Payroll cutover",
        field="due_date", value=date(2026, 8, 12), raw="12-08-2026"))

    # The same task, re-extracted under a completely different id.
    model = PMIDataModel(
        project=PMIProject(project_id="p1", reporting_date=date(2026, 7, 27)),
        tasks=[Task(task_id="T99", title="Payroll cutover")])

    assert replay_user_values(model, kb) == ["Payroll cutover.due_date"]
    assert model.tasks[0].due_date == date(2026, 8, 12)


def test_a_replay_that_cannot_land_is_skipped_not_fatal():
    """The entity is gone from the new file set. That is a real outcome, and it
    must not take the whole re-read down with it."""
    from datetime import date

    from app.agent.analysis import replay_user_values
    from app.models.pmi import PMIDataModel

    kb = knowledge.KnowledgeBase(session_id="s1")
    kb.record_value(knowledge.UserValue(
        entity_type="task", entity_id="T1", label="Vanished task",
        field="due_date", value=date(2026, 8, 12), raw="12-08-2026"))

    assert replay_user_values(PMIDataModel(), kb) == []


# ================================================== C3: supersede is recorded
def test_a_second_correction_supersedes_the_first():
    kb = knowledge.KnowledgeBase(session_id="s1")
    kb.record_value(knowledge.UserValue(
        entity_type="task", entity_id="T1", label="Payroll cutover",
        field="owner", value="Anna Schmidt", raw="Anna Schmidt"))
    kb.record_value(knowledge.UserValue(
        entity_type="task", entity_id="T7", label="Payroll cutover",
        field="owner", value="Jonas Weber", raw="Jonas Weber"))

    assert len(kb.user_values) == 1, "two live values for one field"
    assert kb.user_values[0].value == "Jonas Weber"
    assert kb.user_values[0].old_value == "Anna Schmidt"


def test_superseding_matches_on_the_label_even_when_the_id_moved():
    """Keyed on `entity_id`, a correction made after a re-read appended a second
    row instead of replacing the first — two live values, no way to tell which
    was current."""
    kb = knowledge.KnowledgeBase(session_id="s1")
    for entity_id, owner in (("T1", "Anna"), ("T99", "Jonas")):
        kb.record_value(knowledge.UserValue(
            entity_type="task", entity_id=entity_id, label="Payroll cutover",
            field="owner", value=owner, raw=owner))
    assert [v.value for v in kb.user_values] == ["Jonas"]


# ================================================== C4: the audience is a value
def test_the_audience_can_be_corrected_in_words(client, sample_files):
    """It is on no entity and in no `PROJECT_FIELDS` entry, so "the audience is
    the CFO" fell through to the entity matcher and failed there."""
    chat_id, session_id = _chat_with(client, sample_files,
                                     "integration_tracker.xlsx")
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})
    # Drafting starts gap collection, which would otherwise read the next
    # sentence as an answer to the question it just asked.
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "stop"})

    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "Correction: the audience is the CFO"})

    assert knowledge.load(session_id).audience_label == "the CFO"
    assert json_store.load_analysis(session_id).audience_label == "the CFO"


def test_an_audience_that_maps_to_no_shape_is_refused_not_guessed(client,
                                                                 sample_files):
    """§4: ask rather than guess. Silently picking the nearest of four shapes
    would undo the one decision this system insists on getting right."""
    chat_id, session_id = _chat_with(client, sample_files,
                                     "integration_tracker.xlsx")
    client.post(f"/api/chats/{chat_id}/messages",
                json={"text": "give me a SteerCo deck"})
    client.post(f"/api/chats/{chat_id}/messages", json={"text": "stop"})
    before = knowledge.load(session_id).audience

    reply = client.post(f"/api/chats/{chat_id}/messages",
                        json={"text": "the audience is Zaphod"}).json()
    said = " ".join(m["content"].get("content", "")
                    for m in reply["messages"] if m["role"] == "agent")

    assert "don't know which report shape" in said
    assert knowledge.load(session_id).audience == before


# ================================== C5: the user's value outranks the file's
def test_a_user_value_is_evidence_that_names_what_it_is_about():
    """As a bare sentence it had no entity, no field and no value, so nothing
    could tell it apart from — or compare it with — the figure it corrected."""
    from app.context.schemas import UserFact
    from app.evidence.projection import project
    from app.models.pmi import PMIDataModel

    index = project(PMIDataModel(), user_values=[
        UserFact(entity_type="task", label="Payroll cutover", field="due_date",
                 value="12-08-2026", old_value="01-05-2026")])

    item = next(i for i in index if i.kind == "user_value")
    assert item.entity_type == "task"
    assert item.payload["field"] == "due_date"
    assert item.display == "12-08-2026"
    assert "The files said 01-05-2026" in item.statement


def test_a_user_value_can_never_be_ranked_out_of_the_document():
    from app.context.schemas import UserFact
    from app.evidence.projection import project
    from app.models.pmi import PMIDataModel

    index = project(PMIDataModel(), user_values=[
        UserFact(entity_type="task", label="Payroll cutover", field="due_date",
                 value="12-08-2026")])

    item = next(i for i in index if i.kind == "user_value")
    assert item.evidence_id in index.must_include()


def test_a_user_value_outranks_an_equally_relevant_extracted_one():
    """`EvidenceOrigin` called `user_confirmed` authoritative and the only
    origin-aware line in scoring was the assumption penalty."""
    from app.evidence.model import EvidenceIndex, EvidenceItem
    from app.evidence.retrieval import retrieve

    index = EvidenceIndex()
    for origin, ident in (("normalized_value", "ev:task:T1"),
                          ("user_confirmed", "ev:user_value:t")):
        item = EvidenceItem(evidence_id=ident, kind="task", origin=origin,
                            label="Payroll cutover due date",
                            statement="Payroll cutover due date.")
        item.search_text = "payroll cutover due date"
        index.add(item)

    ranked = retrieve("payroll cutover due date", index, k=2)
    assert ranked.included[0].evidence_id == "ev:user_value:t"
