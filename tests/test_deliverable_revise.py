"""Revising a `Deliverable` (`app/deliverable/revise.py`).

`app/report/ops.py` made §11 structural for the old content object: no field on
a revision op could reach a figure. These assert the same thing about the new
one — the op vocabulary reorders, removes and rewords, and a number outside the
evidence is refused with the offending value named rather than quietly dropped.

The rest is about what a revision must *not* be allowed to do: remove the page
that says what the report could not establish, invent a page id, or lose a page
so completely that "put it back" needs a re-plan.
"""
from __future__ import annotations

import pytest

from app.deliverable.model import (
    BulletsElement,
    Deliverable,
    PageDesign,
    TableElement,
    TextElement,
)
from app.deliverable.revise import (
    DeliverableRevision,
    PageOp,
    apply,
    keyword_ops,
    revise,
)
from app.report.content import Cell, Column
from app.visualizations.specs import TableSpec

#: What the evidence supports. Everything else is an invented figure.
CORPUS = {"4", "82"}


@pytest.fixture
def deliverable() -> Deliverable:
    return Deliverable(
        deliverable_id="dlv_1", session_id="s1", title="Status",
        pages=[
            PageDesign(page_id="cover", index=0, purpose="cover",
                       title="Project Aurora"),
            PageDesign(page_id="risks", index=1, title="Open risks",
                       evidence_ids=["ev:risk:R1"],
                       elements=[BulletsElement(element_id="risks.b",
                                                items=["GDPR retention breach"])]),
            PageDesign(page_id="spend", index=2, title="Budget position",
                       elements=[TextElement(element_id="spend.body",
                                             role="body", text="Spend detail")]),
            PageDesign(page_id="limits", index=3, purpose="appendix",
                       title="Data quality and limitations"),
        ],
    )


def _apply(deliverable, *ops, corpus=CORPUS):
    return apply(deliverable, DeliverableRevision(ops=list(ops)), corpus=corpus)


# ============================================================ §11, structurally
def test_no_op_can_carry_a_value_into_the_document():
    """The guarantee is the type, not the prompt.

    A `value:` field here would undo §11 no matter how the prompt were worded,
    so the absence of one is asserted rather than assumed.
    """
    forbidden = {"value", "figure", "number", "amount", "cell", "row_value"}
    assert not forbidden & set(PageOp.model_fields)


def test_a_figure_the_evidence_does_not_hold_is_refused_by_name(deliverable):
    result = _apply(deliverable,
                    PageOp(op="add_bullet", page_id="risks",
                           text="We now have 4173 critical risks open."))

    assert result.deliverable is None
    assert "4173" in result.rejected[0].reason
    # And the page is untouched — a refusal is not a partial write.
    assert deliverable.page("risks").elements[0].items == ["GDPR retention breach"]


def test_a_figure_the_evidence_does_hold_is_accepted(deliverable):
    result = _apply(deliverable,
                    PageOp(op="add_bullet", page_id="risks",
                           text="4 critical risks remain open."))

    assert result.deliverable is not None
    items = result.deliverable.page("risks").elements[0].items
    assert items[-1] == "4 critical risks remain open."


def test_wording_with_no_figure_at_all_is_always_allowed(deliverable):
    result = _apply(deliverable,
                    PageOp(op="rewrite_title", page_id="spend",
                           text="Spend is running ahead of plan"))

    assert result.deliverable.page("spend").title == \
        "Spend is running ahead of plan"


# ================================================================ §12.5 and ids
def test_the_data_quality_page_cannot_be_removed(deliverable):
    result = _apply(deliverable, PageOp(op="drop_page", page_id="limits"))

    assert result.deliverable is None
    assert "entitled to see" in result.rejected[0].reason


def test_an_unknown_page_is_refused_rather_than_guessed(deliverable):
    result = _apply(deliverable, PageOp(op="drop_page", page_id="nope"))

    assert result.deliverable is None
    assert "no page 'nope'" in result.rejected[0].reason


def test_a_dropped_page_survives_so_it_can_be_restored(deliverable):
    dropped = _apply(deliverable, PageOp(op="drop_page", page_id="spend"))
    assert [p.page_id for p in dropped.deliverable.pages] == \
        ["cover", "risks", "limits"]
    assert [p.page_id for p in dropped.deliverable.dropped_pages] == ["spend"]

    restored = _apply(dropped.deliverable,
                      PageOp(op="restore_page", page_id="spend"))
    assert "spend" in [p.page_id for p in restored.deliverable.pages]
    assert restored.deliverable.dropped_pages == []


def test_reordering_leaves_the_cover_where_it_is(deliverable):
    result = _apply(deliverable,
                    PageOp(op="reorder", order=["spend", "risks", "limits"]))

    assert [p.page_id for p in result.deliverable.pages] == \
        ["cover", "spend", "risks", "limits"]
    assert [p.index for p in result.deliverable.pages] == [0, 1, 2, 3]


# ============================================================== nothing silent
def test_one_refused_op_does_not_discard_the_ones_that_worked(deliverable):
    result = _apply(
        deliverable,
        PageOp(op="rewrite_title", page_id="spend", text="Spend is under control"),
        PageOp(op="drop_page", page_id="limits"),
    )

    assert result.deliverable is not None
    assert result.applied and result.rejected
    assert result.deliverable.page("spend").title == "Spend is under control"
    assert result.deliverable.page("limits") is not None


def test_a_revision_that_changes_nothing_returns_no_document(deliverable):
    result = _apply(deliverable, PageOp(op="drop_page", page_id="limits"))

    assert result.deliverable is None, \
        "handing back the old version would look like the edit succeeded"
    assert result.changed is False


def test_an_applied_revision_becomes_the_next_version(deliverable):
    result = _apply(deliverable,
                    PageOp(op="rewrite_title", page_id="risks", text="Risks bite"))

    assert result.deliverable.version == deliverable.version + 1
    assert result.deliverable.parent_version == deliverable.version
    assert "Risks bite" not in deliverable.page("risks").title, \
        "the input was mutated; applying is supposed to be pure"


# ================================================================ keyless path
@pytest.mark.parametrize("instruction, expected", [
    ("remove the budget page", "drop_page"),
    ("put risks first", "reorder"),
    ("show 5 rows on the budget page", "set_row_limit"),
    ("rename Budget position into Next Steps for GlobalMed x MediTexh",
     "rewrite_title"),
])
def test_the_common_instructions_are_understood_without_a_model(
        deliverable, instruction, expected):
    revision = keyword_ops(instruction, deliverable)
    assert [op.op for op in revision.ops] == [expected]


def test_show_all_rows_keeps_and_reveals_the_complete_quality_table(
        deliverable, monkeypatch):
    """Regression: changing 12 to 26 cannot reveal rows discarded at plan time."""
    page = deliverable.page("limits")
    page.elements = [TableElement(element_id="limits.table",
                                  spec_id="quality-table")]
    deliverable.specs.tables["quality-table"] = TableSpec(
        spec_id="quality-table",
        columns=[Column(header="Finding")],
        rows=[[Cell(text=f"finding {index}")] for index in range(26)],
        row_evidence_ids=[f"ev:quality:{index}" for index in range(26)],
        evidence_ids=[f"ev:quality:{index}" for index in range(26)],
        total_rows=26,
        row_limit=12,
        warnings=["Showing 12 of 26 rows."],
    )

    # This exact instruction is deterministic; a model returning no operations
    # must never make the agent ignore it.
    monkeypatch.setattr(
        "app.llm.tasks.run_task",
        lambda *args, **kwargs: pytest.fail("direct row request called the model"),
    )
    result, warnings = revise(
        deliverable,
        "show all 26 of 26 rows in Data quality and limitations",
        use_model=True,
    )

    assert warnings == []
    assert result.changed
    spec = result.deliverable.specs.tables["quality-table"]
    assert len(spec.rows) == 26
    assert len(spec.displayed_rows) == 26
    assert spec.truncation_note() == ""
    assert "Showing 12 of 26 rows." not in spec.warnings

    from app.deliverable.preview import blocks

    quality = next(block for section in blocks(result.deliverable)
                   if section["section_id"] == "limits"
                   for block in section["blocks"]
                   if block["kind"] == "table")
    assert len(quality["rows"]) == 26
    assert quality["note"] == ""


def test_show_all_rows_without_repeating_the_count_uses_the_table_total(
        deliverable):
    page = deliverable.page("limits")
    page.elements = [TableElement(element_id="limits.table",
                                  spec_id="quality-table")]
    deliverable.specs.tables["quality-table"] = TableSpec(
        spec_id="quality-table",
        columns=[Column(header="Finding")],
        rows=[[Cell(text=f"finding {index}")] for index in range(26)],
        total_rows=26,
        row_limit=12,
    )

    revision = keyword_ops(
        "show all rows in Data quality and limitations", deliverable)

    assert revision.ops == [PageOp(
        op="set_row_limit", page_id="limits", row_limit=26)]


def test_a_keyless_rename_preserves_the_users_casing(deliverable):
    revision = keyword_ops(
        "rename Budget position into Next Steps for GlobalMed x MediTexh",
        deliverable,
    )
    assert revision.ops[0].page_id == "spend"
    assert revision.ops[0].text == "Next Steps for GlobalMed x MediTexh"


def test_an_instruction_it_cannot_read_is_declined_not_guessed(deliverable):
    revision = keyword_ops("make it pop", deliverable)

    assert revision.ops == []
    assert "Could not interpret" in revision.rationale


def test_declining_explains_itself_through_the_public_entry_point(deliverable):
    result, warnings = revise(deliverable, "make it pop", corpus=CORPUS,
                              use_model=False)

    assert result.deliverable is None
    assert warnings and "Could not interpret" in warnings[0]
