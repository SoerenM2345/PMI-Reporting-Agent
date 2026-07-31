"""A report structure the *user* asked for, as the primary template.

`DECKS` in `planner.py` is the §12.1-12.4 house template — a good default, and
until now the only possible answer. Someone who wrote out the sections they
wanted got the house deck anyway, which reads as the tool not having listened.

So a request that describes a structure produces one, and it becomes the order
for **every** format: the deck, the workbook, the document and the preview all
plan from the same `ReportContent`, so there is nowhere for the structure to
apply to one and not another.

Two rules hold regardless of what was asked for:

* **A requested section that no source covers still appears**, saying plainly
  that nothing in the files speaks to it (§21.17). Dropping it silently would
  let a reader conclude the topic was fine.
* **`quality.limitations` is always appended and cannot be removed.** §12.5 is
  not a section the user is choosing between; it is what the document says about
  its own reliability.

Detection is LLM-first with a deterministic fallback, the same discipline as the
rest of the pipeline — a numbered or bulleted list in the prompt is parsed
without any model at all, so this works with no API key.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from pydantic import BaseModel, Field

log = logging.getLogger("pmi.report.structure")


class SectionSpec(BaseModel):
    """One section the user asked for, in their words."""

    title: str
    #: The builder this maps to, once matched. `None` means "no source data
    #: covers this" — the section is still emitted, saying so.
    section_id: Optional[str] = None
    hint: str = ""


class StructureSpec(BaseModel):
    sections: list[SectionSpec] = Field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.sections)


# ============================================================ detection
#: A line that is plausibly a section title in a list: "1. Risks", "- Budget",
#: "• Milestones", "Risks and issues" inside an indented block.
_LIST_LINE = re.compile(r"^\s*(?:\d+[.)]\s+|[-*•·]\s+)(?P<title>.+?)\s*$")

#: The phrasings that introduce a structure. Without one of these, a numbered
#: list is just a list — "1. read the tracker 2. tell me what's wrong" is not a
#: table of contents, and treating it as one would produce a nonsense report.
_INTRODUCES = re.compile(
    r"\b(structure|sections?|chapters?|agenda|table of contents|contents|"
    r"outline|following order|in this order|with these|should (?:contain|include|"
    r"have)|organi[sz]ed as|broken (?:down |up )?into)\b", re.I,
)

#: Words that mark a line as an instruction rather than a section title.
_NOT_A_TITLE = re.compile(
    r"\b(please|generate|create|make|build|send|email|upload|then|after that|"
    r"read|check|tell me|let me know)\b", re.I,
)


def detect(request_text: str, *, provider: str = "", model: str = "") -> Optional[
        StructureSpec]:
    """The structure the request describes, or `None`.

    Returning `None` is the common case and the important one: most requests
    describe a *report*, not a structure, and inventing one from an ordinary
    sentence would override the house template for no reason.
    """
    text = (request_text or "").strip()
    if not text:
        return None

    # Explicit lists and headings are syntax, not a semantic task. The complete
    # report call sees the verbatim request and handles any implicit structure.
    # Keeping a separate model call here made every report request slower before
    # planning had even started.
    return _detect_deterministically(text)


def _detect_with_llm(text: str, provider: str, model: str) -> Optional[StructureSpec]:
    from app.llm import LLMError, get_client

    client = get_client(provider or None)
    if client.name == "none":
        return None

    try:
        found = client.structured(
            system=_SYSTEM, user=text, output_model=StructureSpec, model=model or None,
        )
    except LLMError as exc:
        log.warning("structure detection failed (%s); using the deterministic "
                    "parser", exc)
        return None

    # The model may only name titles — never let it choose a builder, because a
    # `section_id` it invented would silently select the wrong data.
    return StructureSpec(sections=[
        SectionSpec(title=s.title.strip(), hint=s.hint)
        for s in found.sections if s.title and s.title.strip()
    ]) or None


_SYSTEM = """You extract a report's requested SECTION STRUCTURE from a request.

Return the sections the user asked for, in the order they asked for them, using
their own words as the title. Return an empty list when the request does not
describe a structure — most do not. Never invent sections the user did not name,
and never return a section_id."""


#: An inline numbered list — "1. Risks 2. Budget 3. Milestones" — all on one
#: line, which is how people actually type a short structure into a chat box.
#: Each title runs up to the next "<n>." marker or the end.
_INLINE_ITEM = re.compile(r"\d+[.)]\s*(?P<title>.+?)(?=\s+\d+[.)]|\s*$)")


def _detect_deterministically(text: str) -> Optional[StructureSpec]:
    """A numbered or bulleted list, when something in the text says it is one."""
    if not _INTRODUCES.search(text):
        return None

    titles = _multiline_titles(text) or _inline_titles(text)
    if len(titles) < 2:
        # One "section" is a mention, not a structure.
        return None
    return StructureSpec(sections=[SectionSpec(title=t) for t in titles])


def _multiline_titles(text: str) -> list[str]:
    titles: list[str] = []
    for line in text.splitlines():
        match = _LIST_LINE.match(line)
        if not match:
            continue
        title = match.group("title").strip(" .;:")
        if title and not _NOT_A_TITLE.search(title) and len(title) <= 60:
            titles.append(title)
    return titles


def _inline_titles(text: str) -> list[str]:
    """"…sections: 1. Risks 2. Budget 3. Milestones" on one line.

    Anchored after the introducing phrase so a stray "…by Q3 2026" earlier in
    the sentence is not mistaken for item 3.
    """
    intro = _INTRODUCES.search(text)
    tail = text[intro.end():] if intro else text
    # Drop a trailing "for the steering committee" style clause so it does not
    # get swept into the last section's title.
    tail = re.split(r"\bfor (?:the |a )?[a-z]", tail, maxsplit=1)[0]

    titles: list[str] = []
    for match in _INLINE_ITEM.finditer(tail):
        title = match.group("title").strip(" .;:,")
        if title and not _NOT_A_TITLE.search(title) and len(title) <= 60:
            titles.append(title)
    return titles


# ============================================================ matching
#: Words a user uses for a section → the builder that produces it. Checked
#: before fuzzy matching, because "financials" and "finance.summary" share
#: little as strings and everything as meaning.
ALIASES: dict[str, tuple[str, ...]] = {
    "summary.executive": ("executive summary", "summary", "management summary",
                          "overview", "exec summary", "key messages",
                          "highlights"),
    "status.overall": ("status", "overall status", "integration status",
                       "status at a glance", "dashboard", "kpis", "scorecard"),
    "workstream.scorecard": ("workstreams", "workstream status",
                             "workstream scorecard", "by workstream",
                             "workstream progress"),
    "risks.critical": ("risks", "risk", "critical risks", "top risks",
                       "risks and issues", "risk register"),
    "milestones": ("milestones", "milestone", "timeline", "key dates",
                   "project plan", "plan", "schedule", "roadmap", "go-live"),
    "tasks.overdue": ("overdue", "overdue tasks", "overdue activities",
                      "late items", "slippage"),
    "dependencies": ("dependencies", "cross-workstream dependencies",
                     "interdependencies"),
    "decisions": ("decisions", "decisions required", "decisions needed",
                  "asks", "escalations"),
    "finance.summary": ("finance", "financials", "financial status",
                        "financial summary", "synergies and budget"),
    "finance.budget_detail": ("budget", "budget detail", "cost", "costs",
                              "spend", "budget vs actual"),
    "finance.synergies": ("synergies", "synergy", "synergy realization",
                          "value capture", "benefits"),
    "finance.risks": ("financial risks", "risks with financial impact"),
    "pmo.missing_updates": ("missing updates", "data gaps", "non-reporting",
                            "who hasn't reported"),
    "actions": ("actions", "action items", "actions and owners", "next actions",
                "to do"),
    "next_steps": ("next steps", "way forward", "recommendations",
                   "what happens next"),
    "quality.limitations": ("data quality", "limitations", "caveats",
                            "assumptions", "how this was produced"),
}

#: Charts a user may ask for by name.
CHART_ALIASES: dict[str, tuple[str, ...]] = {
    "chart.workstream_progress": ("workstream progress chart", "progress chart"),
    "chart.tasks_by_status": ("tasks by status", "task status chart"),
    "chart.budget_vs_actual": ("budget vs actual chart", "budget chart"),
    "chart.synergy_target_vs_realized": ("synergy chart",
                                         "target vs realized chart"),
}

#: How close a fuzzy match must be before it counts. Below this a requested
#: title is treated as unmatched — which produces a section that says no source
#: covers it, and that is a better answer than confidently showing the wrong
#: data under the user's heading.
_FUZZY_FLOOR = 0.72


def match(title: str, available: set[str]) -> Optional[str]:
    """Which builder the user's words mean, or `None`."""
    wanted = _normalise(title)
    if not wanted:
        return None

    everything = {**ALIASES, **CHART_ALIASES}

    # An exact alias, or the section id itself.
    for section_id, aliases in everything.items():
        if section_id not in available:
            continue
        if wanted == _normalise(section_id) or wanted in {_normalise(a)
                                                          for a in aliases}:
            return section_id

    # Containment: "critical risks and issues" contains "critical risks".
    for section_id, aliases in everything.items():
        if section_id not in available:
            continue
        for alias in aliases:
            normalised = _normalise(alias)
            if len(normalised) >= 5 and (normalised in wanted or wanted in normalised):
                return section_id

    # Fuzzy, as the last resort and with a floor.
    best: Optional[tuple[float, str]] = None
    for section_id, aliases in everything.items():
        if section_id not in available:
            continue
        for candidate in (section_id, *aliases):
            score = SequenceMatcher(None, wanted, _normalise(candidate)).ratio()
            if score >= _FUZZY_FLOOR and (best is None or score > best[0]):
                best = (score, section_id)
    return best[1] if best else None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower().replace(".", " ")).strip()
