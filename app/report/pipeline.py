"""The only way a report is ever planned.

There were three copies of this: `graph.plan_content`, `main.plan_content_route`
and `conversation._plan`. Each assembled the same four things — the summary
bullets, the quality report, the fingerprint, the audience — and each did it
slightly differently. The chat path forgot the bullets entirely for a while, so
every chat-drafted report had an empty executive summary; the API path reused
bullets from the previous version and the graph path re-rolled them. Three
callers, three different reports from the same data.

One function, so a change to how a report is planned lands everywhere at once,
and so "what does this session's report say" has exactly one answer.

Planning is cheap by design: no extraction, no vision, and no LLM call when the
existing summary prose can be reused. That is what makes re-planning on every
staleness check affordable, and it is why the staleness check can afford to be
strict.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.models.pmi import Audience
from app.report import store as report_store
from app.report.content import ReportContent
from app.report.planner import plan as plan_report

log = logging.getLogger("pmi.report.pipeline")


def plan_for_session(
    session_id: str,
    analysis,
    *,
    audience: Optional[Audience] = None,
    audience_label: str = "",
    topic: Optional[str] = None,
    request_text: str = "",
    structure=None,
    reuse_bullets: bool = True,
    save: bool = True,
) -> ReportContent:
    """Plan (and by default store) this session's report.

    `reuse_bullets` keeps the executive-summary prose the session already paid
    for. It is on by default because re-planning happens whenever the analysis
    or the knowledge base moves, and re-rolling the summary each time would make
    the wording change under a user who only corrected a due date — and cost an
    LLM call to do it.
    """
    from app.agent import knowledge

    kb = knowledge.load(session_id)
    model = analysis.data_model
    quality = analysis.quality_report

    chosen = (audience or kb.audience or analysis.audience or Audience.PMO)
    label = (audience_label or kb.audience_label
             or getattr(analysis, "audience_label", "") or "")
    spec = structure if structure is not None else _stored_structure(kb)

    bullets = _bullets(session_id, model, chosen, request_text or analysis.request_text,
                       reuse=reuse_bullets, quality=quality)

    content = plan_report(
        model, chosen,
        session_id=session_id,
        topic=topic or analysis.topic,
        bullets=bullets,
        quality=quality,
        fingerprint=report_store.fingerprint(model, quality, session_id=session_id),
        audience_label=label,
        structure=spec,
    )
    content = _apply_prose_overrides(content, kb)
    return report_store.save(content) if save else content


def _apply_prose_overrides(content: ReportContent, kb) -> ReportContent:
    """Overlay the user's rewritten prose onto the freshly planned blocks.

    Applied *after* planning, so the override wins over whatever the planner
    produced this time — the point of storing it is that it outlives the plan.
    Only prose and bullet blocks are text; a table cell or a fact tile is data
    and is corrected through the data model, never here.
    """
    overrides = getattr(kb, "prose_overrides", None)
    if not overrides:
        return content

    from app.report.content import Bullet

    for section in content.sections:
        for index, block in enumerate(section.blocks):
            text = overrides.get(block.block_id)
            if text is None:
                continue
            if block.kind == "prose":
                section.blocks[index] = block.model_copy(update={
                    "text": text, "authored_by": "user"})
            elif block.kind == "bullets":
                items = [Bullet(text=line.strip(" \t•*-"), authored_by="user")
                         for line in text.splitlines() if line.strip()]
                section.blocks[index] = block.model_copy(update={"items": items})
    return content


def _bullets(session_id: str, model, audience: Audience, request_text: str,
             *, reuse: bool, quality=None) -> list[str]:
    """The executive summary's prose — reused only when it is still current.

    Reuse keeps the wording the session already paid for, but it must not
    outlive the data it describes. The stored bullets are LLM free text — the
    one place a figure the report states is *asserted* rather than derived — so
    when the analysis has moved (a conflict resolved, a value supplied), a reused
    bullet can keep stating "progress is unresolved because sources conflict at
    82%, 78%, 41%" long after the user settled it. The deterministic parts of the
    report self-correct because they read the live model; the bullets can only be
    trusted if the content they came from is not stale. So gate reuse on exactly
    the staleness check `/api/generate` already uses, and re-roll otherwise.
    """
    if reuse:
        existing = report_store.load(session_id)
        if existing is not None and not report_store.is_stale(existing, model, quality):
            section = existing.section("summary.executive")
            if section and section.blocks and getattr(section.blocks[0], "items", None):
                return [item.text for item in section.blocks[0].items]

    from app.llm import tasks

    # `write_summary` falls back to template prose with no API key rather than
    # returning nothing, so this is populated either way — and a report with no
    # summary says so plainly rather than diagnosing a cause it did not measure.
    return tasks.write_summary(model, audience, request_text or "")


def _stored_structure(kb):
    """The structure the user asked for, if any, revived from the KB.

    Stored as a plain dict there so `knowledge.py` stays storage rather than
    planning; it is re-typed here, where structure is the subject.
    """
    if not kb.structure:
        return None
    from app.report.structure import StructureSpec

    try:
        return StructureSpec.model_validate(kb.structure)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("stored structure for %s is unreadable (%s); using the "
                    "default deck", kb.session_id, exc)
        return None
