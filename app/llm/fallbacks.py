"""Deterministic answers for every LLM task, used when no provider is configured
or a call fails.

These are the heuristics from the original `app/agent/llm.py`, kept intact. They
are honest-but-dumb: keyword matching and template prose. Every use is recorded as
a warning by the caller in `tasks.py`, so a run that fell back says so in its
data-quality report (§21.17) rather than passing template text off as analysis.
"""
from __future__ import annotations

import re

from app.llm.schemas import RequestParse, SummaryBullets
from app.models.pmi import Audience, PMIDataModel

_REQUEST_HINTS: dict[str, list[str]] = {
    "powerpoint": ["powerpoint", "pptx", "slide", "deck", "presentation", "steerco",
                   "steering", "präsentation"],
    "excel": ["excel", "xlsx", "dashboard", "spreadsheet", "sheet", "tabelle"],
    "chart": ["chart", "charts", "graph", "plot", "diagramm", "diagram", "figure",
              "visual", "image", "images", "picture", "png"],
}

#: The one audience map, shared with `conversation._match_audience` (§4/§9).
#:
#: When more than one hint appears, the most specific (longest) phrase wins.
#: That keeps "Finance Director" in Finance rather than allowing the generic
#: word "director" to turn it into an Executive report.
#:
#: Kept wide on purpose. §4 says to ask when the audience *cannot be inferred*;
#: asking about "a deck for the Integration Director" is not carefulness, it is
#: the agent failing to read a title that names its reader unambiguously.
_AUDIENCE_HINTS: dict[Audience, list[str]] = {
    Audience.EXECUTIVE: ["executive", "executives", "steerco", "steering",
                         "steering committee", "steering board", "c-level",
                         "board", "management", "senior management",
                         "leadership", "ceo", "coo", "cio", "cto", "cmo",
                         "chro", "cpo", "cdo", "clo", "cso", "ciso",
                         "chief executive officer", "chief operating officer",
                         "chief information officer", "chief technology officer",
                         "chief marketing officer", "chief human resources officer",
                         "chief hr officer", "chief people officer",
                         "chief data officer", "chief legal officer",
                         "chief strategy officer", "chief information security officer",
                         "president", "vice president", "vp", "svp", "evp",
                         "managing director", "general counsel", "sponsor",
                         "integration director", "director", "geschäftsführung",
                         "vorstand", "lenkungsausschuss"],
    Audience.FINANCE: ["finance", "finances", "financial", "budget", "cost",
                       "costs", "controlling", "cfo", "chief financial officer",
                       "finance director", "finance manager", "controller",
                       "comptroller", "treasurer", "treasury", "fp&a",
                       "accounting", "accountant", "finanz"],
    Audience.WORKSTREAM: ["workstream", "workstreams", "work stream",
                          "work streams", "workstream lead",
                          "workstream leads", "stream lead", "teilprojekt"],
    Audience.PMO: ["pmo", "imo", "project office", "integration office",
                   "integration management office", "programme office",
                   "program office", "transformation office", "programme manager",
                   "program manager", "project manager", "portfolio manager",
                   "integration manager", "pmi lead", "detailed", "team", "operational",
                   "projektbüro"],
}


def match_audience(text: str) -> Audience | None:
    """Resolve a named reader to one of the four internal report shapes.

    The user's title remains free text; :class:`Audience` is only the closest
    planning shape.  Exact phrases win over generic words (so ``Finance
    Director`` is Finance rather than Executive merely because it contains
    ``director``), then title patterns cover roles that cannot reasonably be
    enumerated one by one.
    """
    lowered = (text or "").casefold()
    matches: list[tuple[int, int, Audience]] = []
    for order, (audience, keywords) in enumerate(_AUDIENCE_HINTS.items()):
        for keyword in keywords:
            if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", lowered):
                matches.append((len(keyword), -order, audience))
    if matches:
        return max(matches)[2]

    # C-suite titles are executive readers even when the particular function
    # is new to our vocabulary. Finance is kept separate because its document
    # shape is materially different.
    if re.search(r"\bchief\s+(?:finance|financial|accounting)\b.{0,40}\bofficer\b",
                 lowered):
        return Audience.FINANCE
    if re.search(r"\bchief\b.{1,60}\bofficer\b", lowered):
        return Audience.EXECUTIVE

    if re.search(
        r"\b(?:senior\s+)?(?:programme|program|project|portfolio|integration|"
        r"transformation)\s+(?:director|manager|lead|officer|coordinator)\b",
        lowered,
    ):
        return Audience.PMO

    if re.search(
        r"\b(?:head\s+of|vice\s+president\s+(?:of|for)|vp\s+(?:of|for)|"
        r"managing\s+director|general\s+counsel)\b",
        lowered,
    ):
        return Audience.EXECUTIVE

    # A named functional role needs the detailed, domain-specific workstream
    # shape. Requiring an actual role noun avoids treating a report *about*
    # supply chain or HR as if its reader had been supplied.
    if re.search(
        r"\b(?:human\s+resources|hr|people|legal|it|technology|operations|"
        r"procurement|supply\s+chain|sales|marketing|communications?|change|"
        r"cyber(?:security)?|data|tax|product|engineering)\b.{0,50}\b"
        r"(?:business\s+partner|manager|lead|owner|analyst|specialist|"
        r"coordinator|counsel|architect|engineer|team)\b",
        lowered,
    ):
        return Audience.WORKSTREAM
    return None


def heuristic_parse(request_text: str) -> RequestParse:
    text = request_text.lower()

    def has_kw(keywords: list[str]) -> bool:
        # Word-boundary match so "board" does not fire inside "dashboard".
        return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)

    output_type = next(
        (ot for ot, kws in _REQUEST_HINTS.items() if has_kw(kws)), "powerpoint"
    )
    audience = match_audience(text)
    # The topic steers which charts an image request produces (see
    # `charts.generate`), so "an image of the milestones and project plan" has
    # to land on "milestone", not the "status" catch-all — otherwise the picture
    # shows workstream progress and the user's actual words are ignored.
    topic = "status"
    for needle, name in (
        (("risk", "risiko"), "risks"),
        (("milestone", "timeline", "project plan", "roadmap", "go-live",
          "go live", "day 1", "day-1"), "milestone"),
        (("budget", "cost", "spend"), "budget"),
        (("synerg",), "synergy"),
        (("depend",), "dependency"),
    ):
        if any(word in text for word in needle):
            topic = name
            break
    return RequestParse(output_type=output_type, audience=audience, topic=topic)


def template_summary(model: PMIDataModel, audience: Audience) -> SummaryBullets:
    bullets: list[str] = []

    progress = model.overall_progress()
    kpi_progress = next(
        (k.current_value for k in model.kpis
         if "progress" in k.name.lower() and k.current_value is not None),
        None,
    )
    shown = kpi_progress if kpi_progress is not None else progress
    if shown is not None:
        bullets.append(
            f"Overall integration progress stands at {shown:.0f}% "
            f"across {len(model.source_files)} reporting source(s)."
        )

    if model.tasks:
        bullets.append(
            f"{len(model.tasks)} tracked tasks, {len(model.open_tasks())} open; "
            f"{len(model.tasks_by_owner())} owner(s) carry assignments."
        )

    if model.risks:
        severe = [r for r in model.risks if r.rating.value in ("high", "critical")]
        bullets.append(
            f"{len(model.risks)} risks logged, {len(severe)} rated high or critical "
            f"— mitigation owners are assigned in the risk log."
        )

    if model.conflicts:
        auto = sum(1 for c in model.conflicts if c.resolution == "source_priority")
        by_user = sum(1 for c in model.conflicts
                      if c.resolution in ("user", "user_value"))
        unresolved = len(model.unresolved_conflicts())

        parts = []
        if auto:
            parts.append(f"{auto} auto-resolved by source priority")
        if by_user:
            parts.append(f"{by_user} decided by the user")
        if unresolved:
            parts.append(f"{unresolved} still UNRESOLVED")

        bullets.append(
            f"{len(model.conflicts)} cross-source inconsistency/inconsistencies "
            f"detected: {', '.join(parts)}."
        )

    if audience == Audience.FINANCE and model.budget:
        planned = sum(b.budget or 0 for b in model.budget)
        actual = sum(b.actual or 0 for b in model.budget)
        consumed = (actual / planned * 100) if planned else 0
        bullets.append(
            f"Budget: {actual:,.0f} EUR spent against {planned:,.0f} EUR planned "
            f"({consumed:.0f}% consumed)."
        )

    if not bullets:
        bullets.append("No structured PMI data found in the uploaded files.")
    return SummaryBullets(bullets=bullets)
