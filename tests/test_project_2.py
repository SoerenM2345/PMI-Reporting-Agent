"""Phase 2 — editable free-text drafts.

Covers the checkpoint contract: a draft is planned from project knowledge as
Markdown; a direct edit mints a version; regenerating one section preserves a
hand-edited section elsewhere and changes only the requested one; versions can be
listed and restored; and a knowledge change flags the draft stale without ever
rewriting it (Scenario 3 + the editable-draft spec).

Keyless: drafts are planned deterministically from the knowledge base.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.project import drafting
from app.project import drafts as drafts_mod
from app.project import facts
from app.project import files as files_mod
from app.project.json_repositories import Repositories
from app.project.rebuild import rebuild

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
PROJECT = "proj_p2"


@pytest.fixture
def knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path / "storage_data")
    repos = Repositories()
    for name in ("milestone_tracker.csv", "integration_tracker.xlsx"):
        src = tmp_path / name
        shutil.copy2(SAMPLES / name, src)
        files_mod.ingest_file(PROJECT, src, repos=repos)
    kb = rebuild(PROJECT, repos=repos, trigger="upload")
    return repos, kb


# ------------------------------------------------------------ create from KB
def test_create_draft_from_knowledge(knowledge):
    repos, _ = knowledge
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)

    assert draft.version == 1
    assert draft.format == "markdown"
    assert draft.sections and draft.content.startswith("# ")
    # Planned deterministically from knowledge — every section names its base.
    assert all(s.based_on_knowledge_version == draft.based_on_knowledge_version
               for s in draft.sections)
    # A milestones section should depend on milestone entities (resolvable deps).
    milestones = next((s for s in draft.sections if "milestone" in s.section_id), None)
    assert milestones is not None and milestones.depends_on.entity_ids


def test_create_requires_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.storage_dir",
                        tmp_path / "storage_data")
    with pytest.raises(drafting.DraftError):
        drafting.create_draft("empty_project", repos=Repositories())


# ------------------------------------------------------- edit mints a version
def test_edit_section_creates_new_version(knowledge):
    repos, _ = knowledge
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)
    section_id = draft.sections[0].section_id

    edited = drafting.edit_section(PROJECT, draft.draft_id, section_id,
                                   "My hand-written summary.", repos=repos)

    assert edited.version == 2
    section = next(s for s in edited.sections if s.section_id == section_id)
    assert section.content == "My hand-written summary."
    assert section.origin == "user"
    assert "My hand-written summary." in edited.content
    # History is intact: v1 still holds the original.
    assert repos.drafts.get_version(PROJECT, draft.draft_id, 1).sections[0].origin \
        == "assistant"


# --------------------------- regenerate one section, preserve edits (Scenario 3)
def test_regenerate_section_preserves_other_edits(knowledge):
    repos, _ = knowledge
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)
    assert len(draft.sections) >= 2
    edited_id, regen_id = draft.sections[0].section_id, draft.sections[1].section_id

    # User edits section 0 by hand.
    drafting.edit_section(PROJECT, draft.draft_id, edited_id,
                          "Hand-written and must survive.", repos=repos)
    # Then asks the agent to regenerate section 1.
    result = drafting.regenerate_section(PROJECT, draft.draft_id, regen_id,
                                         repos=repos)

    edited = next(s for s in result.sections if s.section_id == edited_id)
    regenerated = next(s for s in result.sections if s.section_id == regen_id)
    assert edited.content == "Hand-written and must survive."   # untouched
    assert edited.origin == "user"
    assert regenerated.origin == "assistant"                    # only this changed
    assert result.version == 3


# -------------------------------------------------------- versions + restore
def test_versions_listed_and_restorable(knowledge):
    repos, _ = knowledge
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)
    section_id = draft.sections[0].section_id
    drafting.edit_section(PROJECT, draft.draft_id, section_id, "v2 text", repos=repos)

    versions = repos.drafts.list_versions(PROJECT, draft.draft_id)
    assert [v.version for v in versions] == [1, 2]

    # Restoring v1 appends a new version with v1's content (append-only history).
    restored = drafting.restore_version(PROJECT, draft.draft_id, 1, repos=repos)
    assert restored.version == 3
    assert restored.sections[0].content != "v2 text"
    assert restored.sections[0].origin == "assistant"


# ----------------------------------------- knowledge change flags, never rewrites
def test_knowledge_change_flags_draft_but_keeps_edits(knowledge):
    repos, kb = knowledge
    draft = drafting.create_draft(PROJECT, audience="executive", repos=repos)
    milestones = next(s for s in draft.sections if "milestone" in s.section_id)
    milestone_name = kb.data_model.milestones[0].name
    drafting.edit_section(PROJECT, draft.draft_id, milestones.section_id,
                          "Edited milestones prose.", repos=repos)

    # A correction to a milestone this draft used → knowledge moves.
    facts.record_message(PROJECT, f"{milestone_name} is now 15-09-2026", repos=repos)
    moved = drafts_mod.mark_stale_if_affected(PROJECT, repos=repos)

    assert moved and moved[0].status in ("stale", "potentially_stale")
    # Flagged, never rewritten: the user's edit is exactly as they left it.
    reloaded = repos.drafts.get(PROJECT, draft.draft_id)
    edited = next(s for s in reloaded.sections
                  if s.section_id == milestones.section_id)
    assert edited.content == "Edited milestones prose."


# ------------------------------------------------------------------ REST API
def test_draft_rest_roundtrip(knowledge, monkeypatch):
    # The endpoints use the default repositories, which read the same storage_dir.
    from app import main

    monkeypatch.setattr(main, "_project_or_404", lambda pid: {"project_id": pid})
    client = TestClient(main.app)

    created = client.post(f"/api/projects/{PROJECT}/drafts",
                          json={"audience": "executive"})
    assert created.status_code == 200
    draft_id = created.json()["draft"]["draft_id"]

    section_id = created.json()["draft"]["sections"][0]["section_id"]
    patched = client.patch(f"/api/projects/{PROJECT}/drafts/{draft_id}",
                           json={"section_id": section_id, "text": "edited"})
    assert patched.status_code == 200 and patched.json()["draft"]["version"] == 2

    versions = client.get(
        f"/api/projects/{PROJECT}/drafts/{draft_id}/versions").json()["versions"]
    assert [v["version"] for v in versions] == [1, 2]
