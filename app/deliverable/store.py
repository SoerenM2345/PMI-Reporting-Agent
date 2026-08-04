"""Append-only versioned storage for planned deliverables.

Modelled on `app/report/store.py`, which got this right: versions are never
overwritten, `HEAD` is a pointer, and reverting appends rather than rewinding.
A user who approved v3 and asks to go back to v1 gets a v4 that is a copy of v1,
so the fact that they went back is itself in the history.

Laid out per scope so the two stacks stay independent on disk:

    storage_data/projects/<project_id>/deliverables/{HEAD,v1.json,v2.json,…}
    storage_data/<session_id>/deliverables/{HEAD,v1.json,v2.json,…}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.deliverable.model import Deliverable

log = logging.getLogger("pmi.deliverable.store")

_HEAD = "HEAD"


def _dir(*, project_id: Optional[str] = None,
         session_id: Optional[str] = None) -> Path:
    from app.config import get_settings

    base = Path(get_settings().storage_dir)
    # A project chat carries both ids, but its conversational preview is still
    # a session draft. All preview and revision endpoints load it by session.
    # Project-level builds have no session id and continue to use the project
    # directory below.
    if session_id:
        return base / session_id / "deliverables"
    if project_id:
        return base / "projects" / project_id / "deliverables"
    raise ValueError("a deliverable needs either a project_id or a session_id")


def save(deliverable: Deliverable) -> Deliverable:
    """Append the next version and move HEAD onto it."""
    directory = _dir(project_id=deliverable.project_id,
                     session_id=deliverable.session_id)
    directory.mkdir(parents=True, exist_ok=True)

    deliverable.version = _next_version(directory)
    path = directory / f"v{deliverable.version}.json"
    _atomic_write(path, deliverable.model_dump_json(indent=2))
    _atomic_write(directory / _HEAD, json.dumps({"version": deliverable.version}))

    log.info("stored %s v%d (%d pages)", deliverable.deliverable_id,
             deliverable.version, deliverable.page_count)
    return deliverable


def load(*, project_id: Optional[str] = None, session_id: Optional[str] = None,
         version: Optional[int] = None) -> Optional[Deliverable]:
    directory = _dir(project_id=project_id, session_id=session_id)
    version = version or head(project_id=project_id, session_id=session_id)
    if not version:
        return None
    path = directory / f"v{version}.json"
    if not path.is_file():
        return None
    try:
        deliverable = Deliverable.model_validate_json(
            path.read_text(encoding="utf-8"))
        _upgrade_legacy_cover(deliverable)
        return deliverable
    except Exception as exc:                                   # noqa: BLE001
        # A stored version that no longer validates is a schema change, not a
        # crash: re-planning is always available, so return None and let the
        # caller do that rather than 500 on a stale file.
        log.warning("could not read %s (%s); treating as absent", path, exc)
        return None


def _upgrade_legacy_cover(deliverable: Deliverable) -> None:
    """Repair cover bindings saved before the plain-logo/title-placeholder fix.

    Stored deliverables are the source of truth, but layout names and bindings
    are renderer metadata rather than user-authored copy. Updating them in
    memory lets an existing chat generate the corrected deck immediately,
    without forcing a re-plan that could disturb the user's accepted content.
    """
    cover = next((page for page in deliverable.pages
                  if page.purpose == "cover"), None)
    if cover is None:
        return

    if "tagline logo lockup" in cover.layout_name.casefold():
        from app.templates import template_registry

        choice = template_registry.default().catalog.choose(purpose="cover")
        cover.layout_id = choice.layout.layout_id
        cover.layout_name = choice.layout.raw_name.strip()

    generic_titles = {
        " ".join((deliverable.title or "").casefold().split()),
        " ".join((deliverable.subtitle or "").casefold().split()),
    }
    current = " ".join((cover.title or "").casefold().split())
    governing = " ".join((deliverable.governing_message or "").split())
    if (current in generic_titles and governing.casefold().startswith("status of ")
            and len(governing) <= 80):
        cover.title = governing
        if " ".join((cover.subtitle or "").casefold().split()) \
                == governing.casefold():
            cover.subtitle = ""


def head(*, project_id: Optional[str] = None,
         session_id: Optional[str] = None) -> Optional[int]:
    path = _dir(project_id=project_id, session_id=session_id) / _HEAD
    if not path.is_file():
        return None
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["version"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def versions(*, project_id: Optional[str] = None,
             session_id: Optional[str] = None) -> list[int]:
    directory = _dir(project_id=project_id, session_id=session_id)
    if not directory.is_dir():
        return []
    found = []
    for path in directory.glob("v*.json"):
        try:
            found.append(int(path.stem[1:]))
        except ValueError:
            continue
    return sorted(found)


def revert(*, project_id: Optional[str] = None,
           session_id: Optional[str] = None,
           version: int) -> Optional[Deliverable]:
    """Append a copy of `version` as the new head. History is never rewound."""
    source = load(project_id=project_id, session_id=session_id, version=version)
    if source is None:
        return None
    source.parent_version = version
    source.notes.append(f"Reverted to version {version}.")
    return save(source)


def _next_version(directory: Path) -> int:
    existing = [int(p.stem[1:]) for p in directory.glob("v*.json")
                if p.stem[1:].isdigit()]
    return (max(existing) + 1) if existing else 1


def _atomic_write(path: Path, text: str) -> None:
    import os

    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
