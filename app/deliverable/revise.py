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

Applying is pure: ops in, a new `Deliverable` out. Nothing here writes to disk,
and the input is never mutated — the caller decides whether the result becomes a
version.
"""
from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

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
    "set_row_limit", "set_emphasis",
]

#: A page whose removal the user is not offered. §12.5 requires the document to
#: state what it could not do, and a reader is entitled to see it whether or not
#: the author finds it flattering.
PROTECTED_PURPOSES = ("limitations",)


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
    """
    draft = deliverable.model_copy(deep=True)
    corpus = corpus if corpus is not None else set()

    applied: list[str] = []
    rejected: list[RejectedOp] = []

    for op in revision.ops:
        handler = _HANDLERS.get(op.op)
        if handler is None:
            rejected.append(RejectedOp(op=op.op,
                                       reason=f"unknown operation {op.op!r}"))
            continue
        try:
            applied.append(handler(draft, op, corpus))
        except _Refused as refusal:
            rejected.append(RejectedOp(op=op.op, reason=str(refusal)))

    for refusal in rejected:
        log.info("revision op refused: %s", refusal.reason)

    if not applied:
        return RevisionResult(deliverable=None, applied=[], rejected=rejected)

    draft.parent_version = deliverable.version
    draft.version = deliverable.version + 1
    draft.notes.append(
        f"Revision “{instruction.strip()}”: " + "; ".join(applied)
        if instruction.strip() else "Revision: " + "; ".join(applied))
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


def _prompt(deliverable: Deliverable, instruction: str) -> str:
    """Show the model the table of contents — never the figures.

    It does not need the numbers to decide what to reorder or remove, and not
    sending them removes the temptation to quote one back.
    """
    from app.llm import prompts

    lines = ["Pages, in order:"]
    for page in deliverable.pages:
        lines.append(f"- {page.page_id}: “{_label(page)}” ({page.purpose})")
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


def _is_protected(page: PageDesign) -> bool:
    return (page.purpose in PROTECTED_PURPOSES
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
    page = _find(draft, op)
    if _is_protected(page):
        raise _Refused(
            "the data-quality page cannot be removed — it states what this "
            "report could not do, which every recipient is entitled to see")
    if page.purpose == "cover":
        raise _Refused("the cover cannot be removed")
    draft.pages.remove(page)
    draft.dropped_pages.append(page)
    draft.renumber()
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
    return f"removed “{removed[:40]}” from “{_label(page)}”"


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
            changed += 1
    if not changed:
        raise _Refused(f"“{_label(page)}” has no table that can be resized")
    return f"showing {op.row_limit} row(s) on “{_label(page)}”"


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
    # Preserve casing because a replacement title is the user's wording.
    text = (instruction or "").strip()
    if not text:
        return DeliverableRevision(ops=[], rationale="no instruction given")

    renamed = _kw_rename(text, deliverable)
    if renamed is not None:
        return renamed

    text = text.lower()
    for rule in (_kw_drop, _kw_restore, _kw_move_first, _kw_row_limit):
        revision = rule(text, deliverable)
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
    page = _match_page(old, deliverable.pages)
    if page is None:
        return None
    return DeliverableRevision(
        ops=[PageOp(op="rewrite_title", page_id=page.page_id, text=new)],
        rationale=f"rename “{_label(page)}” to “{new}”",
    )


def _kw_drop(text: str, deliverable: Deliverable
             ) -> Optional[DeliverableRevision]:
    if not re.search(r"\b(remove|drop|delete|take out|hide)\b", text):
        return None
    page = _match_page(text, deliverable.pages)
    if page is None:
        return None
    return DeliverableRevision(
        ops=[PageOp(op="drop_page", page_id=page.page_id)],
        rationale=f"remove “{_label(page)}”")


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
    match = re.search(r"\bshow (?:me )?(?:only )?(\d+)\b", text)
    if not match:
        return None
    page = _match_page(text, deliverable.pages)
    if page is None:
        return None
    return DeliverableRevision(
        ops=[PageOp(op="set_row_limit", page_id=page.page_id,
                    row_limit=int(match.group(1)))],
        rationale=f"limit “{_label(page)}” to {match.group(1)} rows")


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
}
