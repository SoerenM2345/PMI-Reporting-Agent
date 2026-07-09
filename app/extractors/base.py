"""Shared extraction helpers: header mapping, status/date/number normalization.

Every extractor returns a list of raw record dicts tagged with a record type
("task" | "milestone" | "risk" | "budget" | "kpi" | "note") plus a SourceRef.
Standardization into the Pydantic PMI model happens in app/agent/standardize.py.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from app.models.pmi import SourceFormat, SourceRef, Status

# ---------------------------------------------------------------- header maps
# fuzzy column-header aliases -> canonical field names
HEADER_ALIASES: dict[str, list[str]] = {
    "title": ["task", "title", "task name", "name", "activity", "item", "milestone",
              "risk", "description of task", "aufgabe", "meilenstein", "workpackage",
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
    "name": ["kpi", "kpi name", "metric", "measure", "indicator", "kennzahl"],
    "value": ["value", "current", "current value", "actual value", "wert", "ist-wert"],
    "target": ["target", "target value", "goal", "ziel", "soll-wert"],
    "unit": ["unit", "einheit", "uom"],
}

# keywords in headers/sheet names that classify a table
TABLE_TYPE_HINTS: dict[str, list[str]] = {
    "risk": ["risk", "risiko", "issue"],
    "milestone": ["milestone", "meilenstein"],
    "budget": ["budget", "cost", "kosten", "spend", "financial"],
    "kpi": ["kpi", "metric", "kennzahl", "measure", "synergy", "synergie"],
    "task": ["task", "aufgabe", "action", "workplan", "work plan", "todo", "to-do",
             "activity", "backlog", "plan"],
}

STATUS_MAP: dict[Status, list[str]] = {
    Status.DONE: ["done", "complete", "completed", "closed", "finished", "erledigt",
                  "abgeschlossen", "100%", "green/done"],
    Status.IN_PROGRESS: ["in progress", "ongoing", "wip", "started", "active",
                         "in arbeit", "laufend", "on track", "green", "amber"],
    Status.NOT_STARTED: ["not started", "open", "todo", "to do", "planned", "new",
                         "offen", "geplant", "pending", "backlog"],
    Status.BLOCKED: ["blocked", "on hold", "hold", "stuck", "blockiert", "paused"],
    Status.OVERDUE: ["overdue", "late", "delayed", "überfällig", "verzögert", "red"],
    Status.AT_RISK: ["at risk", "risk", "critical", "gefährdet", "yellow"],
}

DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y",
                "%B %d, %Y", "%d-%m-%Y", "%Y/%m/%d", "%b %d, %Y", "%d.%m.%y"]


def normalize_header(header: Any) -> Optional[str]:
    """Map a raw column header to a canonical field name, or None."""
    if header is None:
        return None
    h = str(header).strip().lower().replace("_", " ")
    h = re.sub(r"\s+", " ", h)
    if not h:
        return None
    for canonical, aliases in HEADER_ALIASES.items():
        if h in aliases:
            return canonical
    for canonical, aliases in HEADER_ALIASES.items():
        for a in aliases:
            if h.startswith(a) or a in h:
                return canonical
    return None


def classify_table(headers: list[str], context: str = "") -> str:
    """Guess the record type of a table from its headers and surrounding context."""
    text = " ".join(str(h).lower() for h in headers) + " " + context.lower()
    scores = {t: sum(1 for kw in kws if kw in text) for t, kws in TABLE_TYPE_HINTS.items()}
    # risk/milestone/budget/kpi hints are more specific than task hints
    for specific in ("risk", "milestone", "budget", "kpi"):
        if scores.get(specific, 0) > 0:
            return specific
    return "task" if scores.get("task", 0) > 0 else "task"


def normalize_status(value: Any) -> Status:
    if value is None:
        return Status.UNKNOWN
    v = str(value).strip().lower()
    if not v:
        return Status.UNKNOWN
    for status, aliases in STATUS_MAP.items():
        if v in aliases:
            return status
    for status, aliases in STATUS_MAP.items():
        if any(a in v for a in aliases):
            return status
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
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    v = str(value).strip().replace("€", "").replace("$", "").replace("%", "")
    v = v.replace(",", "") if v.count(",") <= 1 and "." in v else v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        return float(m.group()) if m else None


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


def make_source(file_name: str, fmt: SourceFormat, location: str | None = None) -> SourceRef:
    return SourceRef(file_name=file_name, file_format=fmt, location=location)


def rows_to_records(headers: list[Any], rows: list[list[Any]], record_type: str,
                    source: SourceRef) -> list[dict]:
    """Convert a table (headers + rows) into raw record dicts via header mapping."""
    mapped = [normalize_header(h) for h in headers]
    if not any(mapped):
        return []
    records: list[dict] = []
    for row in rows:
        rec: dict[str, Any] = {"type": record_type, "source": source}
        for field, cell in zip(mapped, row):
            if field and cell is not None and str(cell).strip() != "":
                if field in rec:
                    continue  # first matching column wins
                rec[field] = cell
        # need at least a title-ish field
        if any(k in rec for k in ("title", "name", "category")):
            records.append(rec)
    return records
