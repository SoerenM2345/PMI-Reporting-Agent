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


# ================================================== excluding rows, not pages
#: The two rows, and the instruction as it was actually typed — spaces lost in
#: the wrong places and the last word cut off. Cleaning it up first would test
#: a request nobody made.
TYPED = ("from open risks exclude Communicate toemployees andcustomers and "
         "Release thecombinedorganisationstructur")


@pytest.fixture
def risk_table(deliverable) -> Deliverable:
    page = deliverable.page("risks")
    page.elements = [TableElement(element_id="risks.table", spec_id="risk-table")]
    labels = ["Communicate to employees and customers",
              "Release the combined organisation structure",
              "GDPR retention breach"]
    deliverable.specs.tables["risk-table"] = TableSpec(
        spec_id="risk-table",
        columns=[Column(header="Risk"), Column(header="Owner")],
        rows=[[Cell(text=label), Cell(text="J. Smith")] for label in labels],
        row_evidence_ids=[f"ev:risk:R{index}" for index in range(3)],
        emphasis_rows=[2],
        total_rows=3,
    )
    return deliverable


def test_naming_rows_excludes_those_rows_and_not_the_page(risk_table):
    """The reported bug. The instruction names two rows of the risk register.

    Before `exclude_rows` existed the vocabulary had nowhere to put this, and
    the keyless path was worse than useless: "exclude" is also a `drop_page`
    verb, so a request to leave two rows out matched the page they are on and
    removed the entire register.
    """
    revision = keyword_ops(TYPED, risk_table)
    assert [op.op for op in revision.ops] == ["exclude_rows"]
    assert revision.ops[0].page_id == "risks"

    result = apply(risk_table, revision, corpus=CORPUS)

    assert result.changed
    assert result.deliverable.page("risks") is not None, "the page itself stays"
    spec = result.deliverable.specs.tables["risk-table"]
    assert [row[0].text for row in spec.rows] == ["GDPR retention breach"]
    assert [row.label for row in spec.excluded_rows] == [
        "Communicate to employees and customers",
        "Release the combined organisation structure",
    ]


def test_excluding_keeps_the_parallel_arrays_aligned(risk_table):
    """`emphasis_rows` and `row_evidence_ids` are index-parallel to `rows`.

    Filtering at the display boundary instead would leave the emphasis on
    whichever row moved into position 2 — a different risk, highlighted as
    though the report meant it.
    """
    result = apply(risk_table, keyword_ops(TYPED, risk_table), corpus=CORPUS)
    spec = result.deliverable.specs.tables["risk-table"]

    assert spec.row_evidence_ids == ["ev:risk:R2"]
    assert spec.emphasis_rows == [0]
    assert spec.displayed_rows == spec.rows, "still a prefix, as renderers assume"


def test_an_excluded_table_says_it_was_filtered_without_naming_the_rows(
        risk_table):
    """A filtered risk register that looks complete is the dangerous outcome.

    Naming the excluded rows in the note would republish exactly what the
    author asked to leave out, so the count is stated and the rows are not.
    """
    result = apply(risk_table, keyword_ops(TYPED, risk_table), corpus=CORPUS)
    spec = result.deliverable.specs.tables["risk-table"]

    assert "2 row(s) excluded at the author's request." in spec.warnings
    assert "Communicate" not in " ".join(spec.warnings)
    assert spec.truncation_note() == "", "exclusion is not truncation"


def test_the_excluded_rows_are_not_reprinted_in_the_document(risk_table):
    """The revision note is rendered — into the limitations every format prints.

    So a note naming the excluded rows, or quoting the instruction that named
    them, republishes in the appendix exactly what the author took out of the
    table. The chat reply still names them: that is a confirmation to the
    person who asked, not a page in the report.
    """
    result = apply(risk_table, keyword_ops(TYPED, risk_table), corpus=CORPUS,
                   instruction=TYPED)

    assert "Communicate to employees" in result.applied[0], "the user is told"
    printed = " ".join(result.deliverable.notes)
    assert "Communicate" not in printed
    assert "organisation" not in printed
    assert "excluded 2 row(s) from “Open risks”" in printed


def test_an_excluded_row_can_be_put_back(risk_table):
    excluded = apply(risk_table, keyword_ops(TYPED, risk_table), corpus=CORPUS)
    result = apply(excluded.deliverable,
                   DeliverableRevision(ops=[PageOp(
                       op="restore_rows", page_id="risks",
                       rows=["Communicate to employees and customers"])]),
                   corpus=CORPUS)

    spec = result.deliverable.specs.tables["risk-table"]
    assert [row[0].text for row in spec.rows] == [
        "Communicate to employees and customers", "GDPR retention breach"]
    assert spec.row_evidence_ids == ["ev:risk:R0", "ev:risk:R2"]
    assert spec.emphasis_rows == [1], "the emphasis followed its own row"


def test_a_row_that_does_not_exist_is_reported_not_ignored(risk_table):
    """§21.17: the half that could not be done is said in the same breath."""
    result = apply(risk_table, DeliverableRevision(ops=[PageOp(
        op="exclude_rows", page_id="risks",
        rows=["GDPR retention breach", "Whatever the CFO said"])]),
        corpus=CORPUS)

    assert result.changed
    assert "found no row matching “Whatever the CFO said”" in result.applied[0]


def test_no_row_matching_at_all_refuses_rather_than_excluding_something(
        risk_table):
    result = apply(risk_table, DeliverableRevision(ops=[PageOp(
        op="exclude_rows", page_id="risks", rows=["Whatever the CFO said"])]),
        corpus=CORPUS)

    assert result.deliverable is None
    assert "no row on “Open risks” matches" in result.rejected[0].reason


def test_removing_a_whole_page_still_removes_the_whole_page(risk_table):
    """The row rule runs first and must not swallow the page-level instruction."""
    revision = keyword_ops("remove the open risks page", risk_table)

    assert [op.op for op in revision.ops] == ["drop_page"]


def test_the_same_instruction_works_when_the_page_uses_bullets(deliverable):
    """Whether risks are a table or a list is a layout decision the user never
    made, so the instruction cannot be allowed to depend on it."""
    page = deliverable.page("risks")
    page.elements = [BulletsElement(element_id="risks.b", items=[
        "Communicate to employees and customers",
        "Release the combined organisation structure",
        "GDPR retention breach",
    ])]

    revision = keyword_ops(TYPED, deliverable)
    assert [op.op for op in revision.ops] == ["drop_bullet", "drop_bullet"]
    # Descending, or the second op removes whatever slid into the first's place.
    assert [op.index for op in revision.ops] == [1, 0]

    result = apply(deliverable, revision, corpus=CORPUS)
    assert result.deliverable.page("risks").elements[0].items == [
        "GDPR retention breach"]


def test_naming_nothing_the_page_has_declines_instead_of_deleting_it(
        risk_table):
    """The outcome that made this worth fixing.

    "from X exclude Y" is unambiguously about part of X. When Y matches
    nothing, the old fall-through reached `drop_page` and removed X — turning a
    request the agent did not understand into the largest possible edit.
    """
    revision = keyword_ops("from open risks exclude whatever the CFO said",
                           risk_table)

    assert revision.ops == []
    assert "nothing matching that" in revision.rationale

    result, warnings = revise(risk_table,
                              "from open risks exclude whatever the CFO said",
                              corpus=CORPUS, use_model=False)
    assert result.deliverable is None
    assert risk_table.page("risks") is not None


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
