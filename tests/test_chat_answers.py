"""The assistant answers in its own words (`app/generation/chat_writer.py`).

Every reply used to be a template rendered into a card, so the shape of the
answer was decided before the question was read. What is pinned here is the
opposite: the reply is Markdown the model wrote, the affordances sit beside it
rather than instead of it, and §11 still holds — a figure the sources do not
support does not get said in a chat bubble any more than on a slide.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.agent.replies import ChatAnswer
from app.context import builder
from app.context.schemas import KnowledgeDigest
from app.extractors.base import make_source
from app.generation import chat_writer
from app.main import app
from app.models.entities import PMIProject
from app.models.pmi import (
    BudgetItem,
    PMIDataModel,
    Risk,
    SourceFormat,
    Status,
    Task,
)

XLSX = SourceFormat.EXCEL


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def model() -> PMIDataModel:
    from app.agent.calculations import recompute_derived

    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan")
    built = PMIDataModel(
        project=PMIProject(project_id="p1", reporting_date=date(2026, 7, 27)),
        source_files=["tracker.xlsx"],
        tasks=[Task(task_id="T1", title="Payroll cutover", owner="Anna",
                    status=Status.IN_PROGRESS, progress_percentage=60.0,
                    source_references=[xlsx])],
        risks=[Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                    impact=5, status=Status.NOT_STARTED,
                    source_references=[xlsx])],
        budget=[BudgetItem(budget_item_id="B1", category="Advisors",
                           budget=1000.0, actual=900.0,
                           source_references=[xlsx])],
    )
    built, _ = recompute_derived(built, built.project.reporting_date)
    return built


def context_for(model, request_text="What are the main risks?"):
    return builder._assemble(
        scope="project", project_id="proj", chat_id=None, session_id=None,
        model=model, digest=KnowledgeDigest(), folder_name="Aurora",
        quality=None, request_text=request_text, requested_format=None,
        messages=[])


class _Says:
    """A client that answers `ChatReplyDraft` with whatever it was given."""

    name = "says"
    supports_vision = False

    def __init__(self, *replies: str):
        self._replies = list(replies)
        self.calls: list[str] = []

    def structured(self, *, output_model, system="", user="", **kwargs):
        self.calls.append(user)
        text = (self._replies.pop(0) if len(self._replies) > 1
                else self._replies[0])
        return output_model(content=text)


# ============================================================ prose, not cards
def test_the_answer_is_markdown_the_model_wrote(model):
    llm.set_client(_Says("## Where it stands\n\nThe ERP cutover is the "
                         "binding constraint."))
    answer = chat_writer.answer("How is it going?", context=context_for(model))

    assert answer.format == "markdown"
    assert answer.content.startswith("## Where it stands")
    assert answer.actions == [] and answer.artifacts == []


def test_the_question_and_the_evidence_both_reach_the_model(model):
    client = _Says("Fine.")
    llm.set_client(client)
    chat_writer.answer("What is the GDPR risk?", context=context_for(model))

    payload = client.calls[0]
    assert "<user_message>" in payload and "What is the GDPR risk?" in payload
    assert "GDPR retention breach" in payload, "the evidence was not sent"


def test_a_chat_turn_returns_prose_and_no_card_payload(client, sample_files):
    """The endpoint's contract: one message, whose substance is text."""
    body = client.post("/api/chats", json={}).json()
    chat_id, session_id = body["chat"]["chat_id"], body["session_id"]
    for name in ("integration_tracker.xlsx", "weekly_update.pptx"):
        with open(sample_files / name, "rb") as handle:
            client.post(f"/api/upload?session_id={session_id}",
                        files={"files": (name, handle, "application/octet-stream")})

    messages = client.post(f"/api/chats/{chat_id}/messages",
                           json={"text": "what are the main risks?"}
                           ).json()["messages"]
    agent = [m for m in messages if m["role"] == "agent"]

    assert len(agent) == 1, "one turn must be one message"
    content = agent[0]["content"]
    assert content["format"] == "markdown"
    assert content["content"].strip(), "the assistant said nothing"
    # None of the retired card keys survive.
    for gone in ("markdown", "sections", "outputs", "items", "conflicts",
                 "options", "reasons"):
        assert gone not in content, f"card key {gone!r} is still being emitted"


# ==================================================== §11 holds in the chat too
def test_a_figure_the_evidence_does_not_hold_is_not_said(model):
    """The same rule as a slide. A chat bubble is quoted in meetings too."""
    llm.set_client(_Says(
        "Integration is 91.4% complete and synergies of EUR 7,300,000 are on "
        "track.",
        "Integration progress is reported per workstream; no single overall "
        "figure is stated in the sources.",
    ))
    answer = chat_writer.answer("How complete is it?", context=context_for(model))

    assert "91.4" not in answer.content
    assert "7,300,000" not in answer.content
    assert "per workstream" in answer.content


def test_the_model_is_told_which_figure_was_wrong(model):
    client = _Says("It is 91.4% complete.", "It is progressing.")
    llm.set_client(client)
    chat_writer.answer("How complete is it?", context=context_for(model))

    assert len(client.calls) == 2, "the model was not given a second chance"
    assert "91.4" in client.calls[1] and "Correction" in client.calls[1]


def test_twice_refused_falls_back_and_says_that_it_did(model):
    """Serving a template while sounding conversational is the failure this
    whole module exists to end, so the substitution is disclosed."""
    llm.set_client(_Says("It is 91.4% complete."))
    answer = chat_writer.answer("How complete is it?", context=context_for(model))

    assert "91.4" not in answer.content
    assert "did not use it" in answer.content


def test_a_number_the_evidence_does_hold_is_allowed_through(model):
    llm.set_client(_Says("Payroll cutover is 60% done."))
    answer = chat_writer.answer("Where is payroll?", context=context_for(model))
    assert "60" in answer.content


# ================================================ missing means missing (§19.9)
def test_a_missing_value_is_described_not_invented(model):
    """No synergy is recorded anywhere in this project."""
    answer = chat_writer.deterministic("What is the synergy target?",
                                       context_for(model), None)

    assert answer.content
    assert "synergy" not in answer.content.lower() or "no " in answer.content.lower()
    # Nothing that looks like a fabricated figure.
    assert "%" not in answer.content or "0%" not in answer.content


def test_with_no_model_the_answer_is_still_about_this_project(model):
    llm.reset_client()
    answer = chat_writer.answer("What have you got?", context=context_for(model),
                                use_model=False)

    assert "risk" in answer.content.lower() or "task" in answer.content.lower()
    assert "I can answer from what the files hold" in answer.content


def test_with_nothing_read_it_says_so_rather_than_bluffing():
    empty = context_for(PMIDataModel(project=PMIProject(project_id="p1")))
    answer = chat_writer.deterministic("How is it going?", empty, None)
    assert "Nothing has been read" in answer.content


# ================================================== the scripted model scenario
@pytest.mark.parametrize("scripted_planning", ["steerco_status"], indirect=True)
def test_the_scripted_answer_survives_the_guard(model, scripted_planning):
    answer = chat_writer.answer("What needs my attention?",
                                context=context_for(model))
    assert answer.content.startswith("Three things need your attention")
    assert "cannot state a single completion figure" in answer.content


@pytest.mark.parametrize("scripted_planning", ["bad_plan"], indirect=True)
def test_the_adversarial_answer_is_refused(model, scripted_planning):
    """`bad_plan` states a completion percentage and a synergy total that no
    source supports — exactly what a plausible model does under pressure."""
    answer = chat_writer.answer("How complete is it?", context=context_for(model))

    assert "91.4" not in answer.content
    assert "7,300,000" not in answer.content


# ================================================================= composition
def test_two_things_said_in_one_turn_become_one_message():
    joined = ChatAnswer(content="I re-read the files.").then(
        ChatAnswer(content="Here's the draft."))
    assert joined.content == "I re-read the files.\n\nHere's the draft."


def test_a_failure_anywhere_in_a_turn_is_the_turns_status():
    joined = ChatAnswer(content="Read them.").then(
        ChatAnswer(content="But the render broke.", status="failed"))
    assert joined.status == "failed"
