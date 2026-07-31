"""One way to read the files, for every caller.

`main.analyze` and `conversation._analyse` each built a `SessionAnalysis` from
`run_analysis`, and each did it slightly differently — one set `needs_audience`
and the other did not, one knew about `audience_label` and the other did not,
and only the chat path knew that an analysis is valid only for the file set it
was built from. Two constructors for one object is two answers to "what did we
read", and the one you got depended on which endpoint you came in through.

The file-set check lives here for that reason. Uploading more files mid-session
used to change nothing — the API re-analysed only when asked, and the chat only
when there was *no* analysis — so the report stayed built from the original
files while looking current. That is the worst state this system can be in, and
it must not be possible to reintroduce it by adding a third caller.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.models.pmi import Audience
from app.storage import json_store
from app.storage.json_store import SessionAnalysis

log = logging.getLogger("pmi.agent.analysis")


def covers(analysis: Optional[SessionAnalysis], uploaded: list[str]) -> bool:
    """Was this analysis produced from exactly the files that are here now?"""
    if analysis is None:
        return False
    return sorted(analysis.data_model.source_files) == sorted(uploaded)


def uploaded_files(session_id: str) -> list[str]:
    """The file names currently in the session, however `meta` stored them."""
    meta = json_store.load_meta(session_id) or {}
    names = [
        f if isinstance(f, str) else (f.get("name") or "")
        for f in meta.get("files", [])
    ]
    return sorted(name for name in names if name)


def ensure_analysis(
    session_id: str,
    *,
    request_text: str = "",
    audience: Optional[Audience] = None,
    audience_label: str = "",
    conflict_strategy: Optional[str] = None,
    user_conflict_choices: Optional[dict] = None,
    force: bool = False,
) -> tuple[Optional[SessionAnalysis], bool]:
    """`(analysis, needs_audience)`.

    Returns the stored analysis untouched when it already covers exactly the
    files present — re-extracting would re-pay for the §5.6 vision calls and
    re-roll what the model read out of each screenshot, so the answer could
    change under the user between one turn and the next.

    `needs_audience` is §4: extraction stopped because the audience could not be
    inferred, and guessing would quietly undo a deliberate design decision.
    """
    from app.agent import knowledge
    from app.agent.graph import run_analysis

    existing = json_store.load_analysis(session_id)
    files = uploaded_files(session_id)

    if not force and covers(existing, files):
        return existing, False

    kb = knowledge.load(session_id)
    # What the user has already told us survives a re-read. Asking "who is this
    # for?" again — after they answered two turns ago and only added a file
    # since — is the agent forgetting, not the agent being careful.
    chosen = audience or kb.audience or (existing.audience if existing else None)
    label = (audience_label or kb.audience_label
             or (existing.audience_label if existing else ""))
    text = request_text or (existing.request_text if existing else "")

    result = run_analysis({
        "session_id": session_id,
        "file_paths": [str(json_store.uploads_dir(session_id) / name)
                       for name in files],
        "request_text": text,
        "audience": chosen,
        "project": json_store.load_project(session_id),
        "conflict_strategy": conflict_strategy,
        "user_conflict_choices": user_conflict_choices or {},
    })

    if result.get("needs_audience"):
        return None, True

    model = result["data_model"]
    # Re-extraction builds a brand-new model from the files, so anything the
    # user corrected is back to whatever the file said unless it is put back.
    # See `replay_user_values` — this is the single most consequential line in
    # this function.
    replayed = replay_user_values(model, kb, reporting_date=_reporting_date(model))

    analysis = SessionAnalysis(
        session_id=session_id,
        request_text=text,
        output_type=result.get("output_type", "powerpoint"),
        topic=result.get("topic", "status"),
        audience=result.get("audience"),
        audience_label=label,
        needs_audience=False,
        data_model=model,
        quality_report=result.get("quality_report"),
        errors=result.get("errors", []),
        warnings=result.get("warnings", []),
    )
    if replayed:
        analysis.warnings = [*analysis.warnings,
                             f"Re-applied {len(replayed)} value(s) you supplied "
                             f"earlier, over what the files say."]
    json_store.save_analysis(analysis)

    # Remember the audience that was settled, so a later turn — or a later
    # upload, which re-runs this — never asks about it again.
    if analysis.audience is not None and kb.audience != analysis.audience:
        knowledge.save(kb.set_audience(analysis.audience, label))

    log.info("analysed %s: %d entities from %d file(s)", session_id,
             analysis.data_model.entity_count(), len(files))
    return analysis, False


def replay_user_values(model, kb, *, reporting_date=None) -> list[str]:
    """Put the user's corrections back after a re-read. Returns what landed.

    The bug this exists for: `covers()` is false the moment one new file
    appears, so an upload forces `force=True` and `standardize` builds a fresh
    `PMIDataModel` straight from the extractors. Nothing replayed
    `kb.user_values`, so correcting a milestone date and then uploading a file
    silently reverted the date — and the report looked current while stating a
    figure the user had personally overruled.

    Project-header corrections already survived, because the stored `PMIProject`
    is passed into the graph. Entity corrections had no such path.

    Matching is by `(type, label)`, never by `entity_id`: **ids are reassigned by
    every standardize**, which is why the project stack's
    `rebuild._apply_confirmed_values` uses the same rule. The stored `raw` is
    re-coerced against the live field each time, so a value written before a
    schema change still lands validated.
    """
    from app.agent.calculations import recompute_derived
    from app.agent.corrections import _coerce
    from app.agent.nl_updates import LABELS

    applied: list[str] = []
    for supplied in getattr(kb, "user_values", []) or []:
        entry = LABELS.get(supplied.entity_type or "")
        if entry is None or not supplied.field:
            continue
        collection, _id_attr, label_attr = entry
        entity = next(
            (e for e in getattr(model, collection, []) or []
             if str(getattr(e, label_attr, "")) == (supplied.label or "")),
            None)
        if entity is None or supplied.field not in type(entity).model_fields:
            continue
        raw = supplied.raw or _text_of(supplied.value)
        if not raw:
            continue
        try:
            setattr(entity, supplied.field, _coerce(entity, supplied.field, raw))
        except (ValueError, TypeError) as exc:                 # noqa: PERF203
            log.warning("could not re-apply %s.%s=%r: %s",
                        supplied.entity_type, supplied.field, raw, exc)
            continue
        applied.append(f"{supplied.label or supplied.entity_type}.{supplied.field}")

    if applied:
        # Overdue flags, delays and variances are all computed *from* the values
        # just restored, so leaving them derived from the file's figures would
        # produce a model that disagrees with itself.
        note = "value(s) supplied by the user were re-applied after re-reading"
        if note not in model.notes:
            model.notes.append(note)
        recompute_derived(model, reporting_date)
        log.info("re-applied %d user value(s) after re-extraction: %s",
                 len(applied), ", ".join(applied[:5]))
    return applied


def _reporting_date(model):
    return getattr(getattr(model, "project", None), "reporting_date", None)


def _text_of(value) -> str:
    from datetime import date as _date

    if value is None:
        return ""
    if isinstance(value, _date):
        return f"{value:%d-%m-%Y}"
    return str(value)


def added_files(analysis: Optional[SessionAnalysis], uploaded: list[str]) -> list[str]:
    known = set(analysis.data_model.source_files) if analysis else set()
    return [name for name in uploaded if name not in known]


def file_paths(session_id: str) -> list[str]:
    return [str(json_store.uploads_dir(session_id) / name)
            for name in uploaded_files(session_id)]


def name_of(path: str) -> str:
    return Path(path).name
