"""Phase 1B — sources vs audit, message classification, scoped/authoritative facts.

Covers the checkpoint contract: messages are classified before they can touch
knowledge (formatting/questions never do); a confirmed correction supersedes the
file value with the old value still traceable (Scenario 2); a proposed/uncertain
value is kept beside the current one and flagged; a scenario message leaves
canonical knowledge unchanged; and audit events never alter knowledge.

Keyless: classification uses its keyword model (no provider), and corrections flow
through the deterministic pipeline.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.project import facts
from app.project import files as files_mod
from app.project.classify import classify_by_keyword
from app.project.json_repositories import Repositories
from app.project.rebuild import rebuild

PROJECT = "proj_1b"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project rebuilt to v1 from one sample file, ready to receive messages."""
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    samples = Path(__file__).resolve().parents[1] / "data" / "samples"
    src = tmp_path / "milestone_tracker.csv"
    shutil.copy2(samples / "milestone_tracker.csv", src)
    repos = Repositories()
    files_mod.ingest_file(PROJECT, src, repos=repos)
    knowledge = rebuild(PROJECT, repos=repos, trigger="upload")
    assert knowledge.data_model.milestones, "sample must yield milestones"
    return repos, knowledge


# --------------------------------------------------------- classification (corr #2)
@pytest.mark.parametrize("text, expected", [
    ("Make the report shorter and more positive", "instruction"),
    ("Regenerate the executive summary", "instruction"),
    ("What is the overall completion rate?", "no_knowledge_change"),
    ("The ERP go-live is now 15-09-2026", "correction"),
    ("The Day 1 date is 02-06-2026", "new_fact"),
    ("We decided to go with SAP", "decision"),
    ("Assume the reporting date is month-end", "assumption"),
])
def test_message_classification_routes(text, expected):
    assert classify_by_keyword(text).contribution == expected


def test_hedged_value_is_uncertain_authority():
    assert classify_by_keyword("Maybe the budget is around 3 million").authority \
        == "uncertain"


def test_what_if_is_scenario():
    cls = classify_by_keyword("Suppose the go-live is 15-12-2026")
    assert cls.authority == "scenario_only"
    assert cls.scope == "scenario"


# ------------------------------------------------ instruction is audit-only (corr #1)
def test_instruction_does_not_change_knowledge(project):
    repos, knowledge = project
    before = repos.knowledge.current_version(PROJECT)

    result = facts.record_message(PROJECT, "Make the report shorter", repos=repos)

    assert result.knowledge_changed is False
    assert repos.knowledge.current_version(PROJECT) == before
    # Audited, but never logged as a knowledge source.
    assert len(repos.audit.list(PROJECT)) == 1
    assert repos.sources.list(PROJECT) == []


# ----------------------------------------- confirmed correction supersedes (Scenario 2)
def test_confirmed_correction_supersedes_and_stays_traceable(project):
    repos, knowledge = project
    milestone = knowledge.data_model.milestones[0]
    label = milestone.name
    old = milestone.planned_date

    result = facts.record_message(
        PROJECT, f"{label} is now 15-09-2026", repos=repos)

    assert result.applied is True
    assert result.knowledge_changed is True

    after = repos.knowledge.current(PROJECT)
    updated = next(m for m in after.data_model.milestones if m.name == label)
    assert updated.planned_date.isoformat() == "2026-09-15"

    # The correction is a durable decision (survives future rebuilds) and the old
    # value is preserved for traceability.
    decision = after.user_decisions[-1]
    assert decision.kind == "confirmed_value"
    assert decision.detail["old_value"] == (
        f"{old:%d-%m-%Y}" if old else "Not Reported")
    # Logged as a knowledge source of the right type.
    assert repos.sources.list(PROJECT)[-1].type == "user_correction"


def test_confirmed_correction_survives_a_later_rebuild(project, tmp_path):
    """A file re-read must not win back a value the user corrected.

    Forces a genuine re-derivation by adding a second file, so the model is rebuilt
    from scratch and the correction has to be re-applied — not merely served from
    the previous version.
    """
    repos, knowledge = project
    label = knowledge.data_model.milestones[0].name
    facts.record_message(PROJECT, f"{label} is now 15-09-2026", repos=repos)

    samples = Path(__file__).resolve().parents[1] / "data" / "samples"
    extra = tmp_path / "integration_tracker.xlsx"
    shutil.copy2(samples / "integration_tracker.xlsx", extra)
    files_mod.ingest_file(PROJECT, extra, repos=repos)
    rebuilt = rebuild(PROJECT, repos=repos, trigger="reread")

    assert rebuilt.version > knowledge.version + 1     # a real new version
    updated = next(m for m in rebuilt.data_model.milestones if m.name == label)
    assert updated.planned_date.isoformat() == "2026-09-15"


# ------------------------------------------ proposed/uncertain kept aside (corr #5)
def test_uncertain_value_is_flagged_not_applied(project):
    repos, knowledge = project
    label = knowledge.data_model.milestones[0].name
    original = knowledge.data_model.milestones[0].planned_date

    result = facts.record_message(
        PROJECT, f"Maybe {label} should be 20-10-2026", repos=repos)

    assert result.applied is False
    assert result.knowledge_changed is True  # recorded as an open question

    after = repos.knowledge.current(PROJECT)
    unchanged = next(m for m in after.data_model.milestones if m.name == label)
    assert unchanged.planned_date == original       # current value stands
    assert after.open_questions                     # but flagged for review
    assert after.open_questions[-1].authority == "uncertain"


# ------------------------------------------- scenario leaves canonical intact (corr #4)
def test_scenario_message_does_not_touch_canonical(project):
    repos, knowledge = project
    label = knowledge.data_model.milestones[0].name
    original = knowledge.data_model.milestones[0].planned_date

    result = facts.record_message(
        PROJECT, f"Suppose {label} is 15-12-2026", repos=repos)

    assert result.scope == "scenario"
    after = repos.knowledge.current(PROJECT)
    unchanged = next(m for m in after.data_model.milestones if m.name == label)
    assert unchanged.planned_date == original
    # Recorded as a scenario-scoped fact, never applied to entities.
    assert any(f.scope == "scenario" for f in after.confirmed_user_facts)


# ------------------------------------------ assumptions are their own store (corr #3)
def test_assumption_recorded_separately_from_facts(project):
    repos, _ = project
    result = facts.record_message(
        PROJECT, "Assume the reporting date is month-end", repos=repos)
    assert result.contribution == "assumption"
    after = repos.knowledge.current(PROJECT)
    assert after.assumptions
    # Not smuggled into the confirmed-facts store.
    assert not any(a.text in [f.text for f in after.confirmed_user_facts]
                   for a in after.assumptions)
