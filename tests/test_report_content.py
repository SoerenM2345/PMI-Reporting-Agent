"""The report-content IR and the fact table (`app/report/`).

Nothing renders from these yet — that is deliberate, so the IR can be pinned
before either generator depends on it. The behaviours asserted here are the ones
that make the layer safe to hand to an LLM later: a figure is either real or
explicitly absent, a count of zero is a finding rather than an absence, and the
set of numbers the report may state is closed and inspectable.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agent.calculations import recompute_derived
from app.extractors.base import make_source
from app.models.pmi import (
    Audience,
    BudgetItem,
    PMIDataModel,
    PMIProject,
    Risk,
    SourceFormat,
    Status,
    Synergy,
    Task,
)
from app.report.content import (
    Bullet,
    BulletsBlock,
    ReportContent,
    Section,
    TableBlock,
    TilesBlock,
    Tile,
    Column,
)
from app.report.facts import build_facts

XLSX = SourceFormat.EXCEL


@pytest.fixture
def model() -> PMIDataModel:
    """Enough shape to exercise the facts: an open critical risk, an overdue
    task, money on both sides, and a Day 1 task nobody has started.

    Runs `recompute_derived` exactly as the pipeline does — `is_overdue`,
    `risk_score` and `variance` are computed by `calculations.py` (§11), never
    inferred by whoever happens to be reading the model.
    """
    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan")
    built = PMIDataModel(
        project=PMIProject(project_id="p1", project_name="Project Aurora",
                           reporting_date=date.today()),
        tasks=[
            Task(task_id="T1", title="Payroll cutover", owner="Anna",
                 due_date=date.today() - timedelta(days=3),
                 status=Status.IN_PROGRESS, progress_percentage=60.0,
                 source_references=[xlsx]),
            Task(task_id="T2", title="Day 1 building access",
                 is_day_1_critical=True, status=Status.NOT_STARTED,
                 source_references=[xlsx]),
        ],
        risks=[
            Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                 impact=5, status=Status.IN_PROGRESS, source_references=[xlsx]),
        ],
        budget=[
            BudgetItem(budget_item_id="B1", category="Advisors", budget=1000.0,
                       actual=900.0, forecast=1250.0, source_references=[xlsx]),
        ],
        synergies=[
            Synergy(synergy_id="S1", title="Procurement", target_value=1_000_000.0,
                    realized_value=400_000.0, source_references=[xlsx]),
        ],
    )
    built, _ = recompute_derived(built, built.project.reporting_date)
    return built


# ================================================================ §7: absence
def test_a_project_we_know_nothing_about_reports_nothing_not_zero():
    """§7. A figure we do not have is "Not Reported". A zero is a claim."""
    facts = build_facts(PMIDataModel())

    for key in ("progress.overall", "budget.total", "synergy.target",
                "budget.variance", "synergy.realization_pct", "status.overall"):
        fact = facts.get(key)
        assert fact.value is None, f"{key} invented a value"
        assert fact.display == "Not Reported", f"{key} rendered as {fact.display!r}"


def test_a_count_of_zero_is_a_finding_not_an_absence():
    """"No open critical risks" is something we know. It must not read as
    "nobody told us about the risks" — that is the opposite claim."""
    facts = build_facts(PMIDataModel())

    zero = facts.get("risk.open_critical")
    assert zero.value == 0
    assert zero.display == "0"
    assert zero.display != "Not Reported"


def test_a_budget_summed_from_nothing_is_missing_rather_than_nil(model):
    """The totals are sums over optional fields, so 0 means "nobody reported a
    budget", not "the budget is zero"."""
    empty = model.model_copy(update={"budget": []})
    assert build_facts(empty).get("budget.total").display == "Not Reported"

    assert build_facts(model).get("budget.total").display == "1,000"


# =========================================================== computed figures
def test_figures_are_computed_not_copied(model):
    facts = build_facts(model)

    # 1000 budget - 1250 forecast = -250, computed here in Python (§11).
    assert facts.get("budget.variance").value == -250.0
    # 400k of a 1m target.
    assert round(facts.get("synergy.realization_pct").value) == 40
    assert facts.get("tasks.overdue").value == 1
    assert facts.get("day1.readiness").display == "0/1"


def test_status_refuses_to_state_a_position_the_sources_disagree_on(model):
    """§9. If two of our own files contradict each other, we do not have a
    status — and saying "On Track" would launder that into a fact."""
    from app.models.pmi import Conflict

    before = build_facts(model).get("status.overall").display
    assert before == "At Risk"          # an open critical risk

    contested = model.model_copy(update={
        "conflicts": [Conflict(check_id="PMI-002", entity_type="kpi",
                               entity_key="Overall Progress", field="value",
                               message="sources disagree")]
    })
    assert "Not agreed" in build_facts(contested).get("status.overall").display


def test_derived_figures_do_not_claim_a_source_file(model):
    """A variance we worked out ourselves has no single file to cite; saying
    "tracker.xlsx" would be a false citation."""
    variance = build_facts(model).get("budget.variance")
    assert all(ref.is_derived for ref in variance.refs)
    assert all(ref.file_name is None for ref in variance.refs)


def test_figures_read_from_files_carry_their_provenance(model):
    budget = build_facts(model).get("budget.total")
    assert any(ref.file_name == "tracker.xlsx" for ref in budget.refs)


# ============================================== the closed set of statable numbers
def test_the_corpus_holds_every_number_the_report_may_state(model):
    """`guard.py` will check model-authored prose against this. Anything not in
    here was invented by something."""
    corpus = build_facts(model).numeric_corpus()

    assert "1000" in corpus        # budget, thousands separator stripped
    assert "40" in corpus          # synergy realization, % stripped
    assert "1" in corpus           # one overdue task
    assert "9999" not in corpus


@pytest.mark.parametrize(
    "display,expected",
    [("1,250", "1250"), ("45%", "45"), ("45.0", "45"), ("-250", "-250")],
)
def test_the_corpus_compares_numbers_not_their_formatting(display, expected):
    from app.report.content import Fact, FactTable

    table = FactTable()
    table.add(Fact(key="k", label="l", value=None, display=display))
    assert expected in table.numeric_corpus()


# ================================================================ projections
def _content(sections: list[Section], audience=Audience.EXECUTIVE) -> ReportContent:
    return ReportContent(session_id="s", audience=audience, title="T",
                         sections=sections)


def test_the_narrative_is_ordered_and_audience_filtered():
    content = _content([
        Section(section_id="c", label="C", headline="H", narrative_order=3),
        Section(section_id="a", label="A", headline="H", narrative_order=1),
        Section(section_id="fin", label="Money", headline="H", narrative_order=2,
                audiences=[Audience.FINANCE]),
    ])
    assert [s.section_id for s in content.narrative()] == ["a", "c"]

    finance = content.model_copy(update={"audience": Audience.FINANCE})
    assert [s.section_id for s in finance.narrative()] == ["a", "fin", "c"]


def test_a_section_with_no_narrative_position_stays_out_of_the_deck():
    """§13's workbook carries sheets no deck shows. One IR, two projections:
    the workbook reads `sections`, everything else reads `narrative()`."""
    content = _content([
        Section(section_id="deck", label="D", headline="H", narrative_order=1),
        Section(section_id="dump", label="Masterplan", headline="H"),
    ])
    assert [s.section_id for s in content.narrative()] == ["deck"]
    assert len(content.sections) == 2


# ================================================================ persistence
def test_content_survives_a_save_and_reload():
    """Versions are stored as JSON, so every block type must round-trip through
    the discriminated union without losing its identity."""
    content = _content([
        Section(section_id="a", label="A", headline="H", narrative_order=1, blocks=[
            BulletsBlock(block_id="b1", items=[Bullet(text="one")]),
            TilesBlock(block_id="b2", tiles=[Tile(label="Budget",
                                                  fact_key="budget.total")]),
            TableBlock(block_id="b3", columns=[Column(header="Task")]),
        ]),
    ])

    reloaded = ReportContent.model_validate_json(content.model_dump_json())
    kinds = [b.kind for b in reloaded.sections[0].blocks]
    assert kinds == ["bullets", "tiles", "table"]
    assert reloaded.sections[0].blocks[1].tiles[0].fact_key == "budget.total"


def test_a_large_table_is_stored_by_reference_not_by_value():
    """The Masterplan is ~500 rows. Materialising it into every saved version
    would bloat storage and let the copy drift from the data model."""
    from app.report.content import EntityQuery

    derived = TableBlock(block_id="b", query=EntityQuery(entity="task"))
    materialised = TableBlock(block_id="b", rows=[[]])

    assert derived.is_derived
    assert not materialised.is_derived
