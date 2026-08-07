"""Revision operations over a `Deliverable`, and the only way one is ever edited.

`app/report/ops.py` made §11 structural for `ReportContent`: read its `ReviseOp`
and there is no field that can reach a cell, a tile or a fact, so no prompt and
no malformed response can produce "change the variance to -400" — it is not a
matter of the model behaving. That guarantee does not survive being reimplemented
loosely, so it is reimplemented exactly: the op vocabulary here selects,
reorders, and rewords, and every authored string passes `guard.check_text`
against the evidence's numeric corpus before it is accepted.

Two things differ from the `ReportContent` version, both because the object
differs:

* **A dropped page is kept, not flagged.** `Section.narrative_order = None` was
  how the old model remembered a removed section. Pages are an ordered list with
  no such field, so a dropped one moves to `dropped_pages` — still in the
  document, still restorable, and invisible to every renderer without any
  renderer needing to know the concept exists.
* **Text lives on elements, not blocks.** An op names a page and a role; the
  element is found within the page. Element ids are not stable across a re-plan
  and page ids are, so naming the page is what makes an instruction survive one.
* **A row is excluded, not deleted.** "From open risks exclude X and Y" is a
  selection, not a rewrite, and `exclude_rows` names rows the table already has
  — so it stays within §11 exactly as `set_row_limit` does. The rows move to
  `TableSpec.excluded_rows`, which is what makes `restore_rows` possible and
  what lets the table say it was filtered.

Applying is pure: ops in, a new `Deliverable` out. Nothing here writes to disk,
and the input is never mutated — the caller decides whether the result becomes a
version.
"""
from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.deliverable import column_ops
from app.deliverable.model import (
    BulletsElement,
    Deliverable,
    PageDesign,
    TableElement,
    TextElement,
)

log = logging.getLogger("pmi.deliverable.revise")

OpName = Literal[
    "reorder", "drop_page", "restore_page", "rewrite_title", "rewrite_subtitle",
    "rewrite_bullet", "add_bullet", "drop_bullet", "add_page",
    "set_row_limit", "set_emphasis", "exclude_rows", "restore_rows",
    "exclude_columns", "restore_columns",
]

#: How the §12.5 disclosure page is recognised, whatever the planner titled it.
#: Removing it is allowed — see `_drop_page` — but it is worth saying out loud,
#: so the page still has to be identifiable after the fact.
DISCLOSURE_PURPOSES = ("limitations",)


class PageOp(BaseModel):
    """One edit. Deliberately anaemic — see the module docstring."""

    op: OpName
    page_id: Optional[str] = None
    #: Which bullet, for the bullet ops.
    index: Optional[int] = None
    #: New wording. Guarded before it is accepted.
    text: Optional[str] = None
    #: Full page order, for `reorder`.
    order: Optional[list[str]] = None
    #: Which table rows to exclude or restore, named in the user's own words.
    #: Selects existing rows — it can no more author one than `text` can.
    rows: Optional[list[str]] = None
    #: For `add_page`: a title, plus prose-only content.
    title: Optional[str] = None
    row_limit: Optional[int] = None
    emphasis: Optional[str] = None


class DeliverableRevision(BaseModel):
    """What a revision request produces. Capped so one instruction cannot
    rewrite the whole document in a single turn."""

    ops: list[PageOp] = Field(default_factory=list, max_length=12)
    rationale: str = ""


class RejectedOp(BaseModel):
    op: str
    reason: str


class RevisionResult(BaseModel):
    deliverable: Optional[Deliverable] = None
    applied: list[str] = Field(default_factory=list)
    rejected: list[RejectedOp] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def apply(deliverable: Deliverable, revision: DeliverableRevision, *,
          corpus: Optional[set[str]] = None,
          instruction: str = "") -> RevisionResult:
    """Apply `revision`, reporting everything accepted and everything refused.

    §21.17: nothing is dropped silently. If every op is rejected the result
    carries no deliverable and all the reasons — the caller surfaces them rather
    than handing back the old version as though the request had succeeded.

    A handler may answer with `(reply, note)` when the two audiences differ.
    They differ for exactly one reason so far and it matters: `draft.notes` is
    *rendered*, into the limitations section every format prints, while `reply`
    only reaches the chat. So "excluded «Key engineer attrition»" is the right
    confirmation to the person who asked and the wrong thing to publish — it
    reprints, in the appendix, the row they asked to take out.
    """
    draft = deliverable.model_copy(deep=True)
    corpus = corpus if corpus is not None else set()

    applied: list[str] = []
    notes: list[str] = []
    rejected: list[RejectedOp] = []

    for op in revision.ops:
        handler = _HANDLERS.get(op.op)
        if handler is None:
            rejected.append(RejectedOp(op=op.op,
                                       reason=f"unknown operation {op.op!r}"))
            continue
        try:
            outcome = handler(draft, op, corpus)
        except _Refused as refusal:
            rejected.append(RejectedOp(op=op.op, reason=str(refusal)))
            continue
        reply, note = outcome if isinstance(outcome, tuple) else (outcome,
                                                                 outcome)
        applied.append(reply)
        notes.append(note)

    for refusal in rejected:
        log.info("revision op refused: %s", refusal.reason)

    if not applied:
        return RevisionResult(deliverable=None, applied=[], rejected=rejected)

    draft.parent_version = deliverable.version
    draft.version = deliverable.version + 1
    # The instruction is quoted verbatim, so it goes in only when no handler
    # asked for anything to be held back — the user's own sentence names the
    # rows just as surely as the confirmation does.
    redacted = notes != applied
    draft.notes.append(
        f"Revision “{instruction.strip()}”: " + "; ".join(notes)
        if instruction.strip() and not redacted else "Revision: " + "; ".join(notes))
    draft.renumber()
    return RevisionResult(deliverable=draft, applied=applied, rejected=rejected)


def revise(deliverable: Deliverable, instruction: str, *,
           corpus: Optional[set[str]] = None,
           use_model: bool = True) -> tuple[RevisionResult, list[str]]:
    """`(result, warnings)`. Never raises for an unusable instruction."""
    warnings: list[str] = []
    revision = _interpret(deliverable, instruction, use_model=use_model)

    if not revision.ops:
        return (RevisionResult(deliverable=None, applied=[], rejected=[]),
                warnings + [revision.rationale
                            or "the instruction was not understood"])

    return apply(deliverable, revision, corpus=corpus,
                 instruction=instruction), warnings


def _interpret(deliverable: Deliverable, instruction: str, *,
               use_model: bool) -> DeliverableRevision:
    from app.llm import fast_model, prompts, tasks

    # A direct table-size request must not disappear because a model returned
    # an empty operation list. Keep the deterministic fast path narrow so a
    # compound prose/structure revision can still be interpreted as a whole.
    row_revision = _kw_row_limit((instruction or "").strip().lower(),
                                 deliverable)
    if row_revision is not None:
        return row_revision
    if not use_model:
        return keyword_ops(instruction, deliverable)

    return tasks.run_task(
        "revise.document",
        system=prompts.compose("_grounding_rules", "revise_document"),
        user=_prompt(deliverable, instruction),
        output_model=DeliverableRevision,
        model=fast_model(),
        max_tokens=2048,
        fallback=lambda: keyword_ops(instruction, deliverable),
    )


#: Row labels shown per table. Enough to name the row someone means without
#: turning the table of contents back into the table.
_PROMPT_ROW_LABELS = 40


def _prompt(deliverable: Deliverable, instruction: str) -> str:
    """Show the model the table of contents — never the figures.

    It does not need the numbers to decide what to reorder or remove, and not
    sending them removes the temptation to quote one back.

    Row *labels* are the exception, and are not figures: "exclude the works
    council row" cannot be carried out by anything that has not been told the
    table has such a row. Only the label is listed, never the rest of the row.
    """
    from app.llm import prompts

    lines = ["Pages, in order:"]
    for page in deliverable.pages:
        table_details = []
        row_labels: list[str] = []
        excluded_labels: list[str] = []
        for element in page.elements:
            if not isinstance(element, TableElement):
                continue
            spec = deliverable.specs.tables.get(element.spec_id)
            if spec is not None:
                table_details.append(
                    f"{spec.displayed_row_count} shown / "
                    f"{max(spec.total_rows, len(spec.rows))} available")
                row_labels += [label for row in spec.rows
                               if (label := _row_label(row))]
                excluded_labels += [row.label for row in spec.excluded_rows
                                    if row.label]
        suffix = f"; table: {', '.join(table_details)}" if table_details else ""
        lines.append(
            f"- {page.page_id}: “{_label(page)}” ({page.purpose}{suffix})")
        for label in row_labels[:_PROMPT_ROW_LABELS]:
            lines.append(f"    row: {label}")
        if len(row_labels) > _PROMPT_ROW_LABELS:
            lines.append(f"    … and {len(row_labels) - _PROMPT_ROW_LABELS} more")
        for label in excluded_labels[:_PROMPT_ROW_LABELS]:
            lines.append(f"    excluded row (restorable): {label}")
    if deliverable.dropped_pages:
        lines += ["", "Removed but restorable:"]
        lines += [f"- {p.page_id}: “{_label(p)}”"
                  for p in deliverable.dropped_pages]
    lines += ["", prompts.data_block("instruction", instruction)]
    return "\n".join(lines)


class _Refused(Exception):
    """Internal: this op will not be applied, and here is why."""


def _guarded(text: Optional[str], corpus: set[str], what: str) -> str:
    from app.report import guard

    if not text or not text.strip():
        raise _Refused(f"{what} requires text")
    offending = guard.check_text(text, corpus)
    if offending:
        raise _Refused(guard.describe(offending, text))
    return text.strip()


def _find(draft: Deliverable, op: PageOp) -> PageDesign:
    if not op.page_id:
        raise _Refused("no page named")
    page = draft.page(op.page_id)
    if page is None:
        raise _Refused(f"no page {op.page_id!r} in this document")
    return page


def _label(page: PageDesign) -> str:
    return page.title or page.page_id


def is_disclosure_page(page: PageDesign) -> bool:
    """Whether this is the page §12.5 asks for — by purpose or by its title.

    The planner titles it "Data quality and limitations"; a user-described
    structure may call it something else, and the purpose is what survives a
    retitle. Both are checked because either one alone has been wrong.
    """
    return (page.purpose in DISCLOSURE_PURPOSES
            or "limitation" in (page.title or "").casefold()
            or "data quality" in (page.title or "").casefold())


# ------------------------------------------------------------------ handlers
def _reorder(draft: Deliverable, op: PageOp, _corpus) -> str:
    if not op.order:
        raise _Refused("reorder needs an order")
    known = {p.page_id for p in draft.pages}
    unknown = [pid for pid in op.order if pid not in known]
    if unknown:
        raise _Refused(f"unknown page(s): {', '.join(unknown)}")

    position = {pid: index for index, pid in enumerate(op.order)}
    # The cover is furniture and stays where it is; anything unnamed keeps its
    # relative order after the pages that were named.
    draft.pages.sort(key=lambda p: (p.purpose != "cover",
                                    position.get(p.page_id, len(position)),
                                    p.index))
    draft.renumber()
    return f"reordered {len(op.order)} page(s)"


def _drop_page(draft: Deliverable, op: PageOp, _corpus) -> str:
    """Take a page out of the document. Including the data-quality page.

    That page used to be refused outright on §12.5 grounds. Refusing it did not
    keep the disclosure honest — it produced a report the author could not shape
    and an instruction the agent visibly ignored, while the page was rendered
    anyway. §12.5 constrains what *this system* may hide from a reader, not what
    an author may choose to leave out of their own document, and the removal is
    neither silent nor final: it is confirmed in chat, recorded in the
    deliverable's notes, and the page stays in `dropped_pages` so "restore the
    data quality page" puts it back.
    """
    page = _find(draft, op)
    if page.purpose == "cover":
        raise _Refused("the cover cannot be removed")
    draft.pages.remove(page)
    draft.dropped_pages.append(page)
    draft.renumber()
    if is_disclosure_page(page):
        # The same split `_exclude_rows` makes, for the same reason. The note is
        # *rendered*, into the appendix — so naming this page there, or quoting
        # the instruction that named it, prints "Data quality and limitations"
        # in the document the user just took it out of, and reads as the removal
        # having been ignored.
        log.info("data-quality page %r removed on request", page.page_id)
        return f"removed “{_label(page)}”", "removed 1 page at the author's request"
    return f"removed “{_label(page)}”"


def _restore_page(draft: Deliverable, op: PageOp, _corpus) -> str:
    if not op.page_id:
        raise _Refused("no page named")
    page = next((p for p in draft.dropped_pages if p.page_id == op.page_id), None)
    if page is None:
        raise _Refused(f"{op.page_id!r} is not a page that was removed")
    draft.dropped_pages.remove(page)
    draft.pages.append(page)
    draft.renumber()
    return f"restored “{_label(page)}”"


def _rewrite_title(draft: Deliverable, op: PageOp, corpus) -> str:
    page = _find(draft, op)
    before = _label(page)
    page.title = _guarded(op.text, corpus, "rewrite_title")
    return f"retitled “{before}”"


def _rewrite_subtitle(draft: Deliverable, op: PageOp, corpus) -> str:
    page = _find(draft, op)
    page.subtitle = _guarded(op.text, corpus, "rewrite_subtitle")
    return f"reworded the subtitle of “{_label(page)}”"


def _rewrite_bullet(draft: Deliverable, op: PageOp, corpus) -> str:
    page = _find(draft, op)
    element = _bullets(page)
    if op.index is None or not 0 <= op.index < len(element.items):
        raise _Refused(f"no bullet {op.index} on “{_label(page)}”")
    element.items[op.index] = _guarded(op.text, corpus, "rewrite_bullet")
    element.authored_by = "llm"
    return f"reworded bullet {op.index + 1} of “{_label(page)}”"


def _add_bullet(draft: Deliverable, op: PageOp, corpus) -> str:
    page = _find(draft, op)
    element = _bullets(page, create=True)
    element.items.append(_guarded(op.text, corpus, "add_bullet"))
    element.authored_by = "llm"
    return f"added a point to “{_label(page)}”"


def _drop_bullet(draft: Deliverable, op: PageOp, _corpus) -> str:
    page = _find(draft, op)
    element = _bullets(page)
    if op.index is None or not 0 <= op.index < len(element.items):
        raise _Refused(f"no bullet {op.index} on “{_label(page)}”")
    removed = element.items.pop(op.index)
    # Same split as `_exclude_rows`: confirm the wording to the person who
    # asked, but do not reprint it in the rendered limitations section.
    return (f"removed “{removed[:40]}” from “{_label(page)}”",
            f"removed a point from “{_label(page)}”")


def _add_page(draft: Deliverable, op: PageOp, corpus) -> str:
    """Prose only.

    A page whose *rows* came from a model would be data the report never
    extracted. New tables can only ever be a filtered view of entities already
    held, which is a planner's job — so what a revision may add is commentary,
    and commentary goes through the guard like any other text.
    """
    if not op.title:
        raise _Refused("add_page needs a title")
    text = _guarded(op.text, corpus, "add_page")

    page_id = op.page_id or f"user-{len(draft.pages) + 1}"
    if draft.page(page_id) is not None:
        raise _Refused(f"page {page_id!r} already exists")

    page = PageDesign(
        page_id=page_id, section_id=page_id, purpose="content",
        composition="single", title=op.title, planned_by="user",
        elements=[TextElement(element_id=f"{page_id}.body", role="body",
                              text=text, authored_by="user",
                              prominence="primary")],
    )
    draft.pages.append(page)
    draft.renumber()
    return f"added “{op.title}”"


def _set_row_limit(draft: Deliverable, op: PageOp, _corpus) -> str:
    page = _find(draft, op)
    if op.row_limit is None or op.row_limit < 1:
        raise _Refused("row_limit must be at least 1")
    tables = [e for e in page.elements if isinstance(e, TableElement)]
    if not tables:
        raise _Refused(f"“{_label(page)}” has no table")
    changed = 0
    for element in tables:
        spec = draft.specs.tables.get(element.spec_id)
        if spec is not None:
            spec.row_limit = op.row_limit
            # Validation records the original dynamic note on the spec. Keep
            # it aligned with the revised view instead of preserving a stale
            # “Showing 12 ...” warning after all rows have been requested.
            _restate_notes(spec)
            changed += 1
    if not changed:
        raise _Refused(f"“{_label(page)}” has no table that can be resized")
    return f"showing {op.row_limit} row(s) on “{_label(page)}”"


def _exclude_rows(draft: Deliverable, op: PageOp, _corpus) -> str:
    """Leave named rows out of a page's table.

    The rows are matched against what the table already holds and then moved
    aside, so nothing here can put a value into the report that the evidence
    did not already support.
    """
    page = _find(draft, op)
    if not op.rows:
        raise _Refused("exclude_rows needs the row(s) to leave out")
    specs = _table_specs(draft, page)
    if not specs:
        raise _Refused(f"“{_label(page)}” has no table")

    removed: list[str] = []
    unmatched: list[str] = []
    for wanted in op.rows:
        for spec in specs:
            index = _match_row(wanted, spec)
            if index is not None:
                removed.append(spec.exclude_row(index).label or wanted)
                break
        else:
            unmatched.append(wanted)

    if not removed:
        raise _Refused(
            f"no row on “{_label(page)}” matches "
            + ", ".join(f"“{row}”" for row in op.rows[:3]))
    for spec in specs:
        _restate_notes(spec)
    # §21.17: a row that could not be found is said out loud, in the same
    # sentence as the ones that were — not left for the user to notice.
    reply = (f"excluded {len(removed)} row(s) from “{_label(page)}”: "
             + "; ".join(f"“{row}”" for row in removed)
             + (" — but found no row matching "
                + ", ".join(f"“{row}”" for row in unmatched)
                if unmatched else ""))
    return reply, f"excluded {len(removed)} row(s) from “{_label(page)}”"


def _restore_rows(draft: Deliverable, op: PageOp, _corpus) -> str:
    """Put excluded rows back. With no rows named, all of them."""
    page = _find(draft, op)
    specs = _table_specs(draft, page)
    if not specs:
        raise _Refused(f"“{_label(page)}” has no table")

    restored: list[str] = []
    for spec in specs:
        for excluded in list(spec.excluded_rows):
            if op.rows and not any(_mentions(_squash(wanted),
                                             _squash(excluded.label))
                                   or _mentions(_squash(excluded.label),
                                                _squash(wanted))
                                   for wanted in op.rows):
                continue
            spec.restore_row(excluded)
            restored.append(excluded.label)
    if not restored:
        raise _Refused(f"no excluded row on “{_label(page)}” to put back")
    for spec in specs:
        _restate_notes(spec)
    return (f"restored {len(restored)} row(s) on “{_label(page)}”: "
            + "; ".join(f"“{row}”" for row in restored))


def _table_specs(draft: Deliverable, page: PageDesign) -> list:
    specs = [draft.specs.tables.get(element.spec_id) for element in page.elements
             if isinstance(element, TableElement)]
    return [spec for spec in specs if spec is not None]


def _restate_notes(spec) -> None:
    """Keep the table's own notes true after its rows have moved.

    Both notes are derived, so a stale “Showing 12 of 137 rows.” left behind by
    an earlier edit would contradict the table printed underneath it.
    """
    derived = (spec.truncation_note(), spec.exclusion_note())
    spec.warnings = [warning for warning in spec.warnings
                     if not _is_derived_note(warning)]
    spec.warnings += [note for note in derived if note]


def _is_derived_note(warning: str) -> bool:
    return bool(re.match(r"^(Showing \d+ of \d+ rows\.|\d+ row\(s\) excluded)",
                         warning or ""))


def _set_emphasis(draft: Deliverable, op: PageOp, _corpus) -> str:
    page = _find(draft, op)
    if op.emphasis not in ("none", "good", "warn", "bad", "muted"):
        raise _Refused(f"unknown emphasis {op.emphasis!r}")
    element = _bullets(page)
    element.emphasis = op.emphasis                        # type: ignore[assignment]
    return f"changed emphasis on “{_label(page)}”"


def _bullets(page: PageDesign, *, create: bool = False) -> BulletsElement:
    element = next((e for e in page.elements
                    if isinstance(e, BulletsElement)), None)
    if element is None:
        if not create:
            raise _Refused(f"“{_label(page)}” has no bullet list to edit")
        element = BulletsElement(element_id=f"{page.page_id}.bullets")
        page.elements.append(element)
    return element


# --------------------------------------------------- interpreting, keylessly
_STOPWORDS = {
    "the", "a", "an", "slide", "section", "page", "and", "of", "for", "on",
    "please", "to", "from", "my", "our", "this", "that",
}


def keyword_ops(instruction: str, deliverable: Deliverable
                ) -> DeliverableRevision:
    """Best-effort ops with no model. Empty when nothing matched.

    Keyword matching only, and deliberately narrow: it recognises the
    instructions people actually type and refuses everything else by returning
    no ops, which the caller reports as "I did not understand that" rather than
    guessing. A revision engine that guesses is worse than one that declines.
    """
    # Preserve casing: a replacement title is user-authored wording.
    text = (instruction or "").strip()
    if not text:
        return DeliverableRevision(ops=[], rationale="no instruction given")

    renamed = _kw_rename(text, deliverable)
    if renamed is not None:
        return renamed

    lowered = text.lower()
    for rule in (_kw_exclude_rows, _kw_drop, _kw_restore, _kw_move_first,
                 _kw_row_limit):
        revision = rule(lowered, deliverable)
        if revision is not None:
            return revision

    return DeliverableRevision(
        ops=[],
        rationale=("Could not interpret that without a language model. Try "
                   "“remove the dependencies page”, “put risks first”, or "
                   "“show 5 rows on milestones”."),
    )


def _kw_rename(text: str, deliverable: Deliverable
               ) -> Optional[DeliverableRevision]:
    """Recognise ``rename X to/into/as Y`` without a model."""
    match = re.search(
        r"\b(?:rename|retitle)\s+(?:the\s+)?(?P<old>.+?)\s+"
        r"(?:to|as|into)\s+(?P<new>.+?)\s*[.!?]?\s*$",
        text, re.I,
    )
    if not match:
        return None
    old = match.group("old").strip(" \t\"'“”‘’")
    new = match.group("new").strip(" \t\"'“”‘’.,;:!?-")
    if not old or not new:
        return None
    # Match only the old wording. The new wording often shares words with it,
    # and must not influence which page is selected.
    page = _match_page(old, deliverable.pages)
    if page is None:
        return None
    return DeliverableRevision(
        ops=[PageOp(op="rewrite_title", page_id=page.page_id, text=new)],
        rationale=f"rename “{_label(page)}” to “{new}”",
    )


def _kw_drop(text: str, deliverable: Deliverable
             ) -> Optional[DeliverableRevision]:
    if not re.search(r"\b(remove|drop|delete|take out|hide|exclude|omit|leave out)\b", text):
        return None
    page = _match_page(text, deliverable.pages)
    if page is None:
        return None
    return DeliverableRevision(
        ops=[PageOp(op="drop_page", page_id=page.page_id)],
        rationale=f"remove “{_label(page)}”")


_EXCLUDE_VERB = (r"exclude|omit|leave out|drop|remove|delete|take out|hide|"
                 r"without")

#: "from open risks exclude X and Y". The scope is what to look inside; it is
#: also the only reliable signal that a page was named as a *place* rather than
#: as the thing to delete.
_SUBSET = re.compile(rf"\bfrom\s+(?P<scope>.+?)\s+(?:{_EXCLUDE_VERB})\b", re.I)


def _kw_exclude_rows(text: str, deliverable: Deliverable
                     ) -> Optional[DeliverableRevision]:
    """``from open risks exclude X and Y`` — the items, not the page.

    Runs before `_kw_drop`, which shares every one of its verbs. Without that
    ordering this instruction matched the *page* “Open risks” and removed all
    of it: someone asking to leave two entries out lost the whole register, and
    the reply said “removed «Open risks»” as though that was the request.

    The items are not split on "and". The first one here contains one
    ("Communicate to employees and customers"), and any split that gets that
    right gets another sentence wrong. Instead every entry the page already
    holds is asked whether the instruction names it — which needs no splitting,
    and cannot invent an entry that is not there.
    """
    if not re.search(rf"\b(?:{_EXCLUDE_VERB})\b", text):
        return None
    subset = _SUBSET.search(text)
    # Match the page on the scope alone when there is one: the items carry
    # words of their own ("customers") that otherwise pull the match onto
    # whichever page happens to share them.
    page = _match_page(subset.group("scope") if subset else text,
                       deliverable.pages)
    if page is None:
        return None

    ops, described = _exclusion_ops(deliverable, page, text)
    if ops:
        return DeliverableRevision(
            ops=ops, rationale=f"exclude {described} from “{_label(page)}”")
    if subset is None:
        return None
    # "from X exclude Y" is unambiguously about part of X. Declining is the
    # only safe answer left — falling through would delete X entirely.
    return DeliverableRevision(ops=[], rationale=(
        f"“{_label(page)}” has nothing matching that. Name a row or a point as "
        f"it appears on the page, or say “remove the {_label(page)} page” to "
        f"take the whole page out."))


def _exclusion_ops(deliverable: Deliverable, page: PageDesign,
                   text: str) -> tuple[list[PageOp], str]:
    """Ops that remove whichever of the page's own entries the text names.

    Tables and bullet lists both, because which one a page uses is a layout
    decision the user never made and should not have to know about.
    """
    instruction = _squash(text)
    rows = [label for spec in _table_specs(deliverable, page)
            for label in (_row_label(row) for row in spec.rows)
            if label and _mentions(_squash(label), instruction)]
    if rows:
        return ([PageOp(op="exclude_rows", page_id=page.page_id, rows=rows)],
                f"{len(rows)} row(s)")

    element = next((e for e in page.elements if isinstance(e, BulletsElement)),
                   None)
    if element is None:
        return [], ""
    indexes = [index for index, item in enumerate(element.items)
               if item and _mentions(_squash(item), instruction)]
    # Descending: `drop_bullet` pops by index, so removing 1 before 3 would
    # leave the second op pointing at whatever slid down into its place.
    return ([PageOp(op="drop_bullet", page_id=page.page_id, index=index)
             for index in sorted(indexes, reverse=True)],
            f"{len(indexes)} point(s)")


def _kw_restore(text: str, deliverable: Deliverable
                ) -> Optional[DeliverableRevision]:
    if not re.search(r"\b(restore|bring back|put back|add back|show again)\b",
                     text):
        return None
    page = _match_page(text, deliverable.dropped_pages)
    if page is None:
        return None
    return DeliverableRevision(
        ops=[PageOp(op="restore_page", page_id=page.page_id)],
        rationale=f"restore “{_label(page)}”")


def _kw_move_first(text: str, deliverable: Deliverable
                   ) -> Optional[DeliverableRevision]:
    if not re.search(r"\b(first|to the top|up front|lead with|start with)\b",
                     text):
        return None
    page = _match_page(text, deliverable.pages)
    if page is None or page.purpose == "cover":
        return None
    order = [p.page_id for p in deliverable.pages if p.purpose != "cover"]
    order.remove(page.page_id)
    return DeliverableRevision(
        ops=[PageOp(op="reorder", order=[page.page_id] + order)],
        rationale=f"move “{_label(page)}” to the front")


def _kw_row_limit(text: str, deliverable: Deliverable
                  ) -> Optional[DeliverableRevision]:
    match = re.search(
        r"\bshow\s+(?:me\s+)?(?:only\s+|all\s+)?(?P<count>\d+)"
        r"(?:\s+of\s+\d+)?(?:\s+rows?)?\b",
        text,
    )
    wants_all = bool(re.search(
        r"\bshow\s+(?:me\s+)?all(?:\s+(?:the\s+)?)?rows?\b", text))
    if not match and not wants_all:
        return None
    page = _match_page(text, deliverable.pages)
    if page is None:
        return None
    if match:
        row_limit = int(match.group("count"))
    else:
        totals = [max(spec.total_rows, len(spec.rows))
                  for element in page.elements
                  if isinstance(element, TableElement)
                  for spec in [deliverable.specs.tables.get(element.spec_id)]
                  if spec is not None]
        if not totals:
            return None
        row_limit = max(totals)
    return DeliverableRevision(
        ops=[PageOp(op="set_row_limit", page_id=page.page_id,
                    row_limit=row_limit)],
        rationale=f"show {row_limit} rows on “{_label(page)}”")


def _match_page(text: str, pages) -> Optional[PageDesign]:
    """The page whose title best overlaps the instruction.

    Requires a real word in common, so "remove that" matches nothing rather
    than picking whichever page happens to sort first.
    """
    words = _words(text)
    best, best_score = None, 0
    for page in pages:
        candidate = _words(page.title) | _words(page.page_id.replace("-", " ")) \
            | _words(page.subtitle)
        score = len(words & candidate)
        if score > best_score:
            best, best_score = page, score
    return best if best_score else None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower())
            if w not in _STOPWORDS and len(w) > 2}


def _squash(text: str) -> str:
    """Letters and digits only — what somebody typed, minus how they typed it."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


#: A prefix shorter than this is not enough to name a row on its own.
_MIN_ROW_PREFIX = 12


def _mentions(needle: str, haystack: str) -> bool:
    """Whether `haystack` names `needle`, allowing for how requests arrive.

    Both sides are already squashed, because what reaches here is typed rather
    than chosen from a list: "Communicate toemployees andcustomers" has to find
    "Communicate to employees and customers", so spacing cannot be trusted.

    A trailing prefix match handles the other half of that — "Release the
    combined organisation structur" is the same row as "…structure", and a
    request cut off mid-word is common enough that failing it would send the
    user back to retype the whole instruction. Requiring three quarters of the
    phrase, and never fewer than `_MIN_ROW_PREFIX` characters, is what keeps
    that from matching a different row that merely starts the same way.
    """
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    limit = max(_MIN_ROW_PREFIX, (len(needle) * 3) // 4)
    return len(needle) > limit and needle[:limit] in haystack


def _row_label(cells) -> str:
    from app.visualizations.specs import _row_label as label

    return label(cells)


def _match_row(wanted: str, spec) -> Optional[int]:
    """The row the instruction meant, or `None`.

    Matched against the whole row, not only its label, so "exclude the GDPR
    one" finds a row whose subject sits in the second column.
    """
    needle = _squash(wanted)
    if len(needle) < 3:
        return None
    for index, row in enumerate(spec.rows):
        if _mentions(needle, _squash(" ".join(cell.text for cell in row))):
            return index
    return None


_HANDLERS = {
    "reorder": _reorder,
    "drop_page": _drop_page,
    "restore_page": _restore_page,
    "rewrite_title": _rewrite_title,
    "rewrite_subtitle": _rewrite_subtitle,
    "rewrite_bullet": _rewrite_bullet,
    "add_bullet": _add_bullet,
    "drop_bullet": _drop_bullet,
    "add_page": _add_page,
    "set_row_limit": _set_row_limit,
    "set_emphasis": _set_emphasis,
    "exclude_rows": _exclude_rows,
    "restore_rows": _restore_rows,
    "exclude_columns": column_ops.exclude_columns,
    "restore_columns": column_ops.restore_columns,
}
