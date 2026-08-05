"""Assemble a `GenerationContext` from whichever stack the caller lives in.

Both entry points return the same object, so nothing downstream — interpreter,
storyline, renderers, critics — needs to know whether it is serving the project
workspace or the session chat.

This module is deliberately **model-free and cheap**. It reads stores, resolves
a name, extracts the request's explicit demands with regular expressions, and
projects evidence. Interpreting what the user *meant* is the request
interpreter's job, one layer up; doing it here would put an LLM call in front of
every render and every critic pass.

The extraction below is the "preserve what was asked for" guarantee in its most
literal form. When a user lists eleven sections, those eleven strings are
carried verbatim into `requested_sections`, projected into evidence as gaps
where nothing covers them, and checked by the completeness critic at the end.
The planner may retitle or regroup them. It may not lose them.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional, Sequence

from app.context.retrieval import (
    latest_request,
    relevant_messages,
    request_history,
    summarize_chat,
)
from app.context.schemas import (
    ChatExcerpt,
    CompanyNames,
    ContextGap,
    GenerationContext,
    KnowledgeDigest,
    TransactionContext,
    UserConstraint,
    UserFact,
)
from app.evidence import projection
from app.models.entities import PMIProject
from app.models.pmi import PMIDataModel

log = logging.getLogger("pmi.context.builder")


# ============================================================ public entry
def build_for_project(project_id: str, request_text: str, *,
                      chat_id: Optional[str] = None,
                      requested_format: Optional[str] = None,
                      repos=None) -> GenerationContext:
    """Context for the project workspace (`/api/chat`, drafts, exports)."""
    from app.project.json_repositories import default_repositories
    from app.storage import chat_store

    repos = repos or default_repositories()
    knowledge = repos.knowledge.current(project_id)
    model = knowledge.data_model if knowledge is not None else PMIDataModel()
    record = chat_store.get_project(project_id)

    digest = _project_digest(knowledge, record)
    # Every filed chat contributes retrieval context.  Canonical facts still
    # come only from ProjectKnowledge; this transcript layer supplies the
    # conversational history without treating questions as facts.
    messages = chat_store.list_project_messages(project_id)

    return _assemble(
        scope="project", project_id=project_id, chat_id=chat_id,
        session_id=None, model=model, digest=digest,
        folder_name=record.name if record else "",
        quality=knowledge.quality_report if knowledge is not None else None,
        request_text=request_text, requested_format=requested_format,
        messages=messages,
    )


def build_for_session(session_id: str, request_text: str, *,
                      chat_id: Optional[str] = None,
                      analysis=None) -> GenerationContext:
    """Context for the session chat (`/api/chats/*/messages`, `/api/generate`)."""
    from app.agent import knowledge as kb_store
    from app.storage import chat_store, json_store

    analysis = analysis or json_store.load_analysis(session_id)
    model = analysis.data_model if analysis is not None else PMIDataModel()
    if not model.project.project_name:
        stored = json_store.load_project(session_id)
        if stored is not None:
            model.project = stored

    chat = (chat_store.get_chat(chat_id) if chat_id
            else chat_store.get_chat_for_session(session_id))
    linked_project_id = chat.project_id if chat is not None else None
    record = (chat_store.get_project(linked_project_id)
              if linked_project_id else None)

    project_knowledge = None
    if linked_project_id:
        from app.project.json_repositories import default_repositories

        project_knowledge = default_repositories().knowledge.current(
            linked_project_id)

    session_kb = kb_store.load(session_id)
    digest = _merge_digests(
        _project_digest(project_knowledge, record),
        _session_digest(session_kb),
    )
    active_chat_id = chat.chat_id if chat is not None else chat_id
    messages = (
        chat_store.list_project_messages(linked_project_id)
        if linked_project_id
        else (chat_store.list_messages(active_chat_id) if active_chat_id else [])
    )

    context = _assemble(
        scope="session", project_id=linked_project_id, chat_id=active_chat_id,
        session_id=session_id, model=model, digest=digest,
        folder_name=record.name if record else "",
        quality=analysis.quality_report if analysis is not None else None,
        request_text=request_text or (analysis.request_text if analysis else ""),
        requested_format=(analysis.output_type if analysis else None),
        messages=messages,
    )
    if analysis is not None and analysis.audience_label:
        context.audience = context.audience or analysis.audience_label
    return context


# ============================================================== assembly
#: What wins when two sources say different things. Written down because the
#: merge below is per *field* — the data model fills one, the digest another,
#: the request a third — so there is no single line where "the user said X" and
#: "the file said X" meet, and the rule was previously only implicit in the
#: order of a few `or` expressions.
#:
#: 1. an explicit correction in the latest message
#: 2. explicit information in the latest message
#: 3. the latest source the user named as authoritative
#: 4. saved user corrections     (`digest.confirmed_values`, replayed into the
#:                                model by `analysis.replay_user_values`)
#: 5. earlier messages           (`request_history`, `relevant_chat_messages`)
#: 6. project knowledge          (`digest.free_text`, constraints)
#: 7. extracted source data      (`model`)
#: 8. model inference            (the planner, one layer up)
#:
#: Levels 1-2 are `current` and beat everything here. Level 4 beats level 7 by
#: construction: a correction is written *into* the model and put back after
#: every re-read, so by the time this function sees `model` the user's value is
#: already the one in it. What this ordering governs is the rest.
PRECEDENCE = (
    "latest_correction", "latest_message", "named_authoritative_source",
    "saved_corrections", "earlier_messages", "project_knowledge",
    "extracted_data", "model_inference",
)


def _assemble(*, scope: str, project_id, chat_id, session_id,
              model: PMIDataModel, digest: KnowledgeDigest, folder_name: str,
              quality, request_text: str, requested_format: Optional[str],
              messages: Sequence) -> GenerationContext:
    header = model.project
    companies = _companies(header, digest)
    history = request_history(messages)
    current = (request_text or latest_request(messages, "") or "").strip()
    if current and (not history or history[-1] != current):
        history = [*history, current]

    # §17: a structure the user described is the primary template. A structure
    # named in *this* turn wins over one remembered from three turns ago — the
    # same rule `request_history` follows — but "now make it a Word document"
    # names none, and before this the remembered order was simply lost.
    sections = requested_sections(current) or list(digest.requested_structure)
    context = GenerationContext(
        scope=scope,                                       # type: ignore[arg-type]
        project_id=project_id, chat_id=chat_id, session_id=session_id,
        project_name=resolve_project_name(header, folder_name, companies, current),
        project_context=digest.free_text,
        project_knowledge=digest,
        company_names=companies,
        transaction=_transaction(header),
        reporting_period=header.reporting_period or "",
        reporting_date=header.reporting_date,
        chat_summary=summarize_chat(messages),
        relevant_chat_messages=_excerpts(messages, current),
        user_request=current,
        request_history=history,
        requested_output_format=_normalized_format(current, requested_format),
        requested_sections=sections,
        requested_visuals=requested_visuals(current),
        audience=requested_audience(current),
        user_constraints=user_constraints(current, digest),
        evidence=projection.project(
            model, quality=quality,
            user_facts=digest.as_evidence_pairs(),
            user_values=digest.confirmed_values,
            requested_topics=sections,
        ),
        conflicts=list(model.conflicts),
        quality_issues=list(model.validation_issues),
        quality_report=quality,
        template_reference=_template(),
    )
    context.brand_system = getattr(context.template_reference, "brand", None)
    context.gaps = check_completeness(context)
    log.info("context for %s: %d evidence items, %d requested sections, "
             "%d gaps, name %r", project_id or session_id, len(context.evidence),
             len(context.requested_sections), len(context.gaps),
             context.project_name)
    return context


def _template():
    from app.templates import template_registry

    try:
        return template_registry.default()
    except Exception as exc:                                   # noqa: BLE001
        log.warning("no template reference available (%s)", exc)
        return None


def _excerpts(messages: Sequence, query: str) -> list[ChatExcerpt]:
    return relevant_messages(messages, query) if (messages and query) else []


# =============================================================== identity
def resolve_project_name(header: PMIProject, folder_name: str,
                         companies: CompanyNames, request: str) -> str:
    """The most specific real name available — or nothing, honestly.

    The old default was the literal string "PMI Project", which is
    indistinguishable downstream from a name somebody chose. Every deck, every
    filename and every title used it, including for projects whose acquirer and
    target were both on record.

    The deal name outranks the folder name because this resolves a *document*
    title: a folder called "Q3 stuff" is workspace organisation, while a deal
    called "Project Aurora" is what the transaction is known as internally.
    """
    for candidate in (header.project_name, header.deal_name, folder_name,
                      companies.as_phrase(), _title_in(request)):
        if candidate and candidate.strip():
            return candidate.strip()
    return ""


_TITLE_PATTERNS = (
    re.compile(r"\bfor (?:the )?([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})"
               r"\s+(?:integration|merger|acquisition|programme|program|deal)\b"),
    re.compile(r"\b([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})"
               r"\s+(?:integration|PMI)\b"),
)


def _title_in(request: str) -> str:
    for pattern in _TITLE_PATTERNS:
        match = pattern.search(request or "")
        if match:
            return match.group(1).strip()
    return ""


_MERGER_PATTERNS = (
    re.compile(r"(?P<a>[\w&.\-]+(?:\s+[\w&.\-]+){0,3})\s+is\s+(?:integrating|"
               r"acquiring|merging with)\s+(?P<b>[\w&.\-]+(?:\s+[\w&.\-]+){0,3})",
               re.I),
    re.compile(r"(?:integration|merger|acquisition) of\s+"
               r"(?P<b>[\w&.\-]+(?:\s+[\w&.\-]+){0,3})\s+by\s+"
               r"(?P<a>[\w&.\-]+(?:\s+[\w&.\-]+){0,3})", re.I),
)

#: Legal-form suffixes mark where a company name ends. Without them the greedy
#: capture above swallows the rest of the sentence.
_LEGAL_FORMS = re.compile(
    r"^(.*?\b(?:SE|AG|GmbH|PLC|Plc|Ltd|Limited|Inc|Corp|Corporation|NV|BV|SA|"
    r"SpA|AB|AS|Oy|KG|Co|LLC|LLP|SAS|SARL)\.?)\b", re.I)


#: Project-header fields the user can correct in chat, by the name
#: `nl_updates.apply_project_field` records them under.
_NAME_FIELDS = ("acquirer_name", "target_name", "deal_name", "project_name")


def _corrected_names(digest: KnowledgeDigest) -> dict[str, str]:
    """Company names the user has explicitly overruled, most recent last."""
    corrected: dict[str, str] = {}
    for fact in digest.confirmed_values:
        if fact.field in _NAME_FIELDS and fact.value:
            corrected[fact.field] = fact.value
    return corrected


def _companies(header: PMIProject, digest: KnowledgeDigest) -> CompanyNames:
    """Names from the project header, or read out of the user's own context.

    A user who wrote "MedAxis SE is integrating NordCare GmbH" in the project
    background has told us who this is about. Nothing used to read it.
    """
    # A name the user corrected outranks the header, which outranks a name read
    # out of their prose. `apply_project_field` writes both the stored project
    # and the in-memory one, so the header is normally already correct — this
    # keeps that true even when the two are written out of order.
    corrected = _corrected_names(digest)
    names = CompanyNames(
        acquirer=corrected.get("acquirer_name") or header.acquirer_name,
        target=corrected.get("target_name") or header.target_name,
        deal_name=corrected.get("deal_name") or header.deal_name)
    if names.acquirer and names.target:
        return names

    haystack = "\n".join([digest.free_text, *digest.confirmed_facts])
    for pattern in _MERGER_PATTERNS:
        match = pattern.search(haystack)
        if not match:
            continue
        acquirer, target = _trim(match.group("a")), _trim(match.group("b"))
        if acquirer and target:
            return CompanyNames(acquirer=names.acquirer or acquirer,
                                target=names.target or target,
                                deal_name=names.deal_name)
    return names


def _trim(name: str) -> str:
    name = " ".join((name or "").split()).strip(" .,;:")
    match = _LEGAL_FORMS.match(name)
    if match:
        return match.group(1).strip()
    # No legal form: keep at most three words, so a greedy match does not turn
    # half a sentence into a company name.
    return " ".join(name.split()[:3])


def _transaction(header: PMIProject) -> TransactionContext:
    today = header.reporting_date or date.today()
    day_1 = header.day_1_date
    return TransactionContext(
        integration_phase=str(getattr(header.integration_phase, "value",
                                      header.integration_phase)),
        integration_type=str(getattr(header.integration_type, "value",
                                     header.integration_type)),
        signing_date=header.signing_date,
        closing_date=header.closing_date,
        day_1_date=day_1,
        # Computed here, deterministically. The model is never asked to do
        # date arithmetic and then quote the result.
        days_to_day_1=(day_1 - today).days if day_1 else None,
    )


# ============================================== what the user explicitly asked
_SECTION_PREAMBLE = re.compile(
    r"\b(?:sections?|chapters?|slides?|topics?|cover(?:ing|s)?|"
    r"includ(?:e|ing|es)|containing|contains|with|comprising)\b\s*"
    r"(?::|\-|\bon\b|\babout\b)", re.I)
_NUMBERED = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(?P<text>.+?)\s*[.;]?$", re.M)
_INLINE_NUMBERED = re.compile(
    r"(?:(?<=\s)|^)\d{1,2}[.)]\s*(?P<text>.+?)(?=\s+\d{1,2}[.)]\s|\s*$)")
_STOP_SECTION = re.compile(
    r"^(?:and|then|also|please|thanks?|in|as|for|the|a|an)\b", re.I)


def requested_sections(request: str) -> list[str]:
    """The section titles the user named, verbatim and in order.

    Three shapes, in priority order: a numbered or bulleted list; a
    "sections: a, b, c" preamble; a semicolon-separated run. Anything else
    yields nothing here and is left to the request interpreter — guessing at
    prose would invent sections the user did not ask for, which is exactly the
    failure this redesign exists to end.
    """
    if not request:
        return []

    listed = [_clean_section(m.group("text")) for m in _NUMBERED.finditer(request)]
    listed = [s for s in listed if s]
    if len(listed) >= 2:
        return _dedupe(listed)

    # The same list typed on one line — "sections: 1. Risks 2. Budget 3.
    # Milestones" — which is how people write it in a chat box. Only attempted
    # after a "sections:" preamble, so a sentence that happens to contain
    # numbered clauses is not mistaken for a table of contents.
    match = _SECTION_PREAMBLE.search(request)
    if match:
        inline = [_clean_section(m.group("text"))
                  for m in _INLINE_NUMBERED.finditer(request[match.end():])]
        inline = [s for s in inline if s]
        if len(inline) >= 2:
            return _dedupe(inline)

    if match:
        tail = request[match.end():]
        # Stop at the next sentence, but not at the period in a section title
        # such as "Forecast vs. Actuals".
        tail = re.split(r"(?:(?<!vs)(?<!Vs)(?<!VS)\.\s+(?=[A-Z]))|\n\n",
                        tail, maxsplit=1)[0]
        parts = [_clean_section(p) for p in re.split(r"[;,]|\band\b", tail)]
        parts = [p for p in parts if p and not _STOP_SECTION.match(p)]
        if len(parts) >= 2:
            return _dedupe(parts)

    semis = [_clean_section(p) for p in request.split(";")]
    semis = [s for s in semis if s and 2 <= len(s.split()) <= 8]
    if len(semis) >= 3:
        return _dedupe(semis)

    # A title-cased run without commas is still an explicit structure when the
    # whole include-clause can be segmented into known report topics. The
    # guarded parser rejects partial/ambiguous prose rather than inventing a
    # table of contents from it.
    from app.report.structure import bare_topic_titles

    bare = bare_topic_titles(request)
    if len(bare) >= 2:
        return _dedupe(bare)
    return []


def _clean_section(text: str) -> str:
    text = " ".join((text or "").split()).strip(" .;:,-–—")
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.I)
    if not (2 <= len(text) <= 90):
        return ""
    return text


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


_VISUAL_WORDS = {
    "chart": "chart", "charts": "chart", "graph": "chart", "graphs": "chart",
    "waterfall": "waterfall", "bridge": "waterfall",
    "timeline": "timeline", "roadmap": "timeline", "gantt": "timeline",
    "heatmap": "heatmap", "heat map": "heatmap", "matrix": "matrix",
    "dashboard": "dashboard", "diagram": "diagram", "flow": "process_flow",
    "table": "table", "tables": "table", "kpi": "kpi", "kpis": "kpi",
    "scorecard": "kpi", "tree": "tree", "org chart": "org_chart",
}


def requested_visuals(request: str) -> list[str]:
    lowered = (request or "").casefold()
    found: list[str] = []
    for word, kind in _VISUAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered) and kind not in found:
            found.append(kind)
    return found


_AUDIENCE_PATTERNS = (
    re.compile(r"\bfor (?:the )?(?P<who>steering committee|steerco|board|"
               r"executive committee|exco|cfo|ceo|cio|coo|cto|cmo|chro|cpo|"
               r"cdo|clo|cso|ciso|management team|"
               r"leadership team|imo|pmo|integration management office|"
               r"workstream leads?|finance team|audit committee)\b", re.I),
    re.compile(r"\b(?P<who>steering committee|steerco|board|exco|cfo|ceo)\b"
               r"\s+(?:report|update|pack|presentation|deck)", re.I),
    # Preserve arbitrary spelled-out job titles rather than maintaining an
    # impossible exhaustive list (for example, "Chief People and Culture
    # Officer" or "HR Business Partner"). The terminal role noun keeps a topic
    # phrase such as "for supply chain" from being mistaken for a reader.
    re.compile(
        r"\bfor (?:the )?(?P<who>"
        r"(?:[\w&/-]+\s+){0,8}"
        r"(?:officer|director|manager|lead|leads|owner|partner|counsel|"
        r"president|executive|analyst|specialist|coordinator|architect|"
        r"engineer|team|committee|board|office))\b",
        re.I,
    ),
)


def requested_audience(request: str) -> Optional[str]:
    """The reader in the user's own words — not a four-value enum.

    "For the CFO" and "for the Steering Committee" are different documents, and
    collapsing both onto `Audience.EXECUTIVE` is what made every executive deck
    identical.
    """
    for pattern in _AUDIENCE_PATTERNS:
        match = pattern.search(request or "")
        if match:
            return " ".join(match.group("who").split()).strip()
    return None


_FORMAT_WORDS = (
    (re.compile(r"\b(powerpoint|pptx|deck|slides?|presentation)\b", re.I), "pptx"),
    (re.compile(r"\b(word|docx|document|report document)\b", re.I), "docx"),
    (re.compile(r"\b(pdf)\b", re.I), "pdf"),
    (re.compile(r"\b(html|dashboard|web page|webpage|interactive)\b", re.I), "html"),
    (re.compile(r"\b(chart|charts|graph|graphs|plot|image|png)\b", re.I), "chart"),
)


def _format(request: str) -> Optional[str]:
    for pattern, fmt in _FORMAT_WORDS:
        if pattern.search(request or ""):
            return fmt
    return None


def _normalized_format(request: str, stored: Optional[str]) -> Optional[str]:
    """The requested format in the renderers' vocabulary, or `None`.

    `SessionAnalysis.output_type` speaks the older words — "powerpoint",
    "excel" — and `OutputBrief.primary_format` is a closed literal, so passing
    one through unmapped raises a validation error deep inside planning where it
    reads as a model failure rather than as a vocabulary mismatch. `None` is a
    real answer here and must survive: it means the user did not say, which is
    the planner's cue to choose.
    """
    from app.renderers import registry

    raw = _format(request) or (stored or "")
    if not raw:
        return None
    key = raw.strip().casefold()
    return registry.ALIASES.get(key)


_MAX_PAGES = re.compile(
    r"\b(?:no more than|at most|maximum(?: of)?|max|under|within|keep it to)\s+"
    r"(\d{1,3})\s*(?:pages?|slides?)\b", re.I)
_EXACT_PAGES = re.compile(r"\b(\d{1,3})[- ](?:page|slide)\b", re.I)
_ONE_PAGER = re.compile(r"\bone[- ]pager\b", re.I)
_MIN_PAGES = re.compile(r"\b(?:at least|no fewer than|minimum(?: of)?)\s+"
                        r"(\d{1,3})\s*(?:pages?|slides?)\b", re.I)
_EXCLUDE = re.compile(r"\b(?:don'?t|do not|without|exclude|leave out|omit|no)\s+"
                      r"(?:include\s+|mention\s+)?(?P<what>[\w \-]{3,40})", re.I)
_LANGUAGE = re.compile(r"\bin (German|French|Dutch|Spanish|Italian|Portuguese|"
                       r"Polish|English)\b", re.I)
_TONE = re.compile(r"\b(blunt|direct|diplomatic|neutral|concise|detailed|"
                   r"high[- ]level|deep[- ]dive)\b", re.I)


def user_constraints(request: str, digest: KnowledgeDigest) -> list[UserConstraint]:
    """Hard rules the user stated, kept so the critic can verify them."""
    out: list[UserConstraint] = []
    text = request or ""

    if _ONE_PAGER.search(text):
        out.append(UserConstraint(kind="max_pages", value="1"))
    for pattern in (_MAX_PAGES, _EXACT_PAGES):
        match = pattern.search(text)
        if match:
            out.append(UserConstraint(kind="max_pages", value=match.group(1)))
            break
    match = _MIN_PAGES.search(text)
    if match:
        out.append(UserConstraint(kind="min_pages", value=match.group(1)))

    match = _LANGUAGE.search(text)
    if match:
        out.append(UserConstraint(kind="language", value=match.group(1)))
    match = _TONE.search(text)
    if match:
        out.append(UserConstraint(kind="tone", value=match.group(1).casefold()))

    for match in _EXCLUDE.finditer(text):
        what = " ".join(match.group("what").split()).strip(" .,;")
        if what and len(what.split()) <= 5:
            out.append(UserConstraint(kind="exclude_topic", value=what))

    if re.search(r"\bno charts?\b", text, re.I):
        out.append(UserConstraint(kind="no_charts", value="true"))

    # Standing instructions the user pinned to the project apply to every
    # deliverable, not just the turn that mentioned them.
    for line in digest.free_text.splitlines():
        if re.match(r"\s*(?:always|never|standing instruction)\b", line, re.I):
            out.append(UserConstraint(kind="other", value=line.strip(),
                                      source="project_knowledge"))
    return out


# ============================================================== knowledge
def _project_digest(knowledge, record) -> KnowledgeDigest:
    """`ProjectKnowledge` + the folder's free text, in one shape."""
    digest = KnowledgeDigest(free_text=(record.knowledge if record else "") or "")
    if knowledge is None:
        return digest
    digest.confirmed_facts = [f.text for f in knowledge.confirmed_user_facts if f.text]
    digest.assumptions = [a.text for a in knowledge.assumptions if a.text]
    digest.open_questions = [q.text for q in knowledge.open_questions if q.text]
    digest.decisions = [_decision_text(d) for d in knowledge.user_decisions]
    digest.decisions = [d for d in digest.decisions if d]
    digest.requested_structure = list(knowledge.requested_structure)
    return digest


def _decision_text(decision) -> str:
    detail = decision.detail or {}
    if decision.kind == "conflict_resolution":
        chosen = detail.get("value") or detail.get("resolved_value")
        source = detail.get("source") or detail.get("resolved_from")
        if chosen:
            return (f"The user resolved a source conflict to {chosen}"
                    + (f" (from {source})." if source else "."))
        return ""
    field, value = detail.get("field"), detail.get("value")
    if field and value is not None:
        return f"The user confirmed {field} = {value}."
    return ""


def _session_digest(kb) -> KnowledgeDigest:
    """`KnowledgeBase` in the same shape. This is `digest()`'s first caller."""
    digest = KnowledgeDigest(free_text="\n".join(kb.notes) if kb.notes else "")
    digest.confirmed_facts = [
        f"{value.label or value.field}: {value.value}"
        for value in kb.user_values
        if getattr(value, "value", None) is not None
    ]
    digest.declined = list(kb.declined_gaps)
    digest.requested_structure = _structure_titles(kb.structure)
    digest.confirmed_values = [
        UserFact(entity_type=value.entity_type, label=value.label,
                 field=value.field,
                 value=None if value.value is None else str(value.value),
                 old_value=getattr(value, "old_value", None))
        for value in kb.user_values
        if getattr(value, "value", None) is not None
    ]
    # Project-header corrections — the reporting date, Day 1, the company names.
    # `record_project_field` writes these to `kb.project_fields`, which nothing
    # projected: a corrected target name reached the digest neither as a fact
    # nor as a value, so the only reason it survived was that
    # `apply_project_field` happens to write the stored `PMIProject` too.
    digest.confirmed_values += [
        UserFact(entity_type="project", label="", field=field,
                 value=None if value is None else str(value))
        for field, value in (kb.project_fields or {}).items()
        if value is not None
    ]
    return digest


def _merge_digests(project: KnowledgeDigest,
                   session: KnowledgeDigest) -> KnowledgeDigest:
    """Project background plus the chat's newer, authoritative corrections."""
    return KnowledgeDigest(
        free_text="\n\n".join(
            text for text in (project.free_text, session.free_text)
            if text.strip()),
        confirmed_facts=[
            *project.confirmed_facts, *session.confirmed_facts],
        assumptions=[*project.assumptions, *session.assumptions],
        decisions=[*project.decisions, *session.decisions],
        open_questions=[
            *project.open_questions, *session.open_questions],
        declined=[*project.declined, *session.declined],
        confirmed_values=[
            *project.confirmed_values, *session.confirmed_values],
        requested_structure=(
            session.requested_structure or project.requested_structure),
    )


def _structure_titles(structure) -> list[str]:
    """The section titles of a structure the user described, in their order.

    `kb.structure` is stored untyped so `report.structure` can own the schema.
    Reading it defensively here keeps a malformed or half-written spec from
    breaking generation — the worst case is that the remembered structure is
    ignored for this turn, which is what happened for every turn before this.
    """
    if not isinstance(structure, dict):
        return []
    titles: list[str] = []
    for section in structure.get("sections") or []:
        title = (section or {}).get("title") if isinstance(section, dict) else None
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


# ============================================================ completeness
def check_completeness(context: GenerationContext) -> list[ContextGap]:
    """What would make this deliverable wrong or impossible, stated plainly."""
    gaps: list[ContextGap] = []

    if not context.has_evidence:
        gaps.append(ContextGap(
            gap_id="no_evidence", severity="block",
            message="There is nothing to report on yet — no file has been read "
                    "and no fact has been recorded for this project.",
            remedy="Upload the trackers, status decks or exports you want the "
                   "report built from."))

    if not context.user_request.strip():
        gaps.append(ContextGap(
            gap_id="no_request", severity="warn",
            message="No request was captured, so the document was planned from "
                    "the project's contents rather than from what you asked for.",
            remedy="Say what the document is for and who will read it."))

    blocking = context.unresolved_critical_conflicts
    if blocking:
        subjects = ", ".join(sorted({c.entity_key for c in blocking})[:3])
        gaps.append(ContextGap(
            gap_id="unresolved_conflicts", severity="block",
            message=f"{len(blocking)} unresolved conflict(s) affect figures this "
                    f"report would state ({subjects}). Publishing now would "
                    f"present one source's number as agreed fact.",
            remedy="Resolve them, or generate with `force` to publish with the "
                   "disagreement disclosed on the page."))

    if not context.project_name and not context.company_names.known:
        gaps.append(ContextGap(
            gap_id="unnamed_project", severity="warn",
            message="This project has no name and no company names on record, so "
                    "the document cannot title itself accurately.",
            remedy="Name the project, or add the acquirer and target to the "
                   "project background."))

    reference = context.template_reference
    if reference is not None and not getattr(reference, "available", True):
        gaps.append(ContextGap(
            gap_id="no_template", severity="warn",
            message="The Deloitte master template could not be read, so slides "
                    "will not carry the brand background, logo or typography.",
            remedy="Restore app/assets/templates/Deloitte_Master.pptx."))

    if context.quality_report is not None:
        score = getattr(context.quality_report, "score", None)
        if score is not None and score < 60:
            gaps.append(ContextGap(
                gap_id="low_quality", severity="warn",
                message=f"The source data scores {score:.0f}/100 for completeness "
                        f"and consistency; conclusions drawn from it are "
                        f"correspondingly provisional.",
                remedy="Fill the gaps listed in the data-quality report, or "
                       "expect the document to state its own limitations."))

    return gaps
