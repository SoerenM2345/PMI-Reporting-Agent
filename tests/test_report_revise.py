"""Revision: the numeric guard, the op vocabulary, and the keyless fallback.

The guard tests are the important ones. Everything else here is editing
mechanics; those decide whether a model can put a number into a board pack that
the data does not support.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.extractors.base import make_source
from app.models.pmi import (
    Audience,
    BudgetItem,
    PMIDataModel,
    PMIProject,
    Risk,
    SourceFormat,
    Status,
)
from app.report import guard, ops, revise_fallback
from app.report.ops import ContentRevision, ReviseOp
from app.report.planner import plan


@pytest.fixture
def content():
    xlsx = make_source("tracker.xlsx", SourceFormat.EXCEL, sheet_name="Workplan")
    model = PMIDataModel(
        project=PMIProject(project_id="p1", project_name="Aurora",
                           reporting_date=date.today()),
        risks=[Risk(risk_id="R1", title="GDPR breach", probability=4, impact=5,
                    status=Status.IN_PROGRESS, source_references=[xlsx])],
        budget=[BudgetItem(budget_item_id="B1", category="Advisors",
                           budget=1000.0, actual=900.0, forecast=1250.0,
                           source_references=[xlsx])],
    )
    return plan(model, Audience.EXECUTIVE, session_id="s1")


def _revise(content, *operations, instruction="test"):
    return ops.apply(content, ContentRevision(ops=list(operations)),
                     instruction=instruction)


# ====================================================== §11: the numeric guard
def test_a_figure_the_report_does_not_hold_is_rejected(content):
    """The whole point. The report says one open critical risk; a rewrite
    claiming four must not reach a Steering Committee."""
    result = _revise(content, ReviseOp(
        op="rewrite_headline", section_id="risks.critical",
        text="4 critical risks require attention",
    ))

    assert result.content is None
    assert not result.applied
    assert "4" in result.rejected[0].reason


def test_a_rewrite_that_reuses_the_reports_own_figures_is_accepted(content):
    result = _revise(content, ReviseOp(
        op="rewrite_headline", section_id="risks.critical",
        text="1 critical risk is open and needs an owner",
    ))

    assert result.changed
    assert result.content.section("risks.critical").headline.startswith("1 critical")


def test_prose_with_no_figures_at_all_is_always_safe(content):
    result = _revise(content, ReviseOp(
        op="rewrite_headline", section_id="risks.critical",
        text="Critical risks need an owner before Day 1",
    ))
    assert result.changed


def test_the_guard_compares_numbers_not_their_formatting(content):
    """The budget is stored as 1000 and displayed as "1,000"; both spellings
    refer to the same figure and must both be allowed."""
    corpus = content.numeric_corpus_cached()
    assert guard.check_text("Budget is 1,000", corpus) == []
    assert guard.check_text("Budget is 1000", corpus) == []
    assert guard.check_text("Budget is 1001", corpus) == ["1001"]


def test_ordinals_are_not_mistaken_for_figures():
    """"the 1st workstream" states no quantity."""
    assert guard.check_text("Fix the 1st and 2nd items", corpus=set()) == []


def test_the_guard_covers_table_cells_and_planner_prose(content):
    """A rephrase reusing a number already printed in a table is legitimate —
    rejecting it would make the feature useless."""
    corpus = content.numeric_corpus_cached()
    variance = content.facts.get("budget.variance")

    assert variance.value == -250.0
    assert guard.check_text("Forecast overruns budget by 250", corpus) == []


def test_a_rejection_tells_the_user_what_to_do(content):
    result = _revise(content, ReviseOp(
        op="add_bullet", section_id="next_steps",
        text="Savings of 9999 are expected",
    ))
    reason = result.rejected[0].reason

    assert "9999" in reason
    assert "not a figure this report states" in reason


# ============================================== what the op vocabulary allows
def test_no_operation_can_write_a_figure_into_the_data():
    """The structural half of §11: the type cannot express the edit at all."""
    fields = set(ReviseOp.model_fields)
    for forbidden in ("value", "cell", "rows", "fact", "facts", "figure", "amount"):
        assert forbidden not in fields


def test_sections_can_be_removed_and_restored(content):
    dropped = _revise(content, ReviseOp(op="drop_section",
                                        section_id="decisions"))
    assert "decisions" not in [s.section_id for s in dropped.content.narrative()]

    back = _revise(dropped.content, ReviseOp(op="restore_section",
                                             section_id="decisions"))
    assert "decisions" in [s.section_id for s in back.content.narrative()]


def test_the_data_quality_section_cannot_be_removed(content):
    """§12.5. Deleting the section that says what the report could not do is
    precisely the outcome that rule exists to prevent."""
    result = _revise(content, ReviseOp(op="drop_section",
                                       section_id="quality.limitations"))

    assert result.content is None
    assert "cannot be removed" in result.rejected[0].reason


def test_reordering_moves_sections_without_losing_any(content):
    before = [s.section_id for s in content.narrative()]
    result = _revise(content, ReviseOp(op="reorder", order=list(reversed(before))))

    assert sorted(s.section_id for s in result.content.narrative()) == sorted(before)


def test_an_added_section_is_prose_only_and_survives_a_replan(content):
    """A section whose rows came from a model would be data we never
    extracted — so a revision may add commentary, not evidence."""
    result = _revise(content, ReviseOp(
        op="add_section", label="TSA exit", text="TSA exit planning starts next month",
    ))
    added = result.content.narrative()[-1]

    assert added.origin == "user"
    assert added.locked
    assert [b.kind for b in added.blocks] == ["prose"]


def test_an_unknown_section_is_refused_rather_than_guessed_at(content):
    result = _revise(content, ReviseOp(op="drop_section", section_id="nope"))
    assert "no section" in result.rejected[0].reason


def test_a_revision_records_what_it_did_and_what_it_refused(content):
    result = _revise(
        content,
        ReviseOp(op="drop_section", section_id="decisions"),
        ReviseOp(op="rewrite_headline", section_id="risks.critical",
                 text="7 risks are open"),
        instruction="tidy this up",
    )

    assert result.applied and result.rejected
    assert result.content.provenance.instruction == "tidy this up"
    assert result.content.parent_version == content.version


def test_a_revision_never_mutates_the_version_it_started_from(content):
    before = [s.section_id for s in content.narrative()]
    _revise(content, ReviseOp(op="drop_section", section_id="decisions"))

    assert [s.section_id for s in content.narrative()] == before


# ======================================================== the keyless fallback
def test_common_instructions_work_with_no_model_available(content):
    revision = revise_fallback.interpret("remove the decisions section", content)
    assert revision.ops[0].op == "drop_section"
    assert revision.ops[0].section_id == "decisions"


def test_the_fallback_can_move_a_section_to_the_front(content):
    revision = revise_fallback.interpret("put critical risks first", content)
    order = revision.ops[0].order

    # The summary keeps position one — a report that opens with a risk table
    # and explains itself afterwards is not a report.
    assert order[0] == "summary.executive"
    assert order[1] == "risks.critical"


def test_the_fallback_says_it_did_not_understand_rather_than_guessing(content):
    revision = revise_fallback.interpret("make it pop", content)

    assert revision.ops == []
    assert "Could not interpret" in revision.rationale
