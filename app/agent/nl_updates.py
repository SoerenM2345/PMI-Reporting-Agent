""""The deadline is 12-08-2026." — plain English that changes the data.

This owns what `conversation._parse_correction` / `_locate_correction` used to
do, and extends them in three directions the originals could not reach:

* **More phrasings.** The old patterns matched "should be", "is now" and "is
  actually" and nothing else, so the most natural sentence a person types —
  "Reporting date is 17-09-2026." — fell through to `revise_content`, hit
  `guard.check_text` (which correctly refuses prose stating a figure the report
  does not hold), and came back as "I didn't change anything." The user had
  supplied a value and been told nothing happened.

* **Project-level fields.** A reporting date is not on any entity; it is on
  `PMIProject`, and overdue-ness and milestone delay are *derived from it*. So
  writing one re-runs `recompute_derived` + `run_checks` + `build_report` rather
  than just setting an attribute.

* **Conversational focus.** After the agent names something — a gap question, a
  "no deadline" finding — a bare "The deadline is 12-08-2026." refers to *that*.
  Without a stored focus it resolves to nothing, which is exactly the case the
  old code dead-ended on.

Two rules keep this from swallowing wording changes:

1. A recognised **field** must resolve, *and*
2. the right-hand side must be **value-shaped** (a date, a number, a name).

Anything else falls back to revision, and `guard.check_text` stays exactly as it
is — it is the §11 backstop for *authored prose*, not for data. A revision can
still never write a number.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from app.models.quality import ValidationIssue

log = logging.getLogger("pmi.nl_updates")


class Update(BaseModel):
    """One recognised "set X to Y", before anything has been written."""

    target: str                    # the words on the left of the verb
    value: str                     # the words on the right
    #: True when the sentence named no target at all ("The deadline is …"), so
    #: the conversational focus has to supply one.
    needs_focus: bool = False


class Applied(BaseModel):
    """What a write actually did, for composing the reply."""

    applied: bool
    message: str
    scope: str = "entity"          # "entity" | "project"
    entity_type: str = ""
    entity_id: Optional[str] = None
    label: str = ""
    field: str = ""
    value: str = ""
    old_value: str = ""
    warning: str = ""
    source_files: list[str] = []
    #: Candidate labels to name when nothing resolved. "I didn't change
    #: anything" is not an answer; "did you mean one of these?" is.
    candidates: list[str] = []


# ============================================================== parsing
#: Ordered: the imperative forms first, because "set the owner to Anna" also
#: matches the looser "X is Y" pattern on its trailing clause.
_PATTERNS = [
    re.compile(r"^(?:please\s+)?(?:set|change|update|correct|make|fix|assign)\s+"
               r"(?P<t>.+?)\s+(?:to|=|as|:)\s+(?P<v>.+)$", re.I),
    re.compile(r"^(?:the\s+)?(?P<t>.+?)\s+"
               r"(?:should (?:be|now be|read)|is now|is actually|are now|"
               r"was|were|=)\s+(?P<v>.+)$", re.I),
    # The plain present tense — the phrasing people actually use, and the one
    # that used to fall through to revision and be refused.
    re.compile(r"^(?:the\s+)?(?P<t>.+?)\s+(?:is|are)\s+(?P<v>.+)$", re.I),
]

_STOP_TOKENS = {"the", "a", "an", "of", "for", "to", "is", "are", "should", "be",
                "value", "date", "day", "day-1", "day1", "s", "and", "or", "its",
                "please", "set", "change", "update", "new"}

#: A left-hand side that names only a field, with no entity in it — the case
#: that has to resolve against `kb.focus`.
_BARE_FIELD_WORDS = {
    "deadline", "due date", "due", "owner", "date", "status", "progress",
    "lead", "value", "target", "forecast", "actual", "budget", "mitigation",
    "realization date", "realisation date", "start date", "end date",
    "completion date", "planned date", "required date", "responsible",
    "assignee", "priority", "confidence", "impact", "probability",
}


#: How people signal that they are overriding something they or the files said
#: earlier. Mirrors `app/project/classify.py::_CORRECTION`, which has had this
#: vocabulary all along on the other stack.
_CORRECTION_PREFIX = re.compile(
    r"^\s*(?:correction|to be clear|just to be clear|actually|in fact|"
    r"i meant|i said|sorry|no)\s*[,:—-]?\s+", re.I)

# ``change X to Y and give me back an updated PDF`` contains one data value;
# the trailing export request is not part of it.  Splitting at the parser keeps
# pending-gap answers and ordinary turns on the same correction path.
_FOLLOWUP_ACTION = re.compile(
    r"\s+(?:and|then)\s+(?:please\s+)?"
    r"(?:give|send|return|export|generate|render|produce|create|make|"
    r"rebuild|regenerate|redo)\b.*$",
    re.I,
)


def strip_correction_prefix(text: str) -> tuple[str, bool]:
    """`(sentence, was_a_correction)`.

    "Correction: the target is HealthSystems AG" used to reach nothing at all.
    `match_project_field` compares the *whole* left-hand side and strips only a
    leading article, so the target read as `"correction: the target"` and
    matched no field — and because `apply` still returned a non-`None` result,
    the turn dead-ended at an apology instead of falling through to anything
    else. The most natural way to signal an override was the one phrasing that
    guaranteed it would be ignored.
    """
    stripped = _CORRECTION_PREFIX.sub("", text or "", count=1)
    return stripped, stripped != (text or "")


def parse(text: str) -> Optional[Update]:
    """The sentence as an intended update, or `None` if it is not one."""
    stripped, _ = strip_correction_prefix(text)
    stripped = stripped.strip().rstrip(".!")
    stripped = _FOLLOWUP_ACTION.sub("", stripped).strip().rstrip(".!")
    if not stripped:
        return None

    for pattern in _PATTERNS:
        match = pattern.match(stripped)
        if not match:
            continue
        target = match.group("t").strip()
        value = match.group("v").strip()
        if not target or not value:
            continue
        # A value-shaped right-hand side is required before anything is written.
        # Without it "the summary is too long" would be read as a data edit.
        if not looks_like_value(value):
            return None
        return Update(target=target, value=value,
                      needs_focus=_is_bare_field(target))
    return None


def _is_bare_field(target: str) -> bool:
    cleaned = re.sub(r"^(the|its|his|her|their)\s+", "", target.strip().lower())
    return cleaned in _BARE_FIELD_WORDS


# ------------------------------------------------------------- value shapes
_MULTIPLIERS = {"k": 1_000, "thousand": 1_000, "m": 1_000_000,
                "million": 1_000_000, "mn": 1_000_000, "bn": 1_000_000_000,
                "billion": 1_000_000_000}

_MONTHS = ("jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec")


def is_date(value: str) -> bool:
    return bool(
        re.search(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b", value)
        or re.search(rf"\b\d{{1,2}}\s+({_MONTHS})", value, re.I)
        or re.search(rf"\b({_MONTHS})\w*\s+\d{{1,2}},?\s+\d{{4}}", value, re.I)
    )


def is_number(value: str) -> bool:
    return expand_number(value) is not None


def expand_number(value: str) -> Optional[float]:
    """`3.5 million EUR` → 3500000.0, `82%` → 82.0, `1,250` → 1250.0.

    A budget stated as "3.5 million" and written literally as 3.5 would be wrong
    by six orders of magnitude and would look perfectly plausible in a cell.
    """
    text = (value or "").strip().lower()
    # Strip a trailing currency word or symbol; the unit lives on the entity.
    text = re.sub(r"\b(eur|euro|euros|usd|dollars?|gbp|pounds?|chf)\b", "", text)
    text = text.replace("€", "").replace("$", "").replace("£", "").strip()

    match = re.match(r"^([+-]?[\d,]+(?:\.\d+)?)\s*"
                     r"(k|m|mn|bn|thousand|million|billion)?\s*%?$", text)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return number * _MULTIPLIERS.get(match.group(2) or "", 1)


def is_name(value: str) -> bool:
    """A person's name or a short label.

    Six words rather than four, and `&`/`,` allowed: company names are the
    common case here and they are longer than people's. "Health Systems
    Deutschland Holding AG" and "Müller, Weber & Partner" are ordinary target
    names, and at four bare-word tokens both failed `looks_like_value` — so the
    sentence was not read as an update at all and the correction was lost.
    """
    words = value.split()
    return 1 <= len(words) <= 6 and all(
        re.fullmatch(r"[\w.'’&,/-]+", word) for word in words
    )


def looks_like_value(value: str) -> bool:
    return is_date(value) or is_number(value) or is_name(value)


# ============================================================ project fields
#: The words a user says → the `PMIProject` field they mean. These are not on
#: any entity, and `reporting_date` in particular is what overdue-ness and
#: milestone delay are computed *from*, so writing one re-derives the model.
PROJECT_FIELDS: dict[str, tuple[str, ...]] = {
    "reporting_date": ("reporting date", "report date", "as of date", "as-of date",
                       "status date", "cut-off date", "cutoff date"),
    "reporting_period": ("reporting period", "period",),
    "day_1_date": ("day 1", "day-1", "day1", "day 1 date", "day-1 date",
                   "legal day 1", "day one"),
    "closing_date": ("closing date", "close date", "completion date of the deal",
                     "deal close", "closing"),
    "signing_date": ("signing date", "signature date", "sign date", "signing"),
    "integration_start_date": ("integration start", "integration start date"),
    "integration_end_date": ("integration end", "integration end date"),
    "project_name": ("project name", "programme name", "program name"),
    "deal_name": ("deal name", "transaction name"),
    "acquirer_name": ("acquirer", "acquirer name", "buyer", "buyer name"),
    "target_name": ("target", "target name", "target company"),
}

def match_project_field(target: str) -> Optional[str]:
    """Which `PMIProject` field this names — or `None`, which is the common case.

    Matched against the *whole* left-hand side, not a substring of it. A
    substring match reads "Day-1 legal close should be 02-06-2026" as the
    project's Day 1 date, when the sentence plainly names a milestone called
    "Day-1 legal close" — and writing the project field would silently re-derive
    every overdue flag in the model from a date the user never set.

    So a project field is only recognised when the user named it and nothing
    else, which is how these sentences are actually typed: "Reporting date is
    17-09-2026."
    """
    cleaned = re.sub(r"^(the|our|its)\s+", "", target.strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    best: Optional[tuple[int, str]] = None
    for field, phrases in PROJECT_FIELDS.items():
        for phrase in phrases:
            if cleaned == phrase and (best is None or len(phrase) > best[0]):
                # Longest phrase wins: "day 1 date" beats "day 1".
                best = (len(phrase), field)
    return best[1] if best else None


def apply_project_field(analysis, field: str, raw_value: str) -> Applied:
    """Write a project field, then re-derive everything that depends on it.

    Setting `reporting_date` without re-running `recompute_derived` would leave
    every "overdue" flag and every milestone delay computed against the *old*
    date while the report claimed the new one — a document that is internally
    inconsistent and looks fine.
    """
    from app.agent.calculations import recompute_derived
    from app.agent.consistency import run_checks
    from app.agent.data_quality import build_report
    from app.agent.knowledge import load as load_kb
    from app.agent.knowledge import save as save_kb
    from app.storage import json_store

    project = (json_store.load_project(analysis.session_id)
               or analysis.data_model.project)

    try:
        value = _coerce_project_value(project, field, raw_value)
    except ValueError as exc:
        return Applied(applied=False, scope="project", field=field,
                       message=str(exc))

    setattr(project, field, value)
    analysis.data_model.project = project
    json_store.save_project(analysis.session_id, project)

    # Everything downstream of the changed field, in order.
    model, issues = recompute_derived(analysis.data_model, project.reporting_date)
    model.validation_issues = list(issues)
    results = run_checks(model)
    model.conflicts = results.conflicts
    model.validation_issues.extend(results.issues)
    analysis.data_model = model
    analysis.quality_report = build_report(
        model,
        failed_files=[e.split(":", 1)[0] for e in analysis.errors],
        warnings=analysis.warnings,
    )
    json_store.save_analysis(analysis)

    kb = load_kb(analysis.session_id)
    kb.record_project_field(field, str(value))
    save_kb(kb)

    label = field.replace("_", " ")
    return Applied(
        applied=True, scope="project", field=field, value=str(value),
        label=label,
        message=f"Set the {label} to {_display(value)}.",
    )


# ================================================================= audience
_AUDIENCE_WORDS = {"audience", "reader", "readers", "recipient", "recipients",
                   "report audience", "target audience", "intended audience",
                   "this is for", "it is for", "report is for"}


def _names_audience(target: str) -> bool:
    cleaned = re.sub(r"^(the|our|its|this)\s+", "", target.strip().lower())
    return re.sub(r"\s+", " ", cleaned).strip() in _AUDIENCE_WORDS


def apply_audience(analysis, raw_value: str) -> Applied:
    """"This is for the CFO, not the SteerCo."

    Two things are written, deliberately. `Audience` is the planning key —
    there are four report shapes and no more — and the *label* is what the user
    actually said, which is what goes on the title page. Storing only the key
    would put "pmo" in front of someone who asked for the Integration Director.
    """
    from app.agent.conversation import _match_audience
    from app.agent.knowledge import load as load_kb
    from app.agent.knowledge import save as save_kb
    from app.storage import json_store

    label = " ".join((raw_value or "").split()).strip(" .")
    if not label:
        return Applied(applied=False, scope="project", field="audience",
                       message="Say who the report is for.")

    shape = _match_audience(label.lower())
    if shape is None:
        # Refused rather than guessed: §4's whole point is that the audience is
        # asked for when it cannot be inferred, and picking the nearest shape
        # silently would undo that.
        return Applied(
            applied=False, scope="project", field="audience",
            message=(f"I don't know which report shape “{label}” maps to. "
                     f"Say whether it is closest to a Steering Committee, an "
                     f"IMO/PMO, Finance, or a single workstream."))

    analysis.audience = shape
    analysis.audience_label = label
    json_store.save_analysis(analysis)

    kb = load_kb(analysis.session_id)
    kb.audience = shape
    kb.audience_label = label
    # The audience reshapes the document, so any existing draft is stale.
    kb.content_revision += 1
    save_kb(kb)

    return Applied(
        applied=True, scope="project", field="audience", value=label,
        label="audience",
        message=f"Noted — I'll write it for {label} from now on.",
    )


def _coerce_project_value(project, field: str, raw: str) -> Any:
    """Reuse the corrections engine's coercion so one parser owns dates."""
    from app.agent.corrections import _coerce

    return _coerce(project, field, raw)


def _display(value: Any) -> str:
    if isinstance(value, date):
        return f"{value:%d-%m-%Y}"
    return str(value)


# ============================================================ entity fields
#: entity_type -> (collection attr, id attr, label attr)
LABELS: dict[str, tuple[str, str, str]] = {
    "task": ("tasks", "task_id", "title"),
    "milestone": ("milestones", "milestone_id", "name"),
    "risk": ("risks", "risk_id", "title"),
    "issue": ("issues", "issue_id", "title"),
    "dependency": ("dependencies", "dependency_id", "description"),
    "decision": ("decisions", "decision_id", "title"),
    "budget": ("budget", "budget_item_id", "category"),
    "synergy": ("synergies", "synergy_id", "title"),
    "kpi": ("kpis", "kpi_id", "name"),
    "workstream": ("workstreams", "workstream_id", "name"),
}

#: entity_type -> value-kind -> ordered [(field, [keywords])]; plus defaults.
FIELDS: dict[str, dict] = {
    "task": {
        "date": [("due_date", ["due", "deadline", "target"]),
                 ("start_date", ["start", "begin", "kickoff"]),
                 ("completion_date", ["complet", "done", "finish", "close"])],
        "number": [("progress_percentage", ["progress", "percent", "complet", "%"])],
        "text": [("owner", ["owner", "responsible", "assignee", "lead"]),
                 ("status", ["status"]), ("priority", ["priority"])],
        "default_date": "due_date", "default_number": "progress_percentage",
        "default_text": "owner",
    },
    "milestone": {
        "date": [("forecast_date", ["forecast", "expected", "revised"]),
                 ("actual_date", ["actual", "achieved", "done", "complet"]),
                 ("planned_date", ["planned", "baseline", "target", "due",
                                   "deadline", "close", "go-live", "go live",
                                   "date"])],
        "text": [("owner", ["owner", "responsible", "lead"]), ("status", ["status"])],
        "default_date": "planned_date", "default_text": "owner",
    },
    "risk": {
        "number": [("probability", ["probab", "likelihood"]),
                   ("impact", ["impact", "severity"])],
        "date": [("mitigation_due_date", ["mitigation", "due", "deadline", "date"])],
        "text": [("owner", ["owner", "responsible"]),
                 ("mitigation_owner", ["mitigation owner", "mitigation"]),
                 ("mitigation_action", ["mitigation", "action"]),
                 ("status", ["status"])],
        "default_text": "owner", "default_date": "mitigation_due_date",
    },
    "issue": {
        "date": [("due_date", ["due", "deadline", "date"])],
        "text": [("owner", ["owner", "responsible"]),
                 ("resolution_owner", ["resolution owner"]),
                 ("resolution_action", ["resolution", "action"]),
                 ("status", ["status"])],
        "default_text": "owner", "default_date": "due_date",
    },
    "dependency": {
        "date": [("required_date", ["required", "due", "deadline", "date"])],
        "text": [("owner", ["owner", "responsible"]), ("status", ["status"])],
        "default_text": "owner", "default_date": "required_date",
    },
    "decision": {
        "date": [("decision_deadline", ["deadline", "due", "date", "by"])],
        "text": [("decision_owner", ["owner", "responsible"]),
                 ("status", ["status"])],
        "default_text": "decision_owner", "default_date": "decision_deadline",
    },
    "budget": {
        "number": [("budget", ["budget", "plan"]), ("actual", ["actual", "spent"]),
                   ("committed", ["committed", "commitment"]),
                   ("forecast", ["forecast", "eac", "projected"])],
        "text": [("currency", ["currency"])],
        "default_number": "budget",
    },
    "synergy": {
        "number": [("baseline", ["baseline"]),
                   ("target_value", ["target", "goal"]),
                   ("realized_value", ["realized", "realised", "achieved",
                                       "captured"]),
                   ("forecast_value", ["forecast", "expected", "projected"])],
        "date": [("planned_realization_date", ["realization", "realisation", "date",
                                               "planned"])],
        "text": [("owner", ["owner", "responsible"]), ("status", ["status"])],
        "default_number": "target_value", "default_date": "planned_realization_date",
        "default_text": "owner",
    },
    "kpi": {
        "number": [("current_value", ["current", "actual", "now", "value"]),
                   ("target_value", ["target", "goal"]),
                   ("previous_value", ["previous", "last", "prior"])],
        "date": [("reporting_date", ["reporting", "date", "as of"])],
        "default_number": "current_value", "default_date": "reporting_date",
    },
    "workstream": {
        "number": [("progress_percentage", ["progress", "percent", "complet", "%"])],
        "text": [("lead", ["lead", "owner", "responsible"]),
                 ("sponsor", ["sponsor"]), ("status", ["status"]),
                 ("summary", ["summary"])],
        "default_number": "progress_percentage", "default_text": "lead",
    },
}


#: The score a match earns for containing (or being contained by) the entity's
#: own label, as opposed to merely sharing words with it.
_LABEL_MATCH = 100


def locate(model, target: str, value: str, focus=None) -> Optional[ValidationIssue]:
    """Map "<target> is <value>" onto a concrete entity and field.

    Returns a synthetic `ValidationIssue` so the same `apply_and_persist` engine
    does the write, with the same provenance discipline — the value is recorded
    as the user's, never as something a file said.

    `focus` is the KB's record of what the agent last named. It supplies the
    entity when the sentence only names a field ("The deadline is 12-08-2026."),
    which is the case that previously resolved to nothing at all.
    """
    target_l = target.lower()
    target_words = set(re.findall(r"[\w-]+", target_l)) - _STOP_TOKENS

    best = None  # (score, entity_type, entity, label)
    for entity_type, (coll, _id_attr, label_attr) in LABELS.items():
        for entity in getattr(model, coll, []) or []:
            label = getattr(entity, label_attr, None)
            if not label:
                continue
            label_l = str(label).lower()
            label_words = set(re.findall(r"[\w-]+", label_l))
            overlap = len(target_words & label_words)
            if label_l in target_l or (target_l in label_l and len(target_l) > 3):
                score = _LABEL_MATCH + overlap
            elif overlap:
                score = overlap
            else:
                continue
            if best is None or score > best[0]:
                best = (score, entity_type, entity, str(label))

    # What the agent just asked about beats a weak label match.
    #
    # One shared word is not evidence: "The mitigation owner is Anna Schmidt",
    # answered straight after a question about a specific risk, overlaps the word
    # "mitigation" with any risk whose title mentions it — and writing the value
    # onto *that* risk is worse than not writing it at all, because it looks like
    # it worked. A focus only loses to a match that named a label outright
    # (`score >= _LABEL_MATCH`) or shared more than one distinctive word.
    if focus is not None and (best is None or best[0] < _LABEL_MATCH) \
            and (best is None or best[0] < 2):
        from_focus = _from_focus(model, focus, target_l, value)
        if from_focus is not None:
            return from_focus

    if best is None:
        # Nothing in the sentence named an entity — fall back to what the agent
        # was just talking about.
        return _from_focus(model, focus, target_l, value)

    _, entity_type, entity, label = best
    field = pick_field(entity_type, entity, target_l, value)
    if field is None:
        return None

    return _issue(entity_type, entity, label, field)


def _from_focus(model, focus, target_l: str, value: str) -> Optional[ValidationIssue]:
    if focus is None or not focus.entity_type:
        return None
    entry = LABELS.get(focus.entity_type)
    if entry is None:
        return None
    coll, id_attr, label_attr = entry
    entity = next((e for e in getattr(model, coll, []) or []
                   if getattr(e, id_attr, None) == focus.entity_id), None)
    if entity is None:
        return None

    # The field named in the sentence wins; the focused field is the fallback,
    # so "the deadline is …" right after a "no deadline" finding lands on it.
    field = pick_field(focus.entity_type, entity, target_l, value)
    if field is None and focus.field and hasattr(entity, focus.field):
        field = focus.field
    if field is None:
        return None

    label = str(getattr(entity, label_attr, "") or focus.label)
    return _issue(focus.entity_type, entity, label, field)


def _issue(entity_type: str, entity, label: str, field: str) -> ValidationIssue:
    id_attr = LABELS[entity_type][1]
    return ValidationIssue(
        check_id="CHAT-EDIT",
        family="completeness",
        entity_type=entity_type,
        entity_id=getattr(entity, id_attr, None),
        entity_label=label,
        field=field,
        message="value supplied by the user in chat",
    )


def pick_field(entity_type: str, entity, target_l: str, value: str) -> Optional[str]:
    spec = FIELDS.get(entity_type)
    if not spec:
        return None
    kind = "date" if is_date(value) else ("number" if is_number(value) else "text")

    candidates = spec.get(kind, [])

    # The **most specific** keyword wins, not the first one declared. "mitigation
    # owner" contains "owner", so first-match order sent it to `owner` and the
    # value landed on the wrong field of the right entity — which looks like it
    # worked and is therefore worse than not writing it.
    best: Optional[tuple[int, str]] = None
    for field, keywords in candidates:
        if not _has(entity, field):
            continue
        matched = max((len(kw) for kw in keywords if kw in target_l), default=0)
        if matched and (best is None or matched > best[0]):
            best = (matched, field)
    if best is not None:
        return best[1]

    default = spec.get(f"default_{kind}")
    if default and _has(entity, default):
        return default
    for field, _ in candidates:
        if _has(entity, field):
            return field
    return None


def _has(entity, field: str) -> bool:
    return field in type(entity).model_fields


# ============================================================ the entry point
def apply(analysis, text: str, focus=None) -> Optional[Applied]:
    """Try to read `text` as a data update and write it. `None` means "not one".

    Returning `None` rather than a failed `Applied` matters: the caller must be
    free to fall through to revision, so a wording change is never reported as a
    failed data edit.
    """
    update = parse(text)
    if update is None:
        return None

    # Who it is for reshapes the whole report, and it was the one thing the
    # user could not correct: it is on no entity and in no `PROJECT_FIELDS`
    # entry, so "the audience is the CFO" fell through to the entity matcher and
    # failed there.
    if _names_audience(update.target):
        return apply_audience(analysis, update.value)

    # Project-level next — a reporting date is not on any entity, and letting
    # the entity matcher fuzzy-match "reporting date" onto a KPI named "Date"
    # would write it in the wrong place entirely.
    field = match_project_field(update.target)
    if field is not None:
        return apply_project_field(analysis, field, update.value)

    model = analysis.data_model
    issue = locate(model, update.target, update.value, focus=focus)
    if issue is None:
        candidates = candidates_for(model, update.target)
        if not candidates:
            # Nothing in the model is even close, so this was probably never a
            # data edit — "the summary is too long" parses as `summary is too
            # long` and means nothing of the kind. Returning `None` lets the
            # router answer it instead of apologising for failing to do
            # something the user did not ask for.
            return None
        return Applied(
            applied=False,
            message=(f"I couldn't tell what “{update.target}” refers to."),
            candidates=candidates,
        )

    collection, id_attr, _label_attr = LABELS[issue.entity_type]
    entity = next(
        (candidate for candidate in getattr(model, collection, []) or []
         if getattr(candidate, id_attr, None) == issue.entity_id),
        None,
    )
    old = getattr(entity, issue.field, None) if entity is not None else None
    old_text = _value_text(old)
    source_files = list(getattr(entity, "source_files", []) or [])

    from app.agent.corrections import apply_and_persist
    from app.agent.knowledge import UserValue
    from app.agent.knowledge import load as load_kb
    from app.agent.knowledge import save as save_kb

    # A number written as "3.5 million" must reach the model as 3500000.
    raw = update.value
    if is_number(raw) and not is_date(raw):
        expanded = expand_number(raw)
        if expanded is not None:
            raw = f"{expanded:g}"

    result = apply_and_persist(analysis, issue, raw)
    if not result.applied:
        return Applied(applied=False, message=result.message,
                       entity_type=issue.entity_type, entity_id=issue.entity_id,
                       label=issue.entity_label or "", field=issue.field or "")

    current = getattr(entity, issue.field, None) if entity is not None else raw
    current_text = _value_text(current)
    percentage = (re.search(r"\b\d+(?:\.\d+)?%", update.target)
                  if issue.field == "status" else None)
    warning = _override_warning(
        old, old_text, current_text, source_files,
        percentage_in_status=(percentage.group(0) if percentage else ""),
    )

    kb = load_kb(analysis.session_id)
    kb.record_value(UserValue(
        entity_type=issue.entity_type, entity_id=issue.entity_id,
        label=issue.entity_label or "", field=issue.field or "",
        value=current_text, raw=update.value, old_value=old_text or None,
    ))
    save_kb(kb)

    return Applied(
        applied=True, message=result.message,
        entity_type=issue.entity_type, entity_id=issue.entity_id,
        label=issue.entity_label or "", field=issue.field or "",
        value=current_text, old_value=old_text, warning=warning,
        source_files=source_files,
    )


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return _display(value)


def _override_warning(old: Any, old_text: str, new_text: str,
                      source_files: list[str], *,
                      percentage_in_status: str = "") -> str:
    """Explain a mismatch while still applying the user's correction."""
    parts: list[str] = []
    if percentage_in_status:
        parts.append(
            f"{percentage_in_status} is a readiness/progress measure, "
            "not the workflow status field, so the percentage remains unchanged."
        )

    meaningful = old is not None and old_text.casefold() not in {
        "", "unknown", "not reported"
    }
    if meaningful and old_text != new_text:
        source = (" from " + ", ".join(source_files)) if source_files else ""
        parts.append(
            f"The current consolidated value is {old_text}{source}, while you "
            f"asked for {new_text}. Your explicit correction overrides that "
            "value in the report; the source file itself is unchanged."
        )
    return " ".join(parts)


class BulkResult(BaseModel):
    """The outcome of a pasted, multi-item update — one block, many writes.

    Distinct from `Applied` (which is one field) because a paste is only useful
    if it says *per item* what happened: a report that silently drops the two
    lines it could not place is worse than one that names them, since the user
    has no other signal that those values did not land.
    """

    count: int = 0                 # records recognised in the paste
    applied: list[str] = []        # human-readable "set X" messages
    skipped: list[str] = []        # "<title>: <why>" for each write that failed


class EmbeddedValue(BaseModel):
    """One value filled into a finding the agent previously displayed.

    People commonly copy the data-quality findings, replace the missing part in
    each sentence, and paste the whole paragraph back.  That is neither a
    one-field correction nor the compact ``title — owner · due — date`` table
    shape below, so it needs a small typed intermediate of its own.
    """

    entity_type: str
    label: str
    field: str
    value: str
    position: int = 0


_BULK_DATE = r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"


# The phrases mirror the findings emitted by ``consistency/completeness.py`` and
# ``calculations.py``.  They intentionally require an explicit entity type,
# quoted label and field phrase: ordinary prose must never be mined for a value
# merely because it contains a person's name or a date.
_EMBEDDED_VALUE_PATTERNS: tuple[tuple[str, str, re.Pattern], ...] = (
    (
        "risk", "mitigation_owner",
        re.compile(
            r"\bRisk\s+['\"“‘](?P<label>.+?)['\"”’]\s+"
            r"(?:has a mitigation action but (?:nobody is )?assigned to|"
            r"has (?:a )?mitigation owner|mitigation owner(?:\s+is|\s*:)|"
            r"(?:is\s+)?assigned\s+to)\s+"
            r"(?P<value>.+?)(?=\s+(?:Critical|High|Medium|Low)\s*[—–-]|"
            r"\s+(?:Risk|Decision|Dependency|Task)\s+['\"“‘]|"
            r"\s+Source\s*:|[.;\n]|$)",
            re.I,
        ),
    ),
    (
        "decision", "decision_deadline",
        re.compile(
            rf"\bDecision\s+['\"“‘](?P<label>.+?)['\"”’][^;\n]{{0,120}}?"
            rf"\b(?:has|with)\s+(?:a\s+)?deadline(?:\s+(?:of|is|:))?\s+"
            rf"(?P<value>{_BULK_DATE})",
            re.I,
        ),
    ),
    (
        "dependency", "owner",
        re.compile(
            r"\bDependency\s+['\"“‘](?P<label>.+?)['\"”’]\s+"
            r"(?:has\s+(?:an?\s+)?owner|owner(?:\s+is|\s*:))\s+"
            r"(?P<value>.+?)(?=\s+(?:Critical|High|Medium|Low)\s*[—–-]|"
            r"\s+Source\s*:|[.;\n]|$)",
            re.I,
        ),
    ),
    (
        "task", "completion_date",
        re.compile(
            rf"\bTask\s+['\"“‘](?P<label>.+?)['\"”’][^;\n]{{0,100}}?"
            rf"\bcompletion date(?:\s+(?:of|is|:))?\s+"
            rf"(?P<value>{_BULK_DATE})",
            re.I,
        ),
    ),
    (
        "synergy", "planned_realization_date",
        re.compile(
            rf"\bSynergy\s+['\"“‘](?P<label>.+?)['\"”’][^;\n]{{0,100}}?"
            rf"\b(?:planned\s+)?reali[sz]ation date"
            rf"(?:\s+(?:of|is|:))?\s+(?P<value>{_BULK_DATE})",
            re.I,
        ),
    ),
    (
        "project", "reporting_date",
        re.compile(
            rf"\b(?:No\s+)?(?P<label>reporting date)\s+"
            rf"(?:is|=|:)\s+(?P<value>{_BULK_DATE})",
            re.I,
        ),
    ),
)

_NOT_SUPPLIED = {
    "it", "nobody", "none", "no owner", "not assigned", "not reported",
    "unknown", "unassigned", "missing",
}


def parse_embedded(text: str) -> list[EmbeddedValue]:
    """Read values inserted into one or more displayed quality findings.

    The returned order is the order in which the findings appeared, even though
    each field shape has its own pattern. Duplicate references to the same
    field are collapsed so a pasted paragraph cannot write one value twice.
    """
    found: list[EmbeddedValue] = []
    seen: set[tuple[str, str, str]] = set()
    for entity_type, field, pattern in _EMBEDDED_VALUE_PATTERNS:
        for match in pattern.finditer(text or ""):
            label = " ".join(match.group("label").split()).strip()
            value = " ".join(match.group("value").split()).strip(" ,:-")
            key = (entity_type, label.casefold(), field)
            if not label or not value or value.casefold() in _NOT_SUPPLIED \
                    or key in seen:
                continue
            if field.endswith("date") or field.endswith("deadline"):
                if not is_date(value):
                    continue
            elif not is_name(value):
                continue
            seen.add(key)
            found.append(EmbeddedValue(
                entity_type=entity_type, label=label, field=field,
                value=value, position=match.start(),
            ))
    return sorted(found, key=lambda item: item.position)


def apply_embedded(analysis, text: str, focus=None) -> Optional[BulkResult]:
    """Apply all values a user inserted into pasted quality findings.

    Values still travel through :func:`apply`, so coercion, re-checking,
    persistence, provenance and report staleness are identical to a value typed
    as a standalone sentence.  This is only a more forgiving input shape.
    """
    values = parse_embedded(text)
    if not values:
        return None

    result = BulkResult(count=len(values))
    for item in values:
        field = item.field.replace("_", " ")
        if item.entity_type == "project":
            sentence = f"the {field} is {item.value}"
        else:
            sentence = (f"the {field} for {item.entity_type} {item.label} "
                        f"is {item.value}")
        applied = apply(analysis, sentence, focus=focus)
        if applied is not None and applied.applied:
            result.applied.append(applied.message)
        else:
            why = (applied.message if applied is not None
                   else "I couldn't match this item to the data.")
            result.skipped.append(f"{item.label} — {field}: {why}")
    return result


#: One pasted line: "<title> — <owner> · due — <date>". This is the exact shape
#: the agent's own task/issue/milestone answers print, so copying an answer,
#: filling the dashes, and pasting it back is the natural gesture — and the one
#: `parse` (single "X is Y" sentence) cannot read. Separators are the em/en dash
#: the answers use, never the hyphen inside a word ("data-privacy", "Re-baseline").
_BULK_RECORD = re.compile(
    rf"(?P<title>[^\n]+?)\s*[—–]\s*"           # title —
    rf"(?P<owner>[^\n·|]+?)?\s*"                # optional owner
    rf"[·|]?\s*due\b[\s—–:.-]*"                 # · due —
    rf"(?P<date>{_BULK_DATE})",
    re.I,
)


def parse_bulk(text: str) -> list[tuple[str, Optional[str], str]]:
    """Every `(title, owner, date)` a pasted block names, in order.

    `finditer` segments the paste for free: each match consumes up to a due
    date, and the next record begins after it — so a block that arrived as one
    run-together paragraph splits exactly like one that arrived a line per task.
    """
    records: list[tuple[str, Optional[str], str]] = []
    for match in _BULK_RECORD.finditer(text or ""):
        title = match.group("title").strip(" \t•*-·|")
        owner = (match.group("owner") or "").strip(" \t•*·|") or None
        date = match.group("date").strip()
        if title:
            records.append((title, owner, date))
    return records


def apply_bulk(analysis, text: str, focus=None) -> Optional[BulkResult]:
    """Read `text` as a pasted list of "<title> — <owner> · due <date>" and
    write every value it names into the data model. `None` means "not one".

    Each recognised value is routed through `apply` — the same single-value
    engine — by synthesising the sentence it would have been typed as. That
    keeps one parser, one coercion path, and one provenance rule ("supplied by
    the user"): a bulk paste is never a second way for a figure to reach a cell,
    only a faster way to send the same ones.
    """
    records = parse_bulk(text)
    if not records:
        return None

    result = BulkResult(count=len(records))
    for title, owner, date in records:
        dated = apply(analysis, f"the due date for {title} is {date}", focus=focus)
        if dated is not None and dated.applied:
            result.applied.append(dated.message)
        else:
            why = (dated.message if dated is not None
                   else "I couldn't tell which item this is.")
            result.skipped.append(f"{title}: {why}")

        # An owner is written only when the paste actually names one — the agent
        # prints "⚠ unassigned" where it is missing, and copying that back must
        # not record the warning glyph as somebody's name.
        if owner and is_name(owner) and "⚠" not in owner \
                and owner.lower() not in {"unassigned", "no owner", "not reported"}:
            named = apply(analysis, f"the owner of {title} is {owner}", focus=focus)
            if named is not None and named.applied:
                result.applied.append(named.message)
    return result


def candidates_for(model, target: str, limit: int = 6) -> list[str]:
    """The labels closest to what the user typed.

    Replaces "I didn't change anything." — a reply that says nothing about what
    was looked for, so the user's only move is to guess differently.
    """
    words = set(re.findall(r"[\w-]+", target.lower())) - _STOP_TOKENS
    scored: list[tuple[int, str]] = []
    for entity_type, (coll, _id, label_attr) in LABELS.items():
        for entity in getattr(model, coll, []) or []:
            label = getattr(entity, label_attr, None)
            if not label:
                continue
            overlap = len(words & set(re.findall(r"[\w-]+", str(label).lower())))
            if overlap:
                scored.append((overlap, f"{label} ({entity_type})"))
    scored.sort(key=lambda pair: -pair[0])
    return [label for _score, label in scored[:limit]]
