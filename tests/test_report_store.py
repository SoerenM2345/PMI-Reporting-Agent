"""Versioned content storage and the staleness check (`app/report/store.py`).

The staleness test is the one that matters. Everything else here is bookkeeping;
that one guards against rendering a deck whose figures the user has already
corrected.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.agent.data_quality import build_report
from app.extractors.base import make_source
from app.models.pmi import (
    Audience,
    Conflict,
    PMIDataModel,
    PMIProject,
    Risk,
    SourceFormat,
    Status,
)
from app.report import store
from app.report.planner import plan


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    """Point the store at a scratch directory, not the developer's real one."""
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    return tmp_path


@pytest.fixture
def model() -> PMIDataModel:
    xlsx = make_source("tracker.xlsx", SourceFormat.EXCEL, sheet_name="Workplan")
    return PMIDataModel(
        project=PMIProject(project_id="p1", project_name="Project Aurora",
                           reporting_date=date.today()),
        risks=[Risk(risk_id="R1", title="GDPR retention breach", probability=4,
                    impact=5, status=Status.IN_PROGRESS,
                    source_references=[xlsx])],
    )


def _content(model, session_id="s1"):
    return plan(model, Audience.EXECUTIVE, session_id=session_id,
                fingerprint=store.fingerprint(model))


# ================================================================= versioning
def test_nothing_is_stored_until_something_is_planned():
    assert store.load("s1") is None
    assert store.latest_version("s1") == 0
    assert store.versions("s1") == []


def test_each_save_appends_a_version_and_moves_head(model):
    first = store.save(_content(model))
    second = store.save(_content(model))

    assert (first.version, second.version) == (1, 2)
    assert store.latest_version("s1") == 2
    assert store.load("s1").version == 2
    assert store.load("s1", version=1).version == 1


def test_history_is_listed_newest_first_with_head_marked(model):
    store.save(_content(model))
    store.save(_content(model))

    history = store.versions("s1")
    assert [v.version for v in history] == [2, 1]
    assert history[0].is_head and not history[1].is_head


def test_a_revert_appends_rather_than_erasing(model):
    """Someone will ask what the board was actually sent in week 3."""
    v1 = store.save(_content(model))
    store.save(_content(model))

    restored = store.revert("s1", to_version=v1.version)

    assert restored.version == 3, "revert must append, not rewind"
    assert restored.parent_version == 1
    assert restored.provenance.created_by == "revert"
    # The version it replaced is still readable.
    assert store.load("s1", version=2) is not None


def test_reverting_to_a_version_that_does_not_exist_returns_nothing(model):
    store.save(_content(model))
    assert store.revert("s1", to_version=99) is None


def test_unreadable_content_costs_a_replan_not_an_incident(model):
    """A schema change must not 500 the app — and must never touch the analysis,
    which holds the vision calls and cannot be reproduced identically."""
    store.save(_content(model))
    store.content_dir("s1").joinpath("v1.json").write_text("{not json", encoding="utf-8")

    assert store.load("s1", version=1) is None


# ================================================================== staleness
def test_content_planned_from_the_current_analysis_is_fresh(model):
    content = _content(model)
    assert not store.is_stale(content, model)


def test_resolving_a_conflict_makes_the_stored_report_stale(model):
    """The dangerous sequence: plan a report, then resolve a conflict. The
    stored content still states the losing source's figure, and rendering it
    would produce a deck that is confidently wrong."""
    contested = model.model_copy(update={
        "conflicts": [Conflict(check_id="PMI-002", entity_type="kpi",
                               entity_key="Overall Progress", field="value",
                               message="sources disagree")]
    })
    content = plan(contested, Audience.EXECUTIVE,
                   fingerprint=store.fingerprint(contested))
    assert not store.is_stale(content, contested)

    decided = contested.model_copy(deep=True)
    decided.conflicts[0].resolved_value = "82"
    decided.conflicts[0].resolution = "user"

    assert store.is_stale(content, decided), \
        "a resolved conflict must invalidate content planned before it"


def test_new_extraction_makes_the_stored_report_stale(model):
    content = _content(model)
    enlarged = model.model_copy(update={
        "risks": model.risks + [Risk(risk_id="R2", title="Second risk",
                                     probability=1, impact=1)]
    })
    assert store.is_stale(content, enlarged)


def test_a_quality_score_change_makes_the_stored_report_stale(model):
    quality = build_report(model, failed_files=[], warnings=[])
    content = plan(model, Audience.EXECUTIVE, quality=quality,
                   fingerprint=store.fingerprint(model, quality))

    assert not store.is_stale(content, model, quality)
    assert store.is_stale(content, model, None), \
        "losing the quality report changes what the deck may claim"


def test_content_with_no_fingerprint_is_treated_as_stale(model):
    """Content predating this check cannot vouch for itself, so it does not get
    the benefit of the doubt."""
    content = plan(model, Audience.EXECUTIVE)      # no fingerprint passed
    assert content.analysis_fingerprint == ""
    assert store.is_stale(content, model)
