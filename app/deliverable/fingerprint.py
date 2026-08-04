"""Know when a deliverable has gone stale — and exactly which pages have.

`ReportContent.analysis_fingerprint` was a single hash of entity counts. It could
answer "is this document stale" and nothing more, so resolving one conflict
invalidated the whole draft and every page had to be rebuilt.

Here the digest is kept **per evidence item** as well as in aggregate. A page
records the evidence it used, so `stale_pages` can name exactly the pages whose
inputs moved. That is what makes targeted regeneration in `engine` both cheap
and correct.

Some changes stale everything, and should: a different request, a different
template, or a change to the planning code itself all mean the *argument* is
questionable, not just its figures.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

#: Bumped whenever planning semantics change enough that an existing document
#: would not be produced the same way again.
ENGINE_VERSION = 4


class ContextFingerprint(BaseModel):
    engine_version: int = ENGINE_VERSION
    evidence_digest: str = ""
    #: evidence_id -> digest. The reason page-level staleness is possible.
    evidence_digests: dict[str, str] = Field(default_factory=dict)
    knowledge_version: int = 0
    content_revision: int = 0
    request_digest: str = ""
    template_digest: str = ""
    brief_digest: str = ""

    def whole_document_key(self) -> tuple:
        """The parts whose change invalidates the storyline, not just figures."""
        return (self.engine_version, self.request_digest, self.template_digest)

    def brief_differs_from(self, other: "ContextFingerprint") -> bool:
        """Whether the two briefs disagree — *when both are known*.

        Interpreting a request into an `OutputBrief` is a model call, so a caller
        merely asking "has this gone stale?" has no brief to offer and passes
        none. Treating that absence as a difference would mark every document
        stale the moment it was planned, and re-planning on every read is how a
        cheap check becomes an expensive one. The request itself is fingerprinted
        separately, so a genuinely changed ask is still caught.
        """
        return bool(self.brief_digest and other.brief_digest
                    and self.brief_digest != other.brief_digest)


def compute(context, *, brief=None, knowledge_version: int = 0,
            content_revision: int = 0) -> ContextFingerprint:
    evidence = context.evidence
    digests = {item.evidence_id: _item_digest(item, evidence)
               for item in evidence}
    return ContextFingerprint(
        engine_version=ENGINE_VERSION,
        evidence_digest=_digest("|".join(f"{k}={v}"
                                         for k, v in sorted(digests.items()))),
        evidence_digests=digests,
        knowledge_version=knowledge_version,
        content_revision=content_revision,
        request_digest=_digest(_normalize_request(context)),
        template_digest=str(getattr(context.template_reference,
                                    "template_digest", "")),
        brief_digest=_digest(_brief_key(brief)) if brief is not None else "",
    )


def _item_digest(item, evidence=None) -> str:
    """What must change for a page citing this item to need rebuilding.

    The subtle part is the resolution *state* of any attached conflict.
    Answering "which of these two sources is right" changes what a page may
    assert about a figure, even though the figure itself did not move — so a
    digest over the item's own fields alone would leave a page saying "sources
    disagree" after the disagreement was settled.
    """
    parts = [item.evidence_id, str(item.value), item.display, item.status or "",
             item.severity or "", f"{item.confidence:.3f}"]
    for conflict_id in sorted(item.conflict_ids):
        state = ""
        if evidence is not None:
            attached = evidence.get(f"ev:conflict:{conflict_id}")
            if attached is not None:
                state = f"{attached.status}:{attached.display}"
        parts.append(f"{conflict_id}={state}")
    return _digest("|".join(parts))[:12]


def _normalize_request(context) -> str:
    text = " ".join((context.user_request or "").split()).casefold()
    extras = [context.audience or "", context.requested_output_format or "",
              "presentation" if context.presentation_layout else "document",
              "|".join(context.requested_sections),
              "|".join(f"{c.kind}={c.value}" for c in context.user_constraints)]
    return text + "||" + "||".join(extras)


def _brief_key(brief) -> str:
    return "|".join([
        brief.document_kind, brief.primary_format, brief.audience_label,
        str(brief.target_page_count or ""), brief.length_hint,
        "|".join(brief.scope_topics),
    ])


def _digest(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ queries
def is_stale(deliverable, current: ContextFingerprint) -> bool:
    stored = _stored(deliverable)
    if stored is None:
        return True
    if stored.whole_document_key() != current.whole_document_key():
        return True
    if stored.brief_differs_from(current):
        return True
    return stored.evidence_digest != current.evidence_digest


def stale_reason(deliverable, current: ContextFingerprint) -> str:
    """Why, in words a user can act on."""
    stored = _stored(deliverable)
    if stored is None:
        return "This draft predates the current planning engine."
    if stored.engine_version != current.engine_version:
        return "The report engine has changed since this draft was planned."
    if stored.request_digest != current.request_digest:
        return "The request has changed since this draft was planned."
    if stored.template_digest != current.template_digest:
        return "The presentation template has changed."
    if stored.brief_differs_from(current):
        return "The document's scope or audience has changed."
    if stored.evidence_digest != current.evidence_digest:
        changed = len(_changed_ids(stored, current))
        return f"{changed} piece(s) of underlying evidence have changed."
    return ""


def stale_pages(deliverable, current: ContextFingerprint) -> list[str]:
    """Exactly the pages whose evidence moved.

    Empty when the whole document is stale — that case is not a repair, it is a
    re-plan, and returning a page list would invite the caller to patch a
    document whose argument no longer holds.
    """
    stored = _stored(deliverable)
    if stored is None or stored.whole_document_key() != current.whole_document_key():
        return []
    if stored.brief_differs_from(current):
        return []

    changed = _changed_ids(stored, current)
    if not changed:
        return []
    return [page.page_id for page in deliverable.pages
            if changed & set(page.evidence_ids)]


def _changed_ids(stored: ContextFingerprint,
                 current: ContextFingerprint) -> set[str]:
    changed: set[str] = set()
    for evidence_id, digest in current.evidence_digests.items():
        if stored.evidence_digests.get(evidence_id) != digest:
            changed.add(evidence_id)
    for evidence_id in stored.evidence_digests:
        if evidence_id not in current.evidence_digests:
            changed.add(evidence_id)
    return changed


def _stored(deliverable) -> Optional[ContextFingerprint]:
    raw = getattr(deliverable, "fingerprint", None)
    if not raw:
        return None
    try:
        return ContextFingerprint.model_validate(raw)
    except Exception:                                          # noqa: BLE001
        return None
