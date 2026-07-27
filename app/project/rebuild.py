"""The incremental knowledge engine: active records → a new knowledge version.

This is the "holistic re-derivation" half of the design. Extraction is cached per
file (`files.py`); everything downstream of it is cheap and deterministic, so a
rebuild re-runs the *whole* tail over the union of active records rather than trying
to patch entities in place. That is what keeps cross-source matching and conflict
detection correct: a new Finance file can create a conflict with a milestone that
was extracted last week, and only a re-run over both sees it.

The tail reused here is exactly `agent/graph.py`'s analysis nodes *minus extract*:

    standardize → recompute_derived → run_checks → resolve_conflicts → build_report

Two invariants are enforced around it:

* **User decisions survive a rebuild.** Conflict resolutions the user already made
  are replayed onto the freshly derived conflicts, so re-reading the files never
  silently re-opens a settled question (§9, and CLAUDE.md's stored-content rule).
* **Writes are atomic and version-checked.** The rebuild runs under the project
  lock and hands `save_next` the version it read, so two concurrent rebuilds cannot
  mint the same version or clobber each other (correction #8).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from app.agent.calculations import recompute_derived
from app.agent.consistency import apply_resolutions, resolve_conflicts, run_checks
from app.agent.data_quality import build_report
from app.agent.standardize import standardize
from app.models.pmi import PMIDataModel, PMIProject
from app.project import files as files_mod
from app.project import paths
from app.project.json_repositories import Repositories, default_repositories
from app.project.locks import project_lock
from app.project.models import (
    Assumption,
    ChangeLogEntry,
    ConfirmedFact,
    OpenQuestion,
    ProjectKnowledge,
    UserDecision,
    _now,
)

log = logging.getLogger("pmi.project.rebuild")

# Entity collections to diff for the change log, as (kind, list-attribute). The
# label is discovered per entity from the first present of the attrs below, so this
# does not need to know each entity's label field.
_ENTITY_KINDS = [
    ("workstream", "workstreams"), ("task", "tasks"), ("milestone", "milestones"),
    ("risk", "risks"), ("issue", "issues"), ("dependency", "dependencies"),
    ("decision", "decisions"), ("budget", "budget"), ("synergy", "synergies"),
    ("kpi", "kpis"), ("meeting", "meetings"), ("status_update", "status_updates"),
]
_LABEL_ATTRS = ("name", "title", "description", "category")


def rebuild(project_id: str, *, repos: Optional[Repositories] = None,
            trigger: str = "",
            add_decisions: Optional[list[UserDecision]] = None,
            add_facts: Optional[list[ConfirmedFact]] = None,
            add_questions: Optional[list[OpenQuestion]] = None,
            add_assumptions: Optional[list[Assumption]] = None,
            set_project_fields: Optional[dict[str, str]] = None) -> ProjectKnowledge:
    """Re-derive canonical knowledge from the active source set and persist it.

    Runs under the project lock; returns the newly written `ProjectKnowledge`.

    The `add_*` / `set_project_fields` arguments let a caller fold a knowledge
    change into the *same* version write as the re-derivation, so applying a
    correction is one atomic step rather than "mutate metadata, then rebuild"
    (which would mint two versions and leave a window where the two disagree).
    Confirmed-value decisions — new ones passed here and prior ones carried
    forward — are re-applied onto the freshly standardized model before anything
    is derived from it, so a rebuild never reverts a correction the user made.
    """
    repos = repos or default_repositories()
    add_decisions = add_decisions or []
    add_facts = add_facts or []
    add_questions = add_questions or []
    add_assumptions = add_assumptions or []

    with project_lock(paths.lock_path(project_id)):
        prev = repos.knowledge.current(project_id)
        expected = prev.version if prev else 0

        # Merge carried-forward metadata with this call's additions.
        decisions = [*(prev.user_decisions if prev else []), *add_decisions]
        facts = [*(prev.confirmed_user_facts if prev else []), *add_facts]
        questions = [*(prev.open_questions if prev else []), *add_questions]
        assumptions = [*(prev.assumptions if prev else []), *add_assumptions]

        records, source_files = files_mod.collect_active(project_id, repos=repos)
        project = _project_header(project_id, prev, source_files)
        _apply_project_fields(project, set_project_fields or {})

        model = standardize(records, source_files, project=project)
        # Confirmed user corrections win over what the files said, and must be put
        # back before deriving anything — overdue flags, delays and variances all
        # depend on the corrected value, not the stale one from the file.
        _apply_confirmed_values(model, decisions)

        model, derived_issues = recompute_derived(model, project.reporting_date)
        model.validation_issues.extend(derived_issues)

        results = run_checks(model)
        model.conflicts = results.conflicts
        model.validation_issues.extend(results.issues)

        # Replay conflict decisions the user already made, so a re-read cannot
        # re-open them.
        model.conflicts = resolve_conflicts(
            model.conflicts,
            user_choices=_prior_conflict_choices_from(decisions),
            priority_override=project.source_priority,
        )
        model = apply_resolutions(model)

        report = build_report(
            model,
            failed_files=files_mod.failed_file_names(project_id, repos=repos),
            warnings=model.warnings,
        )

        new_version = expected + 1
        change = _change_log_entry(prev, model, source_files, new_version, trigger)
        has_additions = bool(add_decisions or add_facts or add_questions
                             or add_assumptions or set_project_fields)

        # A rebuild that changed no entity *and* added no metadata does not mint a
        # new version — the version number stays a meaningful record of when
        # knowledge actually moved. A metadata-only change (an assumption, a
        # flagged open question) still writes, or it would be lost. The first
        # rebuild always establishes v1.
        if prev is not None and change.is_empty and not has_additions:
            log.info("project %s rebuild: no change, staying at v%d",
                     project_id, prev.version)
            return prev

        knowledge = ProjectKnowledge(
            project_id=project_id,
            data_model=model,
            quality_report=report,
            confirmed_user_facts=facts,
            assumptions=assumptions,
            open_questions=questions,
            user_decisions=decisions,
            source_index=_source_index(project_id, repos),
            change_log=([*prev.change_log, change] if prev else [change]),
            updated_at=_now(),
        )

        saved = repos.knowledge.save_next(knowledge, expected_current_version=expected)

    _stamp_versions(project_id, saved.version, repos)
    return saved


# ------------------------------------------------------------------ helpers
def _project_header(project_id: str, prev: Optional[ProjectKnowledge],
                    source_files: list[str]) -> PMIProject:
    """Reuse the prior project header so user-set §4 facts (reporting date, source
    priority) survive a rebuild; only the source-file list is refreshed."""
    if prev is not None and prev.data_model.project is not None:
        header = prev.data_model.project.model_copy(deep=True)
        header.source_files = source_files
        return header
    return PMIProject(project_id=project_id, source_files=source_files)


def _prior_conflict_choices_from(decisions: list[UserDecision]) -> dict[str, Any]:
    """`{conflict_id: chosen source | {"value": ...}}` from stored user decisions,
    so a re-read honours the resolutions the user already made (§9)."""
    choices: dict[str, Any] = {}
    for decision in decisions:
        if decision.kind != "conflict_resolution":
            continue
        conflict_id = decision.detail.get("conflict_id")
        if conflict_id is not None and "choice" in decision.detail:
            choices[conflict_id] = decision.detail["choice"]
    return choices


def _apply_project_fields(project: PMIProject, fields: dict[str, str]) -> None:
    """Write user-confirmed project-header fields (reporting date, Day 1, …).

    Coerced through the corrections engine so one parser owns dates, and kept on
    the header so `_project_header` carries them into every later rebuild.
    """
    from app.agent.corrections import _coerce

    for field, raw in fields.items():
        if field not in type(project).model_fields:
            log.warning("ignoring unknown project field %r", field)
            continue
        try:
            setattr(project, field, _coerce(project, field, raw))
        except (ValueError, TypeError) as exc:
            log.warning("could not set project field %s=%r: %s", field, raw, exc)


def _apply_confirmed_values(model: PMIDataModel,
                            decisions: list[UserDecision]) -> None:
    """Re-apply confirmed entity corrections onto a freshly standardized model.

    Entities are matched by `(type, label)`, not the positional id, because ids
    are reassigned on every standardize. The stored `raw` is re-coerced against
    the live field type each time, so a value written before a schema tweak still
    lands validated (the `TypeAdapter` discipline from `corrections._coerce`).
    """
    from app.agent.corrections import _coerce

    for decision in decisions:
        if decision.kind != "confirmed_value":
            continue
        detail = decision.detail
        entity = _find_entity(model, detail.get("entity_type"),
                              detail.get("entity_label"))
        field, raw = detail.get("field"), detail.get("raw")
        if entity is None or not field or raw is None:
            continue
        if field not in type(entity).model_fields:
            continue
        try:
            setattr(entity, field, _coerce(entity, field, str(raw)))
        except (ValueError, TypeError) as exc:
            log.warning("could not re-apply %s.%s=%r: %s",
                        detail.get("entity_type"), field, raw, exc)


def _find_entity(model: PMIDataModel, entity_type: Optional[str],
                 label: Optional[str]):
    from app.agent.nl_updates import LABELS

    entry = LABELS.get(entity_type or "")
    if entry is None or not label:
        return None
    coll, _id_attr, label_attr = entry
    return next((e for e in getattr(model, coll, []) or []
                 if str(getattr(e, label_attr, "")) == label), None)


def _entity_signatures(model: PMIDataModel) -> dict[str, str]:
    """`{entity_key: content_hash}` for change detection.

    Keyed by *content identity* (`kind:label`), never the positional `*_id`, because
    those ids shift when the file order changes and would flag every entity as
    changed. The hash likewise drops `*_id` and `source_references` so that a purely
    positional or provenance-only change is not reported as a content change.
    """
    signatures: dict[str, str] = {}
    for kind, attr in _ENTITY_KINDS:
        for i, entity in enumerate(getattr(model, attr, [])):
            label = next((getattr(entity, a) for a in _LABEL_ATTRS
                          if getattr(entity, a, None)), None)
            key = f"{kind}:{label}" if label else f"{kind}#{i}"
            dumped = entity.model_dump(mode="json")
            salient = {k: v for k, v in dumped.items()
                       if not k.endswith("_id") and k != "source_references"}
            signatures[key] = hashlib.sha1(
                json.dumps(salient, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
    return signatures


def _change_log_entry(prev: Optional[ProjectKnowledge], model: PMIDataModel,
                      source_files: list[str], version: int,
                      trigger: str) -> ChangeLogEntry:
    old_sig = _entity_signatures(prev.data_model) if prev else {}
    new_sig = _entity_signatures(model)
    old_keys, new_keys = set(old_sig), set(new_sig)

    old_files = set(prev.data_model.source_files) if prev else set()
    new_files = set(source_files)

    return ChangeLogEntry(
        version=version,
        trigger=trigger,
        added_entities=sorted(new_keys - old_keys),
        removed_entities=sorted(old_keys - new_keys),
        changed_entities=sorted(
            k for k in old_keys & new_keys if old_sig[k] != new_sig[k]),
        added_files=sorted(new_files - old_files),
        removed_files=sorted(old_files - new_files),
    )


def _source_index(project_id: str, repos: Repositories) -> list[dict]:
    """One row per file in the index — active and removed — for provenance."""
    return [
        {"kind": "file", "file_id": r.file_id, "file_name": r.file_name,
         "active": r.active, "status": r.status,
         "extraction_status": r.extraction_status, "record_count": r.record_count}
        for r in repos.files.get_index(project_id)
    ]


def _stamp_versions(project_id: str, version: int, repos: Repositories) -> None:
    """Record which version each active file first contributed to.

    Done after the successful write so a file is never attributed to a version that
    did not get persisted. Only stamps records that have not been stamped before.
    """
    index = repos.files.get_index(project_id)
    changed = False
    for record in index:
        if (record.active and record.extraction_status == "completed"
                and record.knowledge_version_added is None):
            record.knowledge_version_added = version
            changed = True
    if changed:
        repos.files.save_index(project_id, index)
