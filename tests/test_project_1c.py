"""Phase 1C — stale-draft dependency tracking, migration, concurrency, acceptance.

Covers: dependency-based staleness (a draft is flagged only when a change touches
what it used, with a conservative whole-draft fallback when dependencies cannot be
resolved); per-orphan-session migration that copies before deleting and is
idempotent; concurrent rebuilds that never duplicate a version; and the S1
acceptance path (a new file after a draft flags the draft).
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

from app.project import drafts as drafts_mod
from app.project import facts
from app.project import files as files_mod
from app.project import migrate as migrate_mod
from app.project import paths
from app.project.json_repositories import Repositories
from app.project.models import (
    Assumption,
    Dependencies,
    DraftRecord,
    DraftSection,
)
from app.project.rebuild import rebuild

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    return tmp_path


def _seed(project_id, tmp_path, repos, name="milestone_tracker.csv"):
    src = tmp_path / name
    shutil.copy2(SAMPLES / name, src)
    files_mod.ingest_file(project_id, src, repos=repos)
    return rebuild(project_id, repos=repos, trigger="upload")


def _draft(project_id, version, sections):
    return DraftRecord(draft_id="d1", project_id=project_id,
                       based_on_knowledge_version=version, sections=sections)


# ------------------------------------------------------ stale-draft tracking (#7)
def test_draft_staled_only_when_a_dependency_changes(isolated):
    repos = Repositories()
    v1 = _seed("proj", isolated, repos)
    name = v1.data_model.milestones[0].name
    key = f"milestone:{name}"

    # A draft whose one section depends on that milestone.
    repos.drafts.save(_draft("proj", 1, [
        DraftSection(section_id="s1", depends_on=Dependencies(entity_ids=[key]))]))

    # Correct that milestone → v2 changes it.
    facts.record_message("proj", f"{name} is now 15-09-2026", repos=repos)
    moved = drafts_mod.mark_stale_if_affected("proj", repos=repos)

    assert [d.draft_id for d in moved] == ["d1"]
    reloaded = repos.drafts.get("proj", "d1")
    assert reloaded.status == "stale"
    assert reloaded.sections[0].stale is True


def test_draft_not_staled_by_unrelated_change(isolated):
    repos = Repositories()
    v1 = _seed("proj", isolated, repos)
    name = v1.data_model.milestones[0].name

    # Depends on something the change will not touch.
    repos.drafts.save(_draft("proj", 1, [
        DraftSection(section_id="s1",
                     depends_on=Dependencies(entity_ids=["milestone:__other__"]))]))

    facts.record_message("proj", f"{name} is now 15-09-2026", repos=repos)
    drafts_mod.mark_stale_if_affected("proj", repos=repos)

    assert repos.drafts.get("proj", "d1").status == "draft"  # genuinely unaffected


def test_unresolvable_dependency_marks_whole_draft_potentially_stale(isolated):
    repos = Repositories()
    v1 = _seed("proj", isolated, repos)
    name = v1.data_model.milestones[0].name

    # A calculation dependency can't be checked against an entity change log.
    repos.drafts.save(_draft("proj", 1, [
        DraftSection(section_id="s1",
                     depends_on=Dependencies(calculation_ids=["overall_completion"]))]))

    facts.record_message("proj", f"{name} is now 15-09-2026", repos=repos)
    drafts_mod.mark_stale_if_affected("proj", repos=repos)

    assert repos.drafts.get("proj", "d1").status == "potentially_stale"


def test_draft_without_dependencies_is_potentially_stale(isolated):
    repos = Repositories()
    v1 = _seed("proj", isolated, repos)
    name = v1.data_model.milestones[0].name
    repos.drafts.save(_draft("proj", 1, [DraftSection(section_id="s1")]))

    facts.record_message("proj", f"{name} is now 15-09-2026", repos=repos)
    drafts_mod.mark_stale_if_affected("proj", repos=repos)

    assert repos.drafts.get("proj", "d1").status == "potentially_stale"


def test_metadata_only_bump_does_not_stale_a_draft(isolated):
    repos = Repositories()
    _seed("proj", isolated, repos)
    repos.drafts.save(_draft("proj", 1, [
        DraftSection(section_id="s1",
                     depends_on=Dependencies(entity_ids=["milestone:__x__"]))]))

    # An assumption bumps the version but changes no entity or file.
    rebuild("proj", repos=repos, trigger="assumption",
            add_assumptions=[Assumption(assumption_id="a1", text="month-end")])
    drafts_mod.mark_stale_if_affected("proj", repos=repos)

    assert repos.drafts.get("proj", "d1").status == "draft"


# --------------------------------------------------- acceptance S1: new file flags
def test_new_file_after_draft_flags_it(isolated):
    repos = Repositories()
    _seed("proj", isolated, repos)
    # A draft that leans on an overall figure (unresolvable → conservative flag).
    repos.drafts.save(_draft("proj", 1, [
        DraftSection(section_id="summary",
                     depends_on=Dependencies(calculation_ids=["overall_progress"]))]))

    # Upload a second file → knowledge moves.
    extra = isolated / "integration_tracker.xlsx"
    shutil.copy2(SAMPLES / "integration_tracker.xlsx", extra)
    files_mod.ingest_file("proj", extra, repos=repos)
    rebuild("proj", repos=repos, trigger="upload")

    moved = drafts_mod.mark_stale_if_affected("proj", repos=repos)
    assert moved and repos.drafts.get("proj", "d1").status in (
        "stale", "potentially_stale")


# ------------------------------------------------------------ migration (#9)
def test_migrate_orphan_session_creates_one_project(isolated):
    from app.agent import knowledge as sess_knowledge
    from app.storage import chat_store, json_store

    repos = Repositories()
    session_id = json_store.new_session()
    shutil.copy2(SAMPLES / "milestone_tracker.csv",
                 json_store.uploads_dir(session_id) / "milestone_tracker.csv")
    # A project-level fact the user set in the old session.
    kb = sess_knowledge.load(session_id)
    kb.record_project_field("reporting_date", "2026-06-30")
    sess_knowledge.save(kb)
    chat = chat_store.create_chat(session_id, "Factory Merge")  # orphan (no project)

    report = migrate_mod.migrate_all(repos=repos)

    assert len(report.projects_created) == 1
    project_id = report.projects_created[0]
    assert session_id in report.sessions_migrated
    # The chat is now filed under the new project.
    assert chat_store.get_chat(chat.chat_id).project_id == project_id
    # Knowledge was derived, and the user's project fact was applied.
    knowledge = repos.knowledge.current(project_id)
    assert knowledge is not None and knowledge.data_model.milestones
    assert knowledge.data_model.project.reporting_date.isoformat() == "2026-06-30"
    # Copy-before-delete: the original session survives.
    assert json_store.session_dir(session_id).is_dir()


def test_migration_is_idempotent(isolated):
    from app.storage import chat_store, json_store

    repos = Repositories()
    session_id = json_store.new_session()
    shutil.copy2(SAMPLES / "milestone_tracker.csv",
                 json_store.uploads_dir(session_id) / "milestone_tracker.csv")
    chat_store.create_chat(session_id, "Deal Y")

    first = migrate_mod.migrate_all(repos=repos)
    second = migrate_mod.migrate_all(repos=repos)

    assert session_id in first.sessions_migrated
    assert second.projects_created == []          # no duplicate project
    assert session_id in second.sessions_skipped  # already absorbed


# ------------------------------------------------- concurrency / atomicity (#8)
def test_concurrent_rebuilds_do_not_duplicate_versions(isolated):
    repos = Repositories()
    _seed("proj", isolated, repos)  # establishes v1

    errors: list[Exception] = []

    def worker(n: int):
        try:
            rebuild("proj", repos=repos, trigger=f"t{n}",
                    add_assumptions=[Assumption(assumption_id=f"a{n}", text=str(n))])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    # v1 (seed) + 5 concurrent writes, each a distinct, gapless version.
    versions = sorted(int(p.stem[1:])
                      for p in paths.knowledge_versions_dir("proj").glob("v*.json"))
    assert versions == [1, 2, 3, 4, 5, 6]
    assert repos.knowledge.current_version("proj") == 6
