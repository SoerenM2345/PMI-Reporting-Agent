"""Phase 1A — project storage core + deterministic, incremental rebuild.

These cover the checkpoint's contract: extraction is cached by content hash and not
re-run for an unchanged file; a changed file *is* re-extracted; a removed file is
soft-deleted (excluded from rebuild, record kept); knowledge is versioned with a
populated change log; concurrent writes are rejected by the version check; and a
failed extraction stays visible rather than dropping data.

Keyless by design: only CSV/XLSX sample files are used, so nothing here needs a
model (images would require `fake_vision`), matching the suite's no-live-provider rule.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.project import files as files_mod
from app.project import paths
from app.project.json_repositories import Repositories
from app.project.models import ProjectKnowledge
from app.project.rebuild import rebuild
from app.project.repositories import StaleVersionError

PROJECT = "proj_test"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Isolated storage under a temp dir, plus a working copy of two sample files."""
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    work = tmp_path / "incoming"
    work.mkdir()
    samples = Path(__file__).resolve().parents[1] / "data" / "samples"
    for name in ("milestone_tracker.csv", "integration_tracker.xlsx"):
        shutil.copy2(samples / name, work / name)
    return work


@pytest.fixture
def repos():
    return Repositories()


@pytest.fixture
def count_extractions(monkeypatch):
    """Wrap the extractor so a test can assert how many times it actually ran."""
    calls: list[str] = []
    real = files_mod.extract_file

    def counting(path):
        calls.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(files_mod, "extract_file", counting)
    return calls


# --------------------------------------------------------------- basic rebuild
def test_ingest_then_rebuild_creates_v1(store, repos):
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    knowledge = rebuild(PROJECT, repos=repos, trigger="upload")

    assert knowledge.version == 1
    assert knowledge.entity_count() > 0
    assert knowledge.quality_report is not None
    # Persisted where the repository expects it.
    assert paths.knowledge_current_path(PROJECT).is_file()
    assert paths.knowledge_version_path(PROJECT, 1).is_file()

    record = repos.files.get_index(PROJECT)[0]
    assert record.extraction_status == "completed"
    assert record.knowledge_version_added == 1


def test_repeated_rebuild_without_change_keeps_version(store, repos):
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    first = rebuild(PROJECT, repos=repos)
    again = rebuild(PROJECT, repos=repos)
    assert first.version == again.version == 1


# ------------------------------------------- caching does not change the answer
def test_cached_rebuild_matches_fresh_extraction(store, repos):
    """A file read from the record cache must standardize identically to a fresh
    read — otherwise incremental ingestion would silently change results. Uses the
    xlsx, whose date cells are the values most at risk across a JSON round-trip."""
    from app.agent.calculations import recompute_derived
    from app.agent.standardize import standardize
    from app.extractors import extract_file
    from app.project.rebuild import _entity_signatures

    src = store / "integration_tracker.xlsx"
    fresh = standardize(extract_file(src), [src.name])
    fresh, _ = recompute_derived(fresh)

    files_mod.ingest_file(PROJECT, src, repos=repos)
    cached = rebuild(PROJECT, repos=repos).data_model

    assert _entity_signatures(cached) == _entity_signatures(fresh)


# ----------------------------------------------------- incremental extraction
def test_unchanged_file_is_not_reextracted(store, repos, count_extractions):
    src = store / "milestone_tracker.csv"
    files_mod.ingest_file(PROJECT, src, repos=repos)
    files_mod.ingest_file(PROJECT, src, repos=repos)  # identical bytes → cache hit
    assert count_extractions.count("milestone_tracker.csv") == 1


def test_changed_file_is_reextracted(store, repos, count_extractions):
    src = store / "milestone_tracker.csv"
    files_mod.ingest_file(PROJECT, src, repos=repos)
    # Same name, different bytes → a new hash → must re-extract.
    src.write_text(src.read_text() + "\nM99,New milestone,Legal,2026-12-01,Planned\n")
    files_mod.ingest_file(PROJECT, src, repos=repos)
    assert count_extractions.count("milestone_tracker.csv") == 2


def test_added_file_bumps_version_and_records_change(store, repos):
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    v1 = rebuild(PROJECT, repos=repos)

    files_mod.ingest_file(PROJECT, store / "integration_tracker.xlsx", repos=repos)
    v2 = rebuild(PROJECT, repos=repos)

    assert v2.version == 2
    assert v2.entity_count() > v1.entity_count()
    latest = v2.change_log[-1]
    assert "integration_tracker.xlsx" in latest.added_files
    assert latest.added_entities  # the new file contributed entities


# -------------------------------------------------------- soft delete (corr #6)
def test_removed_file_is_excluded_but_record_kept(store, repos):
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    files_mod.ingest_file(PROJECT, store / "integration_tracker.xlsx", repos=repos)
    rebuild(PROJECT, repos=repos)

    removed_id = files_mod.file_id_for("integration_tracker.xlsx")
    files_mod.remove_file(PROJECT, removed_id, repos=repos)
    after = rebuild(PROJECT, repos=repos)

    # Excluded from the rebuilt model...
    assert "integration_tracker.xlsx" not in after.data_model.source_files
    assert after.change_log[-1].removed_files == ["integration_tracker.xlsx"]
    # ...but its record and cached extraction survive (history preserved).
    record = next(r for r in repos.files.get_index(PROJECT) if r.file_id == removed_id)
    assert record.active is False and record.status == "removed"
    assert record.removed_at is not None
    assert repos.files.get_records(PROJECT, removed_id)  # cache not deleted


# -------------------------------------------------- concurrency (correction #8)
def test_stale_version_write_is_rejected(store, repos):
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    rebuild(PROJECT, repos=repos)  # establishes v1 on disk

    # A writer that still thinks the current version is 0 must not be allowed to
    # overwrite v1 or re-mint a version number.
    stale = ProjectKnowledge(project_id=PROJECT)
    with pytest.raises(StaleVersionError):
        repos.knowledge.save_next(stale, expected_current_version=0)


def test_version_files_are_append_only(store, repos):
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    rebuild(PROJECT, repos=repos)
    files_mod.ingest_file(PROJECT, store / "integration_tracker.xlsx", repos=repos)
    rebuild(PROJECT, repos=repos)
    assert paths.knowledge_version_path(PROJECT, 1).is_file()
    assert paths.knowledge_version_path(PROJECT, 2).is_file()


# ------------------------------------------------- failed extraction stays visible
def test_failed_extraction_is_visible_not_dropped(store, repos):
    bad = store / "notes.unsupported"
    bad.write_text("not a supported format")
    record = files_mod.ingest_file(PROJECT, bad, repos=repos)

    assert record.extraction_status == "failed"
    assert record.error
    assert "notes.unsupported" in files_mod.failed_file_names(PROJECT, repos=repos)

    # It reaches the data-quality report rather than silently vanishing.
    files_mod.ingest_file(PROJECT, store / "milestone_tracker.csv", repos=repos)
    knowledge = rebuild(PROJECT, repos=repos)
    assert "notes.unsupported" in knowledge.quality_report.failed_files
