"""Stale-draft detection by dependency (correction #7).

A draft is built from a particular knowledge version. When knowledge moves, some
drafts are affected and some are not, and the spec is emphatic that the system
must *flag* the affected ones without ever rewriting them — a draft carrying a
user's edits must never be silently replaced.

Precision comes from tracking what each section depended on, not merely which
version it was built at. The change log names the entities and files that moved
between versions; a section is stale when its resolvable dependencies intersect
that set. Two dependency kinds — `fact_ids` and `calculation_ids` — cannot be
resolved against an entity-level change log, so a section that declares them is
handled conservatively: if anything changed at all, the draft is marked
**potentially** stale rather than left looking current. Same for a draft that
declares no dependencies: we cannot prove it safe, so we do not.

`mark_stale_if_affected` only ever moves a draft *towards* stale and only touches
its `status`/section `stale` flags — never its content.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.project.json_repositories import Repositories, default_repositories
from app.project.models import DraftRecord, ProjectKnowledge

log = logging.getLogger("pmi.project.drafts")


def changes_since(knowledge: ProjectKnowledge,
                  base_version: int) -> tuple[set[str], set[str]]:
    """`(changed_entity_keys, changed_file_names)` accumulated after `base_version`.

    Unions every change-log entry newer than the draft's base, so a draft two
    versions behind sees the combined effect, not just the latest step.
    """
    entities: set[str] = set()
    files: set[str] = set()
    for entry in knowledge.change_log:
        if entry.version <= base_version:
            continue
        entities |= set(entry.added_entities)
        entities |= set(entry.removed_entities)
        entities |= set(entry.changed_entities)
        files |= set(entry.added_files)
        files |= set(entry.removed_files)
    return entities, files


def evaluate(draft: DraftRecord, knowledge: ProjectKnowledge) -> DraftRecord:
    """Return `draft` with its status/section flags updated for `knowledge`.

    Staleness is judged **per section**, against each section's own
    `based_on_knowledge_version`: regenerating one section refreshes only its base,
    so an untouched section keeps its verdict. Pure and idempotent — it reads the
    change log and rewrites only flags, safe to run on every knowledge bump.
    """
    resolvable_hit = False
    uncertain = False

    for section in draft.sections:
        if section.based_on_knowledge_version >= knowledge.version:
            continue  # section is current — nothing to check

        changed_entities, changed_files = changes_since(
            knowledge, section.based_on_knowledge_version)
        if not changed_entities and not changed_files:
            continue  # a metadata-only bump cannot stale content

        deps = section.depends_on
        hit = (set(deps.entity_ids) & changed_entities) or \
              (set(deps.source_ids) & changed_files)
        if hit:
            section.stale = True
            resolvable_hit = True
        # Fact/calculation dependencies can't be checked against an entity-level
        # change log; if anything moved, we cannot rule this section out.
        if not deps.only_resolvable:
            uncertain = True
        # A section that declared nothing at all cannot be proven safe either.
        if deps.is_empty:
            uncertain = True

    if resolvable_hit:
        draft.status = "stale"
    elif uncertain:
        # A section leaned on something we cannot resolve (or declared nothing) —
        # conservatively flag the whole draft rather than leave content looking
        # current (correction #7).
        draft.status = "potentially_stale"
    # else: every checked section was resolvable and unaffected → genuinely current.
    return draft


def mark_stale_if_affected(project_id: str, *,
                           repos: Optional[Repositories] = None) -> list[DraftRecord]:
    """Evaluate every draft against current knowledge, persisting any that changed.

    Returns the drafts whose status moved, for the caller to tell the user about
    ("new project information is available; want me to update this section?").
    """
    repos = repos or default_repositories()
    knowledge = repos.knowledge.current(project_id)
    if knowledge is None:
        return []

    moved: list[DraftRecord] = []
    for draft in repos.drafts.list(project_id):
        before = draft.status
        stale_before = [s.stale for s in draft.sections]
        evaluate(draft, knowledge)
        if draft.status != before or [s.stale for s in draft.sections] != stale_before:
            repos.drafts.save(draft)
            moved.append(draft)
            log.info("draft %s: %s -> %s (knowledge v%d)", draft.draft_id,
                     before, draft.status, knowledge.version)
    return moved
