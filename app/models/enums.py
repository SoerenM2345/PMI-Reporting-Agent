"""Controlled vocabularies for the PMI data model (spec §6, §7).

§7 requires that inconsistent terminology from the source files be normalized onto
a single taxonomy — "SteerCo"/"Steering Committee"/"SC" all mean one thing, and
"done"/"complete"/"finished"/"100%" all mean Completed. The alias maps here are
where that normalization is defined.
"""
from __future__ import annotations

from enum import Enum

from app.config import get_settings


class SourceFormat(str, Enum):
    """Input formats (§4 step 1)."""

    EXCEL = "excel"
    CSV = "csv"
    WORD = "word"
    PDF = "pdf"
    POWERPOINT = "powerpoint"
    HTML = "html"
    IMAGE = "image"


def source_priority(override: "dict[str, int] | None" = None) -> dict[SourceFormat, int]:
    """Trust ranking for conflict resolution (§9). Lower = more trusted.

    Read from settings on every call so a project-specific override takes effect
    without a reimport. Images rank last: a value read out of a screenshot or a
    photo of a whiteboard is less reliable than one read from the tracker itself.
    """
    configured = override or get_settings().source_priority
    return {fmt: configured.get(fmt.value, 99) for fmt in SourceFormat}


#: Snapshot of the default ranking. Prefer `source_priority()` in new code — this
#: exists so existing imports keep working.
SOURCE_PRIORITY: dict[SourceFormat, int] = source_priority()


class Status(str, Enum):
    """Normalized task/milestone status (§6.3)."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    #: Alias. The spec's taxonomy says "Completed"; the original code said "done".
    #: Declaring it here makes `Status.DONE is Status.COMPLETED` true, so old call
    #: sites keep resolving while `.value` is the spec's word.
    DONE = "completed"

    @property
    def is_open(self) -> bool:
        return self not in (Status.COMPLETED, Status.CANCELLED)


#: §7's status vocabulary, including RAG colours. Note "red" -> AT_RISK, not
#: BLOCKED: red means "off track", which is not the same as "cannot proceed".
#: Blocked is asserted only when a source says so explicitly.
STATUS_ALIASES: dict[str, Status] = {
    "not started": Status.NOT_STARTED, "open": Status.NOT_STARTED,
    "new": Status.NOT_STARTED, "to do": Status.NOT_STARTED,
    "todo": Status.NOT_STARTED, "offen": Status.NOT_STARTED,
    "nicht begonnen": Status.NOT_STARTED, "planned": Status.NOT_STARTED,

    "in progress": Status.IN_PROGRESS, "ongoing": Status.IN_PROGRESS,
    "underway": Status.IN_PROGRESS, "started": Status.IN_PROGRESS,
    "wip": Status.IN_PROGRESS, "active": Status.IN_PROGRESS,
    "in arbeit": Status.IN_PROGRESS, "laufend": Status.IN_PROGRESS,
    "green": Status.IN_PROGRESS, "on track": Status.IN_PROGRESS,
    "grün": Status.IN_PROGRESS,

    "at risk": Status.AT_RISK, "amber": Status.AT_RISK, "yellow": Status.AT_RISK,
    "attention required": Status.AT_RISK, "attention": Status.AT_RISK,
    "delayed": Status.AT_RISK, "behind": Status.AT_RISK, "gelb": Status.AT_RISK,
    "red": Status.AT_RISK, "off track": Status.AT_RISK, "critical": Status.AT_RISK,
    "rot": Status.AT_RISK,

    "blocked": Status.BLOCKED, "on hold": Status.BLOCKED, "stopped": Status.BLOCKED,
    "blockiert": Status.BLOCKED, "gestoppt": Status.BLOCKED,

    "completed": Status.COMPLETED, "complete": Status.COMPLETED,
    "done": Status.COMPLETED, "finished": Status.COMPLETED,
    "closed": Status.COMPLETED, "100%": Status.COMPLETED,
    "abgeschlossen": Status.COMPLETED, "erledigt": Status.COMPLETED,
    "fertig": Status.COMPLETED,

    "cancelled": Status.CANCELLED, "canceled": Status.CANCELLED,
    "dropped": Status.CANCELLED, "abgebrochen": Status.CANCELLED,
}


class Severity(str, Enum):
    """Rating band for risks and issues (§6.5, §6.6)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: Textual ratings -> the 1-5 scale used by `risk_score = probability x impact`.
#: The spec mandates the formula (§6.5) but never defines the scales; we use the
#: conventional PMI 5x5 matrix and document the choice in docs/pmi_data_model.md.
SEVERITY_SCALE: dict[Severity, int] = {
    Severity.LOW: 2,
    Severity.MEDIUM: 3,
    Severity.HIGH: 4,
    Severity.CRITICAL: 5,
}

SEVERITY_ALIASES: dict[str, Severity] = {
    "low": Severity.LOW, "minor": Severity.LOW, "niedrig": Severity.LOW,
    "gering": Severity.LOW, "1": Severity.LOW, "2": Severity.LOW,
    "medium": Severity.MEDIUM, "moderate": Severity.MEDIUM,
    "mittel": Severity.MEDIUM, "3": Severity.MEDIUM,
    "high": Severity.HIGH, "major": Severity.HIGH, "hoch": Severity.HIGH,
    "4": Severity.HIGH,
    "critical": Severity.CRITICAL, "severe": Severity.CRITICAL,
    "kritisch": Severity.CRITICAL, "blocker": Severity.CRITICAL, "5": Severity.CRITICAL,
}


class Audience(str, Enum):
    """Report audiences (§4 step 3)."""

    EXECUTIVE = "Executive"   # Steering Committee
    PMO = "PMO"               # IMO / PMO
    FINANCE = "Finance"
    WORKSTREAM = "Workstream"


class Trend(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"
    UNKNOWN = "unknown"


class IntegrationType(str, Enum):
    """§6.1 recommended integration types."""

    FULL = "Full integration"
    PARTIAL = "Partial integration"
    STANDALONE = "Standalone"
    HOLDING = "Holding model"
    CARVE_OUT = "Carve-out"
    SEPARATION = "Separation"
    UNKNOWN = "Unknown"


class IntegrationPhase(str, Enum):
    """§3's ten PMI phases."""

    SETUP = "Integration project setup"
    STRATEGY = "Integration strategy"
    TOM_DESIGN = "Target Operating Model design"
    DAY_1_READINESS = "Day 1 readiness"
    PLANNING = "Integration planning"
    EXECUTION = "Integration execution"
    VALUE_CREATION = "Value creation and synergy realization"
    CHANGE_MANAGEMENT = "Change management and communication"
    STABILIZATION = "Stabilization"
    TRANSITION_TO_BAU = "Transition to business as usual"
    UNKNOWN = "Unknown"


class RiskCategory(str, Enum):
    """§6.5 recommended risk categories."""

    OPERATIONAL = "Operational"
    FINANCIAL = "Financial"
    PEOPLE = "People"
    TECHNOLOGY = "Technology"
    LEGAL = "Legal"
    COMPLIANCE = "Compliance"
    CUSTOMER = "Customer"
    SYNERGY = "Synergy"
    TIMELINE = "Timeline"
    GOVERNANCE = "Governance"
    COMMUNICATION = "Communication"
    TSA = "TSA"
    DATA = "Data"
    CYBERSECURITY = "Cybersecurity"
    UNKNOWN = "Unknown"


class SynergyType(str, Enum):
    """§6.10 recommended synergy types."""

    COST = "Cost synergy"
    REVENUE = "Revenue synergy"
    CAPITAL = "Capital synergy"
    WORKING_CAPITAL = "Working-capital synergy"
    TAX = "Tax synergy"
    AVOIDED_COST = "Avoided cost"
    ONE_TIME = "One-time benefit"
    UNKNOWN = "Unknown"


class BudgetCategory(str, Enum):
    """§6.9 recommended budget categories."""

    EXTERNAL_ADVISORS = "External advisors"
    INTERNAL_RESOURCES = "Internal project resources"
    TECHNOLOGY = "Technology"
    SYSTEM_MIGRATION = "System migration"
    RESTRUCTURING = "Restructuring"
    COMMUNICATION = "Communication"
    TRAINING = "Training"
    RETENTION = "Retention"
    INFRASTRUCTURE = "Integration infrastructure"
    TSA_COSTS = "TSA costs"
    OTHER = "Other"


class DecisionBody(str, Enum):
    """§6.8 decision bodies."""

    STEERING_COMMITTEE = "Steering Committee"
    INTEGRATION_DIRECTOR = "Integration Director"
    IMO = "IMO"
    WORKSTREAM_LEAD = "Workstream Lead"
    EXECUTIVE_SPONSOR = "Executive Sponsor"
    FINANCE_COMMITTEE = "Finance Committee"
    UNKNOWN = "Unknown"


class MeetingType(str, Enum):
    """§6.12 meeting types."""

    STEERING_COMMITTEE = "Steering Committee"
    IMO = "IMO meeting"
    PMO = "PMO meeting"
    WORKSTREAM = "Workstream meeting"
    RISK_REVIEW = "Risk review"
    SYNERGY_REVIEW = "Synergy review"
    DAY_1_REVIEW = "Day 1 readiness review"
    UNKNOWN = "Unknown"


class ImageContentType(str, Enum):
    """What a picture turned out to contain (§5.6 step 5)."""

    TEXT = "text"
    TABLE = "table"
    CHART = "chart"
    TIMELINE = "timeline"
    DIAGRAM = "diagram"
    DASHBOARD = "dashboard"
    HANDWRITING = "handwriting"


class ExtractionMethod(str, Enum):
    """How a value got into the model — carried on every SourceReference so the
    data-quality report can say *why* something is low confidence."""

    TABLE_PARSE = "table_parse"       # a real table in a real spreadsheet
    TEXT_REGEX = "text_regex"         # pattern-matched out of prose
    LLM_TEXT = "llm_text"             # model read it from unstructured text
    LLM_VISION = "llm_vision"         # model read it from a picture
    OCR = "ocr"                       # local OCR, no semantic understanding
    DERIVED = "derived"               # computed by us, not read from any source
    USER = "user"                     # the user told us


#: §3's canonical workstreams, with the aliases sources actually use. Applied by
#: `normalize_workstream()`; anything unrecognised is kept verbatim rather than
#: forced into a bucket (§7: never silently invent).
WORKSTREAM_ALIASES: dict[str, str] = {
    "finance": "Finance", "fin": "Finance", "finanzen": "Finance",
    "controlling": "Finance", "accounting": "Finance",

    "hr": "Human Resources", "human resources": "Human Resources",
    "people": "Human Resources", "personal": "Human Resources",

    "it": "Information Technology", "information technology": "Information Technology",
    "tech": "Information Technology", "technology": "Information Technology",
    "ict": "Information Technology",

    "operations": "Operations", "ops": "Operations", "betrieb": "Operations",
    "legal": "Legal", "recht": "Legal",
    "compliance": "Compliance",
    "tax": "Tax", "steuern": "Tax",
    "sales": "Sales", "vertrieb": "Sales",
    "marketing": "Marketing",
    "procurement": "Procurement", "purchasing": "Procurement",
    "einkauf": "Procurement",
    "supply chain": "Supply Chain", "logistics": "Supply Chain",
    "scm": "Supply Chain",
    "communications": "Communications", "comms": "Communications",
    "kommunikation": "Communications",
    "change management": "Change Management", "change": "Change Management",
    "organization": "Organization", "organisation": "Organization",
    "org": "Organization",
    "data": "Data",
    "cybersecurity": "Cybersecurity", "cyber": "Cybersecurity",
    "security": "Cybersecurity",
    "real estate": "Real Estate", "facilities": "Real Estate",
    "synergy management": "Synergy Management", "synergies": "Synergy Management",
    "synergy": "Synergy Management",
    "day 1 readiness": "Day 1 Readiness", "day 1": "Day 1 Readiness",
    "day-1": "Day 1 Readiness", "day one": "Day 1 Readiness",
    "d1": "Day 1 Readiness",
    "tsa": "Transitional Service Agreements",
    "transitional service agreements": "Transitional Service Agreements",
    "separation": "Separation", "carve-out": "Separation", "carve out": "Separation",

    "imo": "IMO", "integration office": "IMO",
    "integration management office": "IMO",
    "pmo": "PMO", "program office": "PMO", "project office": "PMO",
}


def normalize_workstream(raw: str | None) -> str | None:
    """Map a source's workstream label onto §3's vocabulary.

    Unrecognised labels are returned trimmed but otherwise untouched — a project
    may legitimately run a workstream the spec never listed, and quietly relabelling
    it would be exactly the kind of invention §7 forbids.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return WORKSTREAM_ALIASES.get(text.casefold(), text)
