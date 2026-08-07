"""Column-level revision operations (exclude/restore).

Separated from revise.py to avoid smart-quote conflicts in the main file.
These handlers follow the same pattern as _exclude_rows/_restore_rows.
"""
from typing import TYPE_CHECKING, Optional

from app.deliverable.model import Deliverable, PageDesign, TableElement

if TYPE_CHECKING:
    from app.deliverable.revise import PageOp


class _Refused(Exception):
    """This op will not be applied."""


def _match_column(wanted: str, spec) -> Optional[int]:
    """The column the instruction meant, or None. Matched against the column header."""
    from app.deliverable.revise import _mentions, _squash

    needle = _squash(wanted)
    if len(needle) < 3:
        return None
    for index, column in enumerate(spec.columns):
        if _mentions(needle, _squash(column.header)):
            return index
    return None


def _find(draft: Deliverable, op: "PageOp") -> PageDesign:
    """Locate the page this op targets."""
    if not op.page_id:
        raise _Refused("no page named")
    page = draft.page(op.page_id)
    if page is None:
        raise _Refused(f"no page {op.page_id!r} in this document")
    return page


def _label(page: PageDesign) -> str:
    """Human-readable page label."""
    return page.title or page.page_id


def _table_specs(draft: Deliverable, page: PageDesign) -> list:
    """Specs for all tables on this page."""
    specs = [draft.specs.tables.get(element.spec_id) for element in page.elements
             if isinstance(element, TableElement)]
    return [spec for spec in specs if spec is not None]


def _restate_notes(spec) -> None:
    """Keep the table's own notes true after edits. Called from revise.py."""
    from app.deliverable.revise import _restate_notes as restate
    restate(spec)


def exclude_columns(draft: Deliverable, op: "PageOp", _corpus) -> tuple[str, str]:
    """Leave named columns out of a page's table.

    Returns (reply_to_user, note_for_document).
    """
    from app.deliverable.revise import _mentions, _squash

    page = _find(draft, op)
    if not op.columns:
        raise _Refused("exclude_columns needs the column(s) to leave out")
    specs = _table_specs(draft, page)
    if not specs:
        raise _Refused(f'"{_label(page)}" has no table')

    removed: list[str] = []
    unmatched: list[str] = []
    for wanted in op.columns:
        for spec in specs:
            index = _match_column(wanted, spec)
            if index is not None:
                removed.append(spec.exclude_column(index).header or wanted)
                break
        else:
            unmatched.append(wanted)

    if not removed:
        raise _Refused(
            f'no column on "{_label(page)}" matches '
            + ", ".join(f'"{col}"' for col in op.columns[:3]))
    for spec in specs:
        _restate_notes(spec)
    reply = (f'excluded {len(removed)} column(s) from "{_label(page)}": '
             + "; ".join(f'"{col}"' for col in removed)
             + (" — but found no column matching "
                + ", ".join(f'"{col}"' for col in unmatched)
                if unmatched else ""))
    return reply, f'excluded {len(removed)} column(s) from "{_label(page)}"'


def restore_columns(draft: Deliverable, op: "PageOp", _corpus) -> tuple[str, str]:
    """Put excluded columns back. With no columns named, all of them."""
    from app.deliverable.revise import _mentions, _squash

    page = _find(draft, op)
    specs = _table_specs(draft, page)
    if not specs:
        raise _Refused(f'"{_label(page)}" has no table')

    restored: list[str] = []
    for spec in specs:
        for excluded in list(spec.excluded_columns):
            if op.columns and not any(_mentions(_squash(wanted),
                                               _squash(excluded.header))
                                     or _mentions(_squash(excluded.header),
                                                  _squash(wanted))
                                     for wanted in op.columns):
                continue
            spec.restore_column(excluded)
            restored.append(excluded.header)
    if not restored:
        raise _Refused(f'no excluded column on "{_label(page)}" to put back')
    for spec in specs:
        _restate_notes(spec)
    return (f'restored {len(restored)} column(s) on "{_label(page)}": '
            + "; ".join(f'"{col}"' for col in restored),
            f'restored {len(restored)} column(s) on "{_label(page)}"')
