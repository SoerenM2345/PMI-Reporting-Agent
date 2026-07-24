"""Shared extraction helpers and the extractor contract (spec §5).

Every extractor is a module exposing:

    suffixes: tuple[str, ...]      # the file extensions it claims
    format:   SourceFormat         # what it produces, for source-priority ranking
    extract(path: Path) -> list[dict]

Each returned dict is a *raw record*: a record type ("task" | "milestone" | "risk" |
"issue" | "dependency" | "decision" | "budget" | "synergy" | "kpi" | "note"), the
fields it could read, and a `SourceReference` saying exactly where it came from.
Turning those into validated Pydantic entities is `app/agent/standardize.py`'s job —
extractors read, they do not interpret.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from app.models.pmi import (
    STATUS_ALIASES,
    ExtractionMethod,
    ImageRegion,
    SourceFormat,
    SourceReference,
    Status,
)

#: v1 alias — `SourceRef` is now `SourceReference` (§6.14).
SourceRef = SourceReference

#: Every record type standardize.py knows how to build.
RECORD_TYPES = (
    "task", "milestone", "risk", "issue", "dependency", "decision",
    "budget", "synergy", "kpi", "note",
)


@runtime_checkable
class Extractor(Protocol):
    """The contract each `app/extractors/*.py` module satisfies."""

    suffixes: tuple[str, ...]
    format: SourceFormat

    def extract(self, path: Path) -> list[dict]: ...

# ---------------------------------------------------------------- header maps
# fuzzy column-header aliases -> canonical field names
HEADER_ALIASES: dict[str, list[str]] = {
    # Whatever names the thing. Every entity type puts its own noun in the first
    # column — a risk register says "Risk", an issue log says "Issue" — and an entity
    # we cannot name is one we cannot report, match or resolve, so these rows would
    # otherwise be dropped entirely.
    "title": ["task", "title", "task name", "name", "activity", "item", "milestone",
              "risk", "issue", "decision", "synergy", "dependency",
              "description of task", "aufgabe", "meilenstein", "workpackage",
              "work package", "action", "action item", "deliverable"],
    "description": ["description", "details", "notes", "comment", "comments",
                    "beschreibung", "detail"],
    "owner": ["owner", "responsible", "assignee", "assigned to", "lead", "who",
              "verantwortlich", "resp", "person", "accountable"],
    "due_date": ["due", "due date", "deadline", "target date", "date", "end date",
                 "finish", "fällig", "termin", "planned date", "by when"],
    "status": ["status", "state", "progress status", "rag", "health"],
    "progress_pct": ["progress", "% complete", "percent complete", "completion",
                     "progress %", "fortschritt", "% done", "complete"],
    "workstream": ["workstream", "stream", "area", "track", "department", "function",
                   "team", "module", "bereich"],
    "priority": ["priority", "prio", "importance"],
    "severity": ["severity", "impact", "schwere"],
    "likelihood": ["likelihood", "probability", "wahrscheinlichkeit", "chance"],
    "mitigation": ["mitigation", "mitigation action", "countermeasure", "response",
                   "gegenmaßnahme"],
    "planned": ["planned", "budget", "plan", "budgeted", "target budget", "plan (eur)",
                "planned cost", "soll"],
    "actual": ["actual", "spent", "actual cost", "actuals", "ist", "actual (eur)"],
    "category": ["category", "cost category", "position", "kostenart", "line item"],
    "name": ["kpi", "kpi name", "metric", "measure", "indicator", "kennzahl",
             "synergy"],
    "value": ["value", "current", "current value", "actual value", "wert", "ist-wert"],
    "target": ["target", "target value", "goal", "ziel", "soll-wert"],
    "unit": ["unit", "einheit", "uom"],

    # §6.9 budget — the spec's field names.
    "forecast": ["forecast", "forecast cost", "eac", "prognose", "expected"],
    "committed": ["committed", "commitment", "obligated", "po", "gebunden"],
    "currency": ["currency", "ccy", "währung"],
    "variance": ["variance", "delta", "difference", "abweichung"],

    # §6.10 synergy
    "synergy_type": ["synergy type"],
    "baseline": ["baseline"],
    "realized": ["realized", "realised", "captured", "achieved", "delivered",
                 "realisiert"],
    "planned_realization_date": ["realization date", "realisation date",
                                 "planned realization date", "capture date"],
    "confidence_level": ["confidence", "confidence level", "certainty"],

    # §6.7 dependency
    "providing_workstream": ["providing workstream", "provider", "from workstream",
                             "providing", "source workstream", "depends on"],
    "receiving_workstream": ["receiving workstream", "receiver", "to workstream",
                             "receiving", "target workstream"],
    "required_date": ["required date", "needed by", "required by", "benötigt bis"],
    "impact_if_delayed": ["impact if delayed", "delay impact", "consequence"],

    # §6.8 decision
    "decision_body": ["decision body", "governance body", "decision forum", "gremium"],
    "recommended_option": ["recommended option", "recommendation", "proposed option",
                           "empfehlung"],

    # §6.6 issue
    "resolution_action": ["resolution", "resolution action", "corrective action",
                          "lösung"],
    "resolution_owner": ["resolution owner"],
}

#: An alias shorter than this only ever matches a header EXACTLY — never as a
#: substring. Without this rule, "to" matches "Total", "art" matches "Not Started",
#: and data rows get mistaken for header rows, which shreds the table they belong to.
_MIN_SUBSTRING_ALIAS = 4

#: Keywords in headers or a sheet/table name that classify a table's record type.
#:
#: Order matters less than specificity: `classify_table` takes the best-scoring
#: *specific* type and only falls back to "task". Note that "issue", "dependency",
#: "decision" and "synergy" each get their own entry — the original map folded issues
#: into risks and synergies into KPIs, so a synergy tracker (the artefact the whole
#: deal was justified with) was silently read as a list of KPIs and never appeared on
#: a Finance deck.
TABLE_TYPE_HINTS: dict[str, list[str]] = {
    "risk": ["risk", "risiko", "risk log", "risk register"],
    "issue": ["issue", "issue log", "problem", "defect", "blocker"],
    "dependency": ["dependency", "dependencies", "abhängigkeit", "interface"],
    "decision": ["decision", "decisions", "entscheidung", "beschluss", "approval"],
    "synergy": ["synergy", "synergies", "synergie", "value capture", "benefit"],
    "milestone": ["milestone", "meilenstein", "gate", "go-live", "cutover"],
    "budget": ["budget", "cost", "kosten", "spend", "financial", "opex", "capex"],
    "kpi": ["kpi", "metric", "kennzahl", "measure", "indicator", "scorecard"],
    "task": ["task", "aufgabe", "action", "workplan", "work plan", "todo", "to-do",
             "activity", "backlog", "plan", "masterplan"],
}

#: The status vocabulary lives in app/models/enums.py (§7) — one normalization
#: table, not two. Note there is no "overdue" status any more: overdue is *derived*
#: from the due date against the reporting date (calculations.py), which is what
#: makes §8.2's "overdue task marked Green" check possible at all. A tracker's own
#: RAG colour cannot be trusted to tell us whether something is late.
STATUS_MAP = STATUS_ALIASES

DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y",
                "%B %d, %Y", "%d-%m-%Y", "%Y/%m/%d", "%b %d, %Y", "%d.%m.%y"]


def normalize_header(header: Any) -> Optional[str]:
    """Map a raw column header to a canonical field name, or None.

    Matching is deliberately conservative, in three passes: exact, then whole-word,
    then prefix. Naive substring matching is what made this function dangerous — it
    is used to *detect which row is the header*, so a false positive on a data cell
    ("Not Started" matching an alias "art") promotes that row to a header and splits
    the table in half, silently losing every row below it.
    """
    if header is None:
        return None

    text = str(header).strip().casefold().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None

    # A value in the status vocabulary is a status, not a column name. "In Progress"
    # contains the word "progress", so without this it maps to the progress_pct column
    # — and a row of statuses then looks like a row of headers.
    if text in STATUS_ALIASES:
        return None

    # 1. Exact.
    for canonical, aliases in HEADER_ALIASES.items():
        if text in aliases:
            return canonical

    # 2. Whole-word, and only for aliases long enough to be unambiguous.
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if len(alias) < _MIN_SUBSTRING_ALIAS:
                continue
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return canonical

    # 3. Prefix ("Owner (Function)" -> owner).
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if len(alias) >= _MIN_SUBSTRING_ALIAS and text.startswith(alias):
                return canonical

    return None


def classify_table(headers: list[str], context: str = "") -> str:
    """Guess the record type of a table from its headers and surrounding context.

    Specific hints outrank task hints, and the best-scoring specific type wins —
    a sheet whose headers mention both "risk" and "owner" is a risk register, not
    a task list. Task is the fallback because most PMI tables are activity tables.
    """
    text = " ".join(str(h).lower() for h in headers) + " " + context.lower()
    scores = {t: sum(1 for kw in kws if kw in text) for t, kws in TABLE_TYPE_HINTS.items()}

    specific = {t: s for t, s in scores.items() if t != "task" and s > 0}
    if specific:
        return max(specific, key=lambda t: specific[t])
    return "task"


def normalize_status(value: Any) -> Status:
    """Map a source's status label onto the §7 taxonomy.

    Exact match first, then substring — so "Done" wins over a substring hit inside
    a longer phrase. Longest aliases are tried first on the substring pass, so
    "not started" is not swallowed by "started".
    """
    if value is None:
        return Status.UNKNOWN
    text = str(value).strip().casefold()
    if not text:
        return Status.UNKNOWN

    exact = STATUS_ALIASES.get(text)
    if exact is not None:
        return exact

    for alias in sorted(STATUS_ALIASES, key=len, reverse=True):
        if alias in text:
            return STATUS_ALIASES[alias]
    return Status.UNKNOWN


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    v = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value: Any) -> Optional[float]:
    """Parse a number written in either English or German convention.

    PMI files mix both: an English tracker writes 1,234.56 and a German one writes
    1.234,56 for the same amount. The rule that disambiguates them is that the LAST
    separator is the decimal point — everything before it is grouping.

    The single-separator case is genuinely ambiguous ("1,234" is 1234 in English and
    1.234 in German), so we use the grouping convention: a separator followed by
    exactly three digits is a thousands separator. That reads "1,234" as 1234 and
    "1,5" as 1.5, which is right in both locales for the values these files carry.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; a flag is not a figure
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    for symbol in ("€", "$", "£", "%", " ", " ", "'"):
        text = text.replace(symbol, "")
    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")  # (1.234) accounting style
    if negative:
        text = text[1:-1]

    has_comma, has_dot = "," in text, "." in text

    if has_comma and has_dot:
        # Last separator wins as the decimal mark.
        if text.rindex(",") > text.rindex("."):
            text = text.replace(".", "").replace(",", ".")   # 1.234,56 -> 1234.56
        else:
            text = text.replace(",", "")                     # 1,234.56 -> 1234.56
    elif has_comma:
        text = _single_separator(text, ",")
    elif has_dot:
        text = _single_separator(text, ".")

    try:
        number = float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())

    return -number if negative else number


def _single_separator(text: str, separator: str) -> str:
    """Resolve one kind of separator appearing on its own."""
    parts = text.split(separator)
    if len(parts) > 2:
        return text.replace(separator, "")            # 1.234.567 -> grouping
    if len(parts[-1]) == 3 and parts[0].lstrip("+-").isdigit():
        return text.replace(separator, "")            # 1,234 -> 1234 (grouping)
    return text.replace(separator, ".")               # 1,5 -> 1.5 (decimal)


def parse_percent(value: Any) -> Optional[float]:
    n = parse_number(value)
    if n is None:
        return None
    if 0 < n <= 1.0 and isinstance(value, (int, float)):
        n *= 100  # 0.82 -> 82%
    return n if 0 <= n <= 100 else None


PROGRESS_PATTERNS = [
    re.compile(r"(?:overall\s+)?progress\s*(?:is|=|:)?\s*(\d{1,3})\s*%", re.I),
    re.compile(r"(\d{1,3})\s*%\s*(?:overall\s+)?(?:complete|progress|done)", re.I),
    re.compile(r"integration\s+(?:is\s+)?(\d{1,3})\s*%", re.I),
]


def find_progress_mentions(text: str) -> list[float]:
    """Find 'progress = NN%' style claims in free text (consistency-check input)."""
    found: list[float] = []
    for pat in PROGRESS_PATTERNS:
        for m in pat.finditer(text):
            n = float(m.group(1))
            if 0 <= n <= 100:
                found.append(n)
    return found


ACTION_PATTERN = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:action|todo|to do|task|ai|next step)s?\s*[:\-]\s*(.+)$", re.I)
OWNER_IN_TEXT = re.compile(r"\(([^()]{2,40})\)\s*$")
OWNER_ARROW = re.compile(r"(?:->|→|@)\s*([A-ZÄÖÜ][\w.\- ]{1,40})\s*$")


def extract_actions_from_text(text: str) -> list[dict]:
    """Heuristic action-item extraction from free text (meeting notes etc.)."""
    items: list[dict] = []
    for line in text.splitlines():
        m = ACTION_PATTERN.match(line)
        if not m:
            continue
        body = m.group(1).strip()
        owner = None
        om = OWNER_ARROW.search(body) or OWNER_IN_TEXT.search(body)
        if om:
            owner = om.group(1).strip()
            body = body[: om.start()].strip().rstrip(",;")
        items.append({"type": "task", "title": body, "owner": owner})
    return items


def make_source(
    file_name: str,
    fmt: SourceFormat,
    location: str | None = None,
    *,
    sheet_name: str | None = None,
    slide_number: int | None = None,
    page_number: int | None = None,
    section_name: str | None = None,
    table_name: str | None = None,
    cell_range: str | None = None,
    image_region: ImageRegion | None = None,
    original_value: str | None = None,
    extraction_method: ExtractionMethod = ExtractionMethod.TABLE_PARSE,
    extraction_confidence: float = 1.0,
) -> SourceReference:
    """Build a provenance record (§6.14).

    `location` is the legacy free-text locator; prefer the structured keywords,
    which let the UI show a user exactly which sheet, slide, page or image region a
    disputed value came from. A bare `location` is kept as the section name so that
    display strings still render.
    """
    return SourceReference(
        file_name=file_name,
        file_type=fmt,
        sheet_name=sheet_name,
        slide_number=slide_number,
        page_number=page_number,
        section_name=section_name or (location if not any(
            (sheet_name, slide_number, page_number, table_name)
        ) else None),
        table_name=table_name,
        cell_range=cell_range,
        image_region=image_region,
        original_value=original_value,
        extraction_method=extraction_method,
        extraction_confidence=extraction_confidence,
    )


def rows_to_records(
    headers: list[Any],
    rows: list[list[Any]],
    record_type: str,
    source: SourceReference,
    *,
    first_data_row: int | None = None,
) -> list[dict]:
    """Convert a table (headers + rows) into raw record dicts via header mapping.

    When `first_data_row` is given (1-based, as a spreadsheet numbers its rows), each
    record gets its own source reference carrying that row's `cell_range`. That is
    what lets a conflict card tell the user the disputed 82% is in Workplan!A7:H7
    rather than merely "somewhere in this file" (§6.14).
    """
    mapped = [normalize_header(h) for h in headers]
    if not any(mapped):
        return []

    last_column = _column_letter(len(headers))
    records: list[dict] = []

    for offset, row in enumerate(rows):
        row_source = source
        if first_data_row is not None:
            excel_row = first_data_row + offset
            row_source = source.model_copy(
                update={"cell_range": f"A{excel_row}:{last_column}{excel_row}"}
            )

        rec: dict[str, Any] = {"type": record_type, "source": row_source}
        for field, cell in zip(mapped, row):
            if field and cell is not None and str(cell).strip() != "":
                if field in rec:
                    continue  # first matching column wins
                rec[field] = cell

        # An entity we cannot name is an entity we cannot report, match or resolve.
        if any(k in rec for k in ("title", "name", "category", "description")):
            records.append(rec)

    return records


def _column_letter(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    letters = ""
    index = max(index, 1)
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
