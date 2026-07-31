"""One question, one source of truth — the intent-to-answer router.

`conversation._explain_issues` used to be the single handler for every finding
word a user might type. Ask "what are the gaps?" and you got the validation-issue
list; ask "what conflicts are there?" and you got the same list again with the
conflicts on top. The words are not synonyms in this domain, and answering the
wrong one is worse than saying "I don't know": the user takes the answer at face
value and acts on the wrong finding.

So each question is routed to exactly the collection it is about:

    gaps / missing values     quality_report.missing_fields + corrections.fillable
    issues                    model.issues            (the PMI entity)
    validation / data quality model.validation_issues (the §8 checks)
    conflicts                 model.unresolved_conflicts()
    risks / milestones / …    the matching collection, phrased by report/messages
    "why is the score N/100?" data_quality.explain

Two rules hold for every answer below:

* **Only the named source.** A gaps answer never reaches into validation issues
  to look fuller. If the collection is empty, that is the answer.
* **One closing action line, about this answer.** No unrelated suggestions —
  a list of things the user did not ask about buries the thing they did.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from app.report import chat_format as chat
from app.report import format as fmt
from app.report import messages

#: Question kinds this module can answer, most specific pattern first — "data
#: quality issues" must not be swallowed by the bare "issues" pattern.
_ROUTES: list[tuple[str, re.Pattern]] = [
    # Always requires the literal word "score". A looser pattern matching bare
    # "quality" swallowed "what data-quality issues did you find?" and answered
    # a question about findings with an explanation of a number.
    ("score", re.compile(r"\bscored?\b|\b\d{1,3}\s*/\s*100\b", re.I)),
    ("validation", re.compile(
        r"\b(data[- ]quality|validation|data)\b.{0,15}\b(issue|issues|problem|"
        r"problems|finding|findings|check|checks)\b", re.I)),
    ("conflicts", re.compile(
        r"\b(conflict|conflicts|disagree\w*|discrepanc\w*|inconsistenc\w*|"
        r"contradict\w*|mismatch\w*)\b", re.I)),
    ("gaps", re.compile(
        r"\b(gap|gaps|missing|blank|blanks|incomplete|not reported|unfilled|"
        r"unknown)\b", re.I)),
    ("risks", re.compile(r"\brisks?\b", re.I)),
    ("milestones", re.compile(r"\bmilestones?\b|\bgo[- ]lives?\b", re.I)),
    ("decisions", re.compile(r"\bdecisions?\b", re.I)),
    ("budget", re.compile(r"\bbudgets?\b|\bspend\b|\bcosts?\b|\bfinancials?\b",
                          re.I)),
    ("synergies", re.compile(r"\bsynerg\w+\b", re.I)),
    ("tasks", re.compile(r"\btasks?\b|\bactivit\w+\b|\bactions?\b|\boverdue\b",
                         re.I)),
    ("workstreams", re.compile(r"\bworkstreams?\b|\bwork ?streams?\b", re.I)),
    ("dependencies", re.compile(r"\bdependenc\w+\b", re.I)),
    ("issues", re.compile(r"\bissues?\b|\bproblems?\b|\bblockers?\b", re.I)),
]

#: A message is only routed here when it *asks* something. "Drop the risks
#: section" mentions risks and is an instruction, not a question about them.
_ASKING = re.compile(
    r"\?|\b(what|which|why|how many|how much|list|show|tell me|explain|"
    r"describe|any|are there|is there|do you see|did you find|summar\w+)\b",
    re.I,
)

_INSTRUCTION = re.compile(
    r"^\s*(please\s+)?(add|remove|drop|delete|move|reorder|rename|shorten|"
    r"generate|create|make|build|render|export|download|produce|put|set|change|"
    r"update|fix|correct)\b", re.I,
)


def classify(text: str) -> Optional[str]:
    """Which question this is, or `None` when it is not one of ours.

    Returning `None` matters as much as returning a kind: a message this module
    does not recognise must fall through to normal routing rather than being
    answered with the nearest-looking collection.
    """
    message = (text or "").strip()
    if not message or _INSTRUCTION.match(message):
        return None
    if not _ASKING.search(message):
        return None
    for kind, pattern in _ROUTES:
        if pattern.search(message):
            return kind
    return None


def answer(kind: str, analysis) -> str:
    """The answer text for a kind `classify` returned."""
    handler: Callable = _HANDLERS.get(kind, _unknown)
    return handler(analysis)


# ------------------------------------------------------------------- handlers
def _gaps(analysis) -> str:
    """Values the files never stated — and *only* those.

    Two sources, both about absence: the quality report's human-readable roll-up,
    and the individual completeness issues a person can actually answer. It
    deliberately does not fall back to `validation_issues` when both are empty;
    "no gaps" is a real answer and the most useful one there is.
    """
    from app.agent.corrections import fillable

    model = analysis.data_model
    report = analysis.quality_report
    summary = list(getattr(report, "missing_fields", []) or [])
    answerable = fillable(model.validation_issues)

    if not summary and not answerable:
        return chat.reply(
            "No gaps",
            body=["Every field the report needs was stated in the files."],
            action="Ask me for the report whenever you're ready.",
        )

    body: list[str] = []
    if summary:
        body += chat.bullets(summary)
    if answerable:
        if body:
            body.append("")
        body.append(f"**{chat.count(len(answerable), 'value')} only you can fill:**")
        body += chat.bullets(
            f"{i.entity_label or i.entity_id} — {(i.field or '').replace('_', ' ')}"
            for i in answerable
        )

    action = ("Say “fill the gaps” and I'll ask for them one at a time, or give me "
              "one directly — “the owner is Anna Schmidt”."
              if answerable else
              "Tell me any of these values and I'll write them in.")
    return chat.reply(f"{chat.count(len(summary) or len(answerable), 'gap')} in the data",
                      body=body, action=action)


def _validation(analysis) -> str:
    """The §8 checks — what a source got wrong, grouped by family."""
    from collections import Counter

    issues = list(analysis.data_model.validation_issues)
    if not issues:
        return chat.reply(
            "No data-quality issues",
            body=["Every §8 consistency check passed on these files."],
            action="Ask me about the gaps if you want to know what was never "
                   "stated at all.",
        )

    by_family: dict[str, list] = {}
    for issue in issues:
        by_family.setdefault(issue.family, []).append(issue)

    body: list[str] = []
    for family, found in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        body.append(f"**{family.replace('_', ' ').title()}** "
                    f"({chat.count(len(found), 'issue')})")
        body += chat.bullets((i.message for i in found), limit=6)
        body.append("")

    counted = Counter(i.family for i in issues)
    from app.agent.corrections import fillable

    action = ("Say “fill the gaps” to answer the ones a person can fix."
              if fillable(issues) else
              "These are contradictions in the sources rather than blanks — the "
              "figures I could recompute, I already have.")
    return chat.reply(
        f"{chat.count(len(issues), 'data-quality issue')} "
        f"across {chat.count(len(counted), 'check family', 'check families')}",
        body=[line for line in body if line is not None],
        action=action,
    )


def _conflicts(analysis) -> str:
    """Where two documents state different values for the same thing."""
    model = analysis.data_model
    unresolved = model.unresolved_conflicts()
    resolved = [c for c in model.conflicts if c.is_resolved]

    if not unresolved:
        body = ([f"All {chat.count(len(resolved), 'conflict')} that were detected "
                 f"have been decided."] if resolved else
                ["No two sources disagree about the same value."])
        return chat.reply("No open conflicts", body=body,
                          action="The figures in the report are agreed.")

    body: list[str] = []
    for conflict in unresolved[:chat.MAX_ITEMS]:
        body.append(f"• **{conflict.entity_key} — {conflict.field}**")
        for evidence in getattr(conflict, "evidence", [])[:4]:
            where = getattr(evidence, "file_name", None) or "unknown source"
            body.append(f"    · {where}: {evidence.value}")
        if not getattr(conflict, "evidence", None):
            body.append(f"    · {conflict.message}")
    if len(unresolved) > chat.MAX_ITEMS:
        body.append(f"…and {len(unresolved) - chat.MAX_ITEMS} more.")

    return chat.reply(
        f"{chat.count(len(unresolved), 'unresolved conflict')}",
        body=body,
        action="Tell me which value is right — “the progress is 82%” — or pick a "
               "source on the conflict card and I'll apply it everywhere.",
    )


def _issues(analysis) -> str:
    """`model.issues`: the PMI entity, not a validation finding.

    The distinction is the whole reason this handler exists. An Issue is
    something the integration team is managing; a ValidationIssue is something
    wrong with the *file*. Answering "which issues do you see?" with the latter
    tells a PMO their tracker is broken when they asked what is blocking Day 1.
    """
    issues = list(analysis.data_model.issues)
    if not issues:
        return chat.reply(
            "No issues are logged",
            body=["No source file recorded an open integration issue."],
            action="Ask about the data-quality issues if you meant problems with "
                   "the files themselves.",
        )

    open_issues = [i for i in issues if i.status.is_open]
    ordered = sorted(open_issues or issues,
                     key=lambda i: _SEVERITY_ORDER.get(i.severity.value, 9))
    body = chat.bullets(
        f"**{i.title}** — {i.severity.value} · "
        f"{i.owner or '⚠ no owner'} · due {fmt.date_str(i.due_date, missing='—')}"
        for i in ordered
    )
    return chat.reply(
        f"{chat.count(len(open_issues), 'open issue')} of {len(issues)} logged",
        body=body,
        action="Tell me an owner or a due date for any of these and I'll write it "
               "in — “the owner of the TSA exit is Anna Schmidt”.",
    )


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _risks(analysis) -> str:
    model = analysis.data_model
    risks = sorted([r for r in model.risks if r.status.is_open],
                   key=lambda r: (r.risk_score or 0), reverse=True)
    if not risks:
        return chat.reply("No open risks",
                          body=["No source file recorded an open risk."],
                          action="Ask me for the report whenever you're ready.")
    body = chat.bullets(
        f"**{r.title}** — {r.rating.value} · score "
        f"{r.risk_score if r.risk_score is not None else 'not scored'} · "
        f"{r.owner or '⚠ no owner'}"
        for r in risks
    )
    unmitigated = [r for r in risks if not r.mitigation_action]
    action = (f"{chat.count(len(unmitigated), 'risk')} still "
              f"{'has' if len(unmitigated) == 1 else 'have'} no mitigation — "
              f"tell me the action and owner and I'll record it."
              if unmitigated else
              "Every open risk has a mitigation recorded.")
    return chat.reply(messages.risk_message(model), body=body, action=action)


def _milestones(analysis) -> str:
    model = analysis.data_model
    if not model.milestones:
        return chat.reply("No milestones",
                          body=["No source file recorded a milestone."],
                          action="Upload a plan or tracker and I'll read them in.")
    ordered = sorted(model.milestones, key=lambda m: (m.delay_days or 0),
                     reverse=True)
    body = chat.bullets(
        f"**{m.name}** — planned {fmt.date_str(m.planned_date, missing='—')} · "
        + (f"slipped {m.delay_days}d" if (m.delay_days or 0) > 0 else "on plan")
        for m in ordered
    )
    late = [m for m in model.milestones if (m.delay_days or 0) > 0]
    action = ("Give me a revised date — “ERP go-live is 30-09-2026” — and I'll "
              "re-derive the slippage."
              if late else "Every milestone is on plan.")
    return chat.reply(messages.milestone_message(model), body=body, action=action)


def _decisions(analysis) -> str:
    model = analysis.data_model
    decisions = [d for d in model.decisions if d.status.is_open]
    if not decisions:
        return chat.reply(
            "No decisions are pending",
            body=["No source file recorded an open decision."],
            action="If a decision is expected this period, it is not in any file "
                   "you gave me.",
        )
    body = chat.bullets(
        f"**{d.title}** — {d.decision_body.value} · "
        f"{d.decision_owner or '⚠ no owner'} · "
        + (f"by {fmt.date_str(d.decision_deadline)}" if d.decision_deadline
           else "⚠ no deadline")
        for d in decisions
    )
    no_deadline = [d for d in decisions if not d.decision_deadline]
    action = ("Tell me a deadline — “the deadline is 12-08-2026” — and I'll set it."
              if no_deadline else
              "Every open decision has an owner and a deadline.")
    return chat.reply(f"{chat.count(len(decisions), 'decision')} required",
                      body=body, action=action)


def _budget(analysis) -> str:
    model = analysis.data_model
    if not model.budget:
        return chat.reply("No budget lines",
                          body=["No source file recorded a budget."],
                          action="Upload a cost tracker and I'll read it in.")
    body = chat.bullets(
        f"**{b.category}** — budget {fmt.num(b.budget)} · actual "
        f"{fmt.num(b.actual)} · forecast {fmt.num(b.forecast)} · variance "
        f"{fmt.num(b.variance)}"
        for b in model.budget
    )
    return chat.reply(
        messages.budget_message(model), body=body,
        action="Correct any figure directly — “the IT budget is 3.5 million EUR” "
               "— and every format picks it up.",
    )


def _synergies(analysis) -> str:
    model = analysis.data_model
    if not model.synergies:
        return chat.reply("No synergies",
                          body=["No source file recorded a synergy."],
                          action="Upload a synergy tracker and I'll read it in.")
    body = chat.bullets(
        f"**{s.title}** — target {fmt.num(s.target_value)} · realized "
        f"{fmt.num(s.realized_value)} · by "
        f"{fmt.date_str(s.planned_realization_date, missing='⚠ no date')}"
        for s in model.synergies
    )
    undated = [s for s in model.synergies if s.planned_realization_date is None]
    action = ("Tell me a realization date — “the realization date for X is "
              "30-09-2026” — and I'll set it."
              if undated else "Every synergy has a realization date.")
    return chat.reply(messages.synergy_message(model), body=body, action=action)


def _tasks(analysis) -> str:
    model = analysis.data_model
    overdue = model.overdue_tasks()
    shown = overdue or model.open_tasks()
    if not shown:
        return chat.reply("No open activities",
                          body=["Every task in the files is complete."],
                          action="Ask me for the report whenever you're ready.")
    body = chat.bullets(
        f"**{t.title}** — {t.owner or '⚠ unassigned'} · due "
        f"{fmt.date_str(t.due_date, missing='—')}"
        + (f" · {t.days_overdue}d overdue" if getattr(t, "days_overdue", None)
           else "")
        for t in shown
    )
    unassigned = [t for t in shown if not t.owner]
    action = (f"{chat.count(len(unassigned), 'activity', 'activities')} "
              f"{'has' if len(unassigned) == 1 else 'have'} no owner — tell me who "
              f"and I'll assign them."
              if unassigned else "Every open activity has an owner.")
    return chat.reply(messages.task_message(model), body=body, action=action)


def _workstreams(analysis) -> str:
    model = analysis.data_model
    if not model.workstreams:
        return chat.reply("No workstreams",
                          body=["Nothing in the files identified a workstream."],
                          action="Upload a plan that names them and I'll group "
                                 "everything under them.")
    body = chat.bullets(
        f"**{w.name}** — {w.lead or '⚠ no lead'} · "
        + (f"{w.progress_percentage:.0f}%" if w.progress_percentage is not None
           else fmt.NOT_REPORTED)
        + f" · {chat.count(len(w.open_risks), 'open risk')}"
        for w in model.workstreams
    )
    silent = [w for w in model.workstreams if w.progress_percentage is None]
    action = ("Give me a figure — “HR progress is 60%” — for any that didn't "
              "report."
              if silent else "Every workstream reported progress.")
    return chat.reply(messages.workstream_message(model), body=body, action=action)


def _dependencies(analysis) -> str:
    model = analysis.data_model
    if not model.dependencies:
        return chat.reply(
            "No dependencies",
            body=["No source file recorded a cross-workstream dependency."],
            action="Ask me for the report whenever you're ready.",
        )
    body = chat.bullets(
        f"**{d.description}** — {d.providing_workstream or '—'} → "
        f"{d.receiving_workstream or '—'} · "
        f"needed by {fmt.date_str(d.required_date, missing='⚠ no date')}"
        for d in model.dependencies
    )
    return chat.reply(
        f"{chat.count(len(model.dependencies), 'dependency', 'dependencies')} "
        f"tracked",
        body=body,
        action="Tell me a date or an owner for any of these and I'll record it.",
    )


def _score(analysis) -> str:
    from app.agent.data_quality import explain

    report = analysis.quality_report
    if report is None:
        return chat.reply(
            "No data-quality score",
            body=["This session has no quality report, so there is no score to "
                  "explain. That is itself worth knowing: the report cannot say "
                  "what it could not do."],
            action="Ask me to re-read the files and I'll score them.",
        )
    return explain(report)


def _unknown(_analysis) -> str:
    return chat.reply(
        "I'm not sure which findings you mean",
        body=chat.bullets([
            "**gaps** — values no file stated",
            "**conflicts** — where two files disagree",
            "**data-quality issues** — what the §8 checks flagged",
            "**issues** — the integration issues your team is managing",
        ]),
        action="Name one and I'll show you exactly that.",
    )


_HANDLERS: dict[str, Callable] = {
    "gaps": _gaps,
    "validation": _validation,
    "conflicts": _conflicts,
    "issues": _issues,
    "risks": _risks,
    "milestones": _milestones,
    "decisions": _decisions,
    "budget": _budget,
    "synergies": _synergies,
    "tasks": _tasks,
    "workstreams": _workstreams,
    "dependencies": _dependencies,
    "score": _score,
}
