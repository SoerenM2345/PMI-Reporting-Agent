"""Ranking and packing evidence (`app/evidence/{scoring,retrieval}.py`).

Retrieval decides what a planning model gets to see, which makes it the last
place a finding can quietly disappear. So the tests here are as much about what
must *survive* selection as about what ranks well.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.evidence import projection
from app.evidence.model import EvidenceIndex, EvidenceItem
from app.evidence.retrieval import pack, retrieve
from app.evidence.scoring import build_index, expand, tokenize
from app.extractors.base import make_source
from app.models.pmi import (
    BudgetItem,
    Conflict,
    Milestone,
    PMIDataModel,
    PMIProject,
    Risk,
    Severity,
    SourceFormat,
    Status,
    Synergy,
    Task,
)
from app.models.quality import ConflictEvidence

XLSX = SourceFormat.EXCEL
TODAY = date(2026, 7, 27)


@pytest.fixture
def index() -> EvidenceIndex:
    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan")
    model = PMIDataModel(
        project=PMIProject(project_id="p1", project_name="Aurora",
                           reporting_date=TODAY),
        source_files=["tracker.xlsx"],
        tasks=[
            Task(task_id=f"T{n}", title=f"Routine task {n}", owner="Sam",
                 workstream="Operations", status=Status.IN_PROGRESS,
                 progress_percentage=50.0, source_references=[xlsx])
            for n in range(1, 41)
        ] + [
            Task(task_id="T99", title="Payroll cutover for Day 1", owner="Anna",
                 workstream="Finance", due_date=TODAY - timedelta(days=3),
                 status=Status.BLOCKED, source_references=[xlsx]),
        ],
        risks=[
            Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                 impact=5, status=Status.IN_PROGRESS, source_references=[xlsx]),
            Risk(risk_id="R2", title="Office lease renewal", probability=1,
                 impact=1, status=Status.COMPLETED, mitigation_action="Signed",
                 owner="Jo", source_references=[xlsx]),
        ],
        budget=[
            BudgetItem(budget_item_id="B1", category="ERP migration",
                       budget=1_000_000.0, actual=900_000.0, forecast=1_220_000.0,
                       currency="EUR", source_references=[xlsx]),
        ],
        synergies=[
            Synergy(synergy_id="S1", title="Procurement consolidation",
                    target_value=1_000_000.0, realized_value=400_000.0,
                    currency="EUR", source_references=[xlsx]),
        ],
        milestones=[
            Milestone(milestone_id="M1", name="ERP go-live",
                      planned_date=date(2026, 9, 15), source_references=[xlsx]),
        ],
    )
    return projection.project(model)


# --------------------------------------------------------------- tokenizing
def test_tokenizing_drops_noise_and_de_pluralises():
    assert tokenize("What are the open Risks?") == ["open", "risk"]
    assert tokenize("synergies") == ["synergy"]
    assert tokenize("dependencies for Day 1") == ["dependency", "day", "1"]


def test_the_thesaurus_bridges_the_words_users_and_trackers_use():
    """A finance section that retrieves nothing is not a ranking nuisance."""
    assert "synergy" in expand(tokenize("cost savings"))
    assert "day-1" in expand(tokenize("cutover"))
    assert "variance" in expand(tokenize("budget overrun"))
    assert "decision" in expand(tokenize("steerco approval"))


def test_expansion_does_not_duplicate_or_reorder():
    expanded = expand(["risk", "risk", "budget"])
    assert expanded[0] == "risk"
    assert len(expanded) == len(set(expanded))


def test_bm25_prefers_the_rarer_term():
    index = build_index([
        ("a", "budget budget budget routine"),
        ("b", "routine routine routine routine"),
        ("c", "gdpr breach"),
    ])
    assert index.bm25("a", ["budget"]) > index.bm25("b", ["budget"])
    assert index.bm25("c", ["gdpr"]) > index.bm25("a", ["gdpr"])


# ---------------------------------------------------------------- retrieval
def test_a_topical_query_ranks_its_own_evidence_first(index):
    result = retrieve("budget overrun on the ERP migration", index, k=6)
    top = result.ids[:4]
    assert "ev:budget:B1" in top
    assert "ev:fact:budget.variance" in top


def test_a_synergy_query_finds_evidence_that_never_says_synergy(index):
    result = retrieve("how are cost savings tracking?", index, k=8)
    assert "ev:synergy:S1" in result.ids


def test_open_and_severe_evidence_outranks_closed_and_trivial(index):
    result = retrieve("risks", index, k=10)
    ranked = result.ids
    assert ranked.index("ev:risk:R1") < ranked.index("ev:risk:R2")


def test_a_low_confidence_read_is_ranked_down_but_never_hidden(index):
    """It still belongs in the document, carrying its disclosure."""
    faint = make_source("photo.png", SourceFormat.IMAGE, extraction_confidence=0.3)
    item = EvidenceItem(evidence_id="ev:risk:R3", kind="risk",
                        origin="normalized_value", label="Budget overrun risk",
                        statement="Budget overrun risk", status="in_progress",
                        sources=[faint], search_text="budget overrun risk")
    item2 = EvidenceItem(evidence_id="ev:risk:R4", kind="risk",
                         origin="normalized_value", label="Budget overrun risk",
                         statement="Budget overrun risk", status="in_progress",
                         sources=[make_source("tracker.xlsx", XLSX)],
                         search_text="budget overrun risk")
    index.add(item)
    index.add(item2)
    result = retrieve("budget overrun risk", index, k=50)
    assert result.ids.index("ev:risk:R4") < result.ids.index("ev:risk:R3")
    assert "ev:risk:R3" in result.ids


# ------------------------------------------------------ the non-negotiable
def test_must_include_evidence_survives_an_unrelated_query(index):
    """The rule the whole layer exists to guarantee.

    A finance query must not be the mechanism by which an unresolved critical
    disagreement fails to reach the board pack.
    """
    conflict = Conflict(
        check_id="PMI-002", entity_type="milestone", entity_key="ERP go-live",
        field="planned_date", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX), value="2026-09-15")],
    )
    index.add(projection.project(
        PMIDataModel(conflicts=[conflict])).get(f"ev:conflict:{conflict.conflict_id}"))

    required = set(index.must_include())
    assert required, "the fixture must actually have must-include evidence"

    result = retrieve("office lease renewal paperwork", index, k=2)
    assert required <= set(result.ids)
    assert set(result.forced_ids) == required


def test_k_is_widened_rather_than_dropping_forced_evidence(index):
    required = index.must_include()
    result = retrieve("nothing at all like this", index, k=1)
    assert len(result.included) >= len(required)
    assert set(required) <= set(result.ids)


# --------------------------------------------------------------- disclosure
def test_truncation_is_reported_not_hidden(index):
    """A model told it sees everything will state totals it cannot support."""
    result = retrieve("tasks", index, k=5)
    assert result.truncated
    assert result.omitted_count == len(index) - len(result.included)
    assert result.omitted_kinds

    disclosure = result.disclosure()
    assert f"{len(result.included)} of {len(index)}" in disclosure
    assert "Do not state totals" in disclosure


def test_an_untruncated_result_says_so(index):
    result = retrieve("everything", index, k=1000)
    assert not result.truncated
    assert "every record" in result.disclosure()


# ------------------------------------------------------------------ packing
def test_packing_emits_dense_lines_within_budget(index):
    result = retrieve("budget and risk", index, k=40)
    packed = pack(result, budget_chars=1500)

    assert packed.char_count <= 1500
    assert packed.included_ids
    assert all(line.startswith("ev:") for line in packed.text.splitlines())
    assert "\n" in packed.text


def test_packing_drops_the_tail_never_half_a_record(index):
    """A truncated final line would present a half-read figure as a whole one."""
    result = retrieve("budget", index, k=40)
    packed = pack(result, budget_chars=400)
    lines = packed.text.splitlines()
    assert len(packed.included_ids) == len(lines)
    for line, evidence_id in zip(lines, packed.included_ids):
        assert line == index.get(evidence_id).one_line()


def test_packing_states_what_it_trimmed(index):
    result = retrieve("budget", index, k=40)
    packed = pack(result, budget_chars=300)
    assert "trimmed to fit" in packed.disclosure


def test_the_highest_ranked_evidence_survives_a_tight_budget(index):
    result = retrieve("budget overrun", index, k=40)
    packed = pack(result, budget_chars=350)
    assert packed.included_ids[0] == result.ids[0]


# ------------------------------------------------------------------ filters
def test_retrieval_can_be_restricted_to_kinds(index):
    result = retrieve("anything", index, kinds=["risk"], k=20)
    assert {i.kind for i in result.included} <= {"risk"}


def test_an_empty_index_retrieves_nothing_without_raising():
    result = retrieve("budget", EvidenceIndex(), k=10)
    assert result.included == [] and not result.truncated
    assert pack(result).text == ""
