"""Versioned storage and staleness (`app/deliverable/{store,fingerprint}.py`).

The staleness story is the interesting one. `ReportContent` carried a single
hash of entity counts, so resolving one conflict invalidated an entire draft.
Here the digest is kept per evidence item, which is what makes it possible to
rebuild the three pages that actually moved.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.context import builder
from app.context.schemas import KnowledgeDigest
from app.deliverable import fingerprint as fp
from app.deliverable import store
from app.deliverable.model import Deliverable, PageDesign, TextElement
from app.extractors.base import make_source
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
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)
    return tmp_path


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
                    impact=5, status=Status.IN_PROGRESS,
                    source_references=[xlsx])],
        budget=[BudgetItem(budget_item_id="B1", category="Advisors",
                           budget=1000.0, actual=900.0, forecast=1250.0,
                           source_references=[xlsx])],
    )
    # Derived fields must already be settled, or the "before" fingerprint
    # differs from the "after" one for reasons that have nothing to do with
    # the change under test.
    built, _ = recompute_derived(built, built.project.reporting_date)
    return built


def context_for(model, request_text="Prepare a pack."):
    return builder._assemble(
        scope="project", project_id="proj", chat_id=None, session_id=None,
        model=model, digest=KnowledgeDigest(), folder_name="Aurora",
        quality=None, request_text=request_text, requested_format=None,
        messages=[])


def a_deliverable(**kwargs) -> Deliverable:
    defaults = dict(
        deliverable_id="dlv_1", project_id="proj", title="Status",
        pages=[
            PageDesign(page_id="risks", index=0, evidence_ids=["ev:risk:R1"],
                       title="Risks", elements=[TextElement(
                           element_id="e1", role="body", text="Risk detail")]),
            PageDesign(page_id="spend", index=1, evidence_ids=["ev:budget:B1"],
                       title="Spend"),
        ],
    )
    defaults.update(kwargs)
    return Deliverable(**defaults)


# ------------------------------------------------------------------- store
def test_versions_are_appended_never_overwritten():
    first = store.save(a_deliverable())
    second = store.save(a_deliverable(title="Status, revised"))

    assert first.version == 1 and second.version == 2
    assert store.versions(project_id="proj") == [1, 2]
    assert store.head(project_id="proj") == 2
    assert store.load(project_id="proj").title == "Status, revised"
    assert store.load(project_id="proj", version=1).title == "Status"


def test_reverting_appends_rather_than_rewinding():
    """A user who went back should be able to see that they went back."""
    store.save(a_deliverable(title="v1"))
    store.save(a_deliverable(title="v2"))

    reverted = store.revert(project_id="proj", version=1)
    assert reverted.version == 3
    assert reverted.title == "v1"
    assert reverted.parent_version == 1
    assert "Reverted to version 1" in reverted.notes[-1]
    assert store.versions(project_id="proj") == [1, 2, 3]


def test_reverting_to_a_version_that_does_not_exist_returns_none():
    store.save(a_deliverable())
    assert store.revert(project_id="proj", version=99) is None


def test_the_two_stacks_do_not_share_a_shelf():
    store.save(a_deliverable(project_id="proj", session_id=None))
    store.save(a_deliverable(deliverable_id="dlv_2", project_id=None,
                             session_id="sess"))
    assert store.head(project_id="proj") == 1
    assert store.head(session_id="sess") == 1


def test_a_chat_draft_with_both_ids_is_stored_on_its_session_shelf():
    stored = store.save(a_deliverable(session_id="chat-session"))

    assert store.load(session_id="chat-session").deliverable_id == \
        stored.deliverable_id
    assert store.load(project_id="proj") is None


def test_an_absent_deliverable_reads_as_none():
    assert store.load(project_id="nobody") is None
    assert store.head(project_id="nobody") is None
    assert store.versions(project_id="nobody") == []


def test_a_deliverable_that_no_longer_validates_is_treated_as_absent(storage):
    """A schema change should mean "re-plan", not a 500."""
    store.save(a_deliverable())
    path = storage / "projects" / "proj" / "deliverables" / "v1.json"
    path.write_text('{"pages": "not a list"}', encoding="utf-8")
    assert store.load(project_id="proj") is None


def test_a_deliverable_needs_a_scope():
    with pytest.raises(ValueError):
        store.load()


# ------------------------------------------------------------- fingerprint
def test_an_unchanged_project_is_not_stale(model):
    context = context_for(model)
    current = fp.compute(context)
    deliverable = a_deliverable(fingerprint=current.model_dump())
    assert not fp.is_stale(deliverable, fp.compute(context_for(model)))


def test_changing_a_figure_stales_only_the_pages_that_used_it(model):
    """The whole point of a per-item digest.

    A single hash of entity counts could only say "the draft is stale", so
    resolving one conflict meant rebuilding every page.
    """
    context = context_for(model)
    deliverable = a_deliverable(fingerprint=fp.compute(context).model_dump())

    model.budget[0].forecast = 9_999.0
    from app.agent.calculations import recompute_derived

    model, _ = recompute_derived(model, model.project.reporting_date)
    later = fp.compute(context_for(model))

    assert fp.is_stale(deliverable, later)
    assert fp.stale_pages(deliverable, later) == ["spend"]
    assert "evidence have changed" in fp.stale_reason(deliverable, later)


def test_a_changed_request_stales_the_whole_document(model):
    """The argument is now questionable, not just its figures — so there is no
    page list to hand back, because this is a re-plan, not a repair."""
    deliverable = a_deliverable(
        fingerprint=fp.compute(context_for(model, "Prepare a pack.")).model_dump())
    later = fp.compute(context_for(model, "Actually, just the finance position."))

    assert fp.is_stale(deliverable, later)
    assert fp.stale_pages(deliverable, later) == []
    assert "request has changed" in fp.stale_reason(deliverable, later)


def test_an_engine_change_stales_everything(model):
    context = context_for(model)
    stored = fp.compute(context)
    stored.engine_version = fp.ENGINE_VERSION - 1
    deliverable = a_deliverable(fingerprint=stored.model_dump())

    later = fp.compute(context)
    assert fp.is_stale(deliverable, later)
    assert "engine has changed" in fp.stale_reason(deliverable, later)


def test_resolving_a_conflict_stales_the_pages_that_cited_the_figure(model):
    """The value did not move; what may be *asserted* about it did."""
    from app.models.pmi import Conflict, Severity
    from app.models.quality import ConflictEvidence

    conflict = Conflict(
        check_id="PMI-002", entity_type="risk", entity_key="GDPR retention breach",
        field="risk_score", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX), value="20")],
    )
    model.conflicts.append(conflict)
    deliverable = a_deliverable(
        fingerprint=fp.compute(context_for(model)).model_dump())

    conflict.resolved_value = "20"
    conflict.resolution = "user"
    later = fp.compute(context_for(model))

    assert fp.is_stale(deliverable, later)
    assert "risks" in fp.stale_pages(deliverable, later)


def test_a_draft_planned_before_references_were_fingerprinted_is_not_stale(model):
    """An unrecorded reference digest is unknown, not changed.

    `compute` hashes the empty constraint list to a real value, so a stored
    empty digest can only mean the draft predates the field. Comparing the two
    marked 116 of the sample sessions permanently stale and disabled Generate
    with no way back — while blaming "a source file explicitly reused by this
    report" on reports that reuse no files at all.
    """
    context = context_for(model)
    stored = fp.compute(context)
    assert stored.reference_digest, "compute must never produce an empty digest"
    stored.reference_digest = ""              # a draft from before the field
    deliverable = a_deliverable(fingerprint=stored.model_dump())

    assert not fp.is_stale(deliverable, fp.compute(context))
    assert fp.stale_reason(deliverable, fp.compute(context)) == ""


def test_a_reference_that_really_changed_is_still_caught(model):
    """The tolerance above is for absence only; two known digests still differ."""
    context = context_for(model)
    stored = fp.compute(context)
    deliverable = a_deliverable(fingerprint=stored.model_dump())

    later = fp.compute(context)
    later.reference_digest = "0123456789abcdef"
    assert fp.is_stale(deliverable, later)
    assert "source file" in fp.stale_reason(deliverable, later)
    assert fp.stale_pages(deliverable, later) == []


def test_a_deliverable_with_no_fingerprint_is_stale(model):
    assert fp.is_stale(a_deliverable(), fp.compute(context_for(model)))
    assert "predates" in fp.stale_reason(a_deliverable(),
                                         fp.compute(context_for(model)))


def test_removing_evidence_is_a_change_too(model):
    context = context_for(model)
    deliverable = a_deliverable(fingerprint=fp.compute(context).model_dump())

    model.budget.clear()
    later = fp.compute(context_for(model))
    assert fp.is_stale(deliverable, later)
    assert "spend" in fp.stale_pages(deliverable, later)


# ---------------------------------------------------------------- the model
def test_a_page_knows_whether_it_is_empty():
    assert PageDesign(page_id="p").is_empty
    assert not PageDesign(page_id="p", elements=[
        TextElement(element_id="e", role="body", text="x")]).is_empty
    # A divider is one line of type by design, not an empty page.
    assert not PageDesign(page_id="p", purpose="divider", title="Finance").is_empty
    assert PageDesign(page_id="p", purpose="divider").is_empty


def test_replacing_a_page_keeps_its_position():
    deliverable = a_deliverable()
    deliverable.replace_page(PageDesign(page_id="spend", title="Spend, revised"))
    assert deliverable.pages[1].title == "Spend, revised"
    assert deliverable.pages[1].index == 1

    with pytest.raises(KeyError):
        deliverable.replace_page(PageDesign(page_id="nope"))


def test_a_deliverable_reports_what_it_drew_on():
    deliverable = a_deliverable()
    assert deliverable.evidence_ids == ["ev:risk:R1", "ev:budget:B1"]
    assert deliverable.page_count == 2
    assert "Risk detail" in deliverable.text_content()


# ------------------------------------------------------- the user's own words
def _kb_with(**overrides):
    from app.agent.knowledge import KnowledgeBase
    from app.deliverable.session import OVERRIDE_PREFIX

    kb = KnowledgeBase(session_id="s1")
    for element_id, text in overrides.items():
        kb.set_prose_override(f"{OVERRIDE_PREFIX}{element_id}", text)
    return kb


def _page_with(*elements, page_id="risks", title="Open risks") -> PageDesign:
    return PageDesign(page_id=page_id, title=title, elements=list(elements))


def test_an_override_survives_an_element_inserted_above_it():
    """The failure this guards: element ids used to encode a *position*, so
    resolving a conflict that let a chart validate renumbered everything below
    it and the user's rewritten paragraph landed on a different element."""
    from app.deliverable.model import ChartElement
    from app.deliverable.session import apply_overrides

    mine = "Integration is on track for Day 1."
    kb = _kb_with(**{"risks.body1": mine})

    # The same page re-planned, now with a chart ahead of the paragraph.
    replanned = Deliverable(deliverable_id="d", pages=[_page_with(
        ChartElement(element_id="risks.chart1", spec_id="risks.chart1-chart"),
        TextElement(element_id="risks.body1", role="body", text="Regenerated."),
    )])

    assert apply_overrides(replanned, kb) == []
    body = replanned.pages[0].element("risks.body1")
    assert body.text == mine
    assert body.authored_by == "user"


def test_an_override_with_nowhere_to_go_is_reported_not_dropped():
    """Text the user typed cannot vanish silently. If the element it was
    written for is gone, say so — in the artifact, not only in a log."""
    from app.deliverable.session import apply_overrides

    kb = _kb_with(**{"risks.body1": "My wording."})
    replanned = Deliverable(deliverable_id="d", pages=[_page_with(
        TextElement(element_id="spend.body1", role="body", text="Kept."),
        page_id="spend", title="Budget position",
    )])

    warnings = apply_overrides(replanned, kb)
    assert len(warnings) == 1
    assert "could not be restored" in warnings[0]
    assert "still saved" in warnings[0]


def test_an_override_names_the_page_it_was_written_for():
    from app.deliverable.session import apply_overrides

    kb = _kb_with(**{"risks.bullets1": "My wording."})
    replanned = Deliverable(deliverable_id="d", pages=[_page_with(
        TextElement(element_id="risks.body1", role="body", text="Kept."),
    )])

    assert "Open risks" in apply_overrides(replanned, kb)[0]
