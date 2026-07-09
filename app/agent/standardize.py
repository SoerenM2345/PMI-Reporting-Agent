"""Step 4: standardize raw extractor records into the one PMI data model."""
from __future__ import annotations

from app.extractors.base import normalize_status, parse_date, parse_number, parse_percent
from app.models.pmi import (KPI, BudgetItem, Milestone, PMIDataModel, Risk, Severity,
                            TaskItem)


def standardize(raw_records: list[dict], source_files: list[str]) -> PMIDataModel:
    model = PMIDataModel(source_files=source_files)
    counters = {"task": 0, "milestone": 0, "risk": 0, "budget": 0, "kpi": 0}

    for rec in raw_records:
        rtype = rec.get("type")
        try:
            if rtype == "task":
                counters["task"] += 1
                model.tasks.append(TaskItem(
                    id=f"T{counters['task']:03d}",
                    title=str(rec.get("title", "")).strip(),
                    description=_opt_str(rec.get("description")),
                    owner=_opt_str(rec.get("owner")),
                    due_date=parse_date(rec.get("due_date")),
                    status=normalize_status(rec.get("status")),
                    progress_pct=parse_percent(rec.get("progress_pct")),
                    workstream=_opt_str(rec.get("workstream")),
                    priority=_opt_str(rec.get("priority")),
                    source=rec["source"],
                ))
            elif rtype == "milestone":
                counters["milestone"] += 1
                model.milestones.append(Milestone(
                    id=f"M{counters['milestone']:03d}",
                    title=str(rec.get("title", "")).strip(),
                    due_date=parse_date(rec.get("due_date")),
                    status=normalize_status(rec.get("status")),
                    owner=_opt_str(rec.get("owner")),
                    workstream=_opt_str(rec.get("workstream")),
                    source=rec["source"],
                ))
            elif rtype == "risk":
                counters["risk"] += 1
                model.risks.append(Risk(
                    id=f"R{counters['risk']:03d}",
                    title=str(rec.get("title", "")).strip(),
                    description=_opt_str(rec.get("description")),
                    severity=_severity(rec.get("severity")),
                    likelihood=_opt_str(rec.get("likelihood")),
                    owner=_opt_str(rec.get("owner")),
                    mitigation=_opt_str(rec.get("mitigation")),
                    status=normalize_status(rec.get("status")),
                    workstream=_opt_str(rec.get("workstream")),
                    source=rec["source"],
                ))
            elif rtype == "budget":
                counters["budget"] += 1
                model.budget.append(BudgetItem(
                    id=f"B{counters['budget']:03d}",
                    category=str(rec.get("category") or rec.get("title") or "").strip(),
                    planned=parse_number(rec.get("planned")),
                    actual=parse_number(rec.get("actual")),
                    workstream=_opt_str(rec.get("workstream")),
                    source=rec["source"],
                ))
            elif rtype == "kpi":
                counters["kpi"] += 1
                model.kpis.append(KPI(
                    id=f"K{counters['kpi']:03d}",
                    name=str(rec.get("name") or rec.get("title") or "").strip(),
                    value=parse_number(rec.get("value")),
                    unit=_opt_str(rec.get("unit")),
                    target=parse_number(rec.get("target")),
                    workstream=_opt_str(rec.get("workstream")),
                    source=rec["source"],
                ))
            elif rtype == "note":
                txt = str(rec.get("text", "")).strip()
                if txt:
                    model.notes.append(f"[{rec['source'].file_name}] {txt}")
        except Exception:
            continue  # one bad row must not sink the pipeline

    return model


def _opt_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _severity(v) -> Severity:
    s = str(v or "").strip().lower()
    if s in ("critical", "very high", "kritisch"):
        return Severity.CRITICAL
    if s in ("high", "hoch", "major"):
        return Severity.HIGH
    if s in ("low", "niedrig", "minor"):
        return Severity.LOW
    return Severity.MEDIUM
