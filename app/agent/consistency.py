"""Steps 5-6: cross-source consistency checks + conflict resolution.

Detection (step 5): the same fact reported differently by different files —
e.g. Excel says progress = 82%, PowerPoint says progress = 75%.

Resolution (step 6):
  Option A ("ask")      -> critical conflicts are returned to the user unresolved.
  Option B ("priority") -> apply source priority Excel > Word/PDF > PowerPoint > HTML.
"""
from __future__ import annotations

from collections import defaultdict

from app.models.pmi import SOURCE_PRIORITY, Conflict, PMIDataModel


def detect_conflicts(model: PMIDataModel) -> list[Conflict]:
    conflicts: list[Conflict] = []
    conflicts += _kpi_conflicts(model)
    conflicts += _task_conflicts(model)
    return conflicts


def _kpi_conflicts(model: PMIDataModel) -> list[Conflict]:
    """Same KPI name, different values, different files (incl. Overall Progress)."""
    groups: dict[str, list] = defaultdict(list)
    for k in model.kpis:
        groups[k.name.strip().lower()].append(k)
    out: list[Conflict] = []
    for name, items in groups.items():
        by_file: dict[str, float] = {}
        formats = {}
        for k in items:
            if k.value is None:
                continue
            # one value per file: keep first
            by_file.setdefault(k.source.file_name, k.value)
            formats[k.source.file_name] = k.source.file_format
        distinct = set(by_file.values())
        if len(by_file) >= 2 and len(distinct) >= 2:
            out.append(Conflict(
                entity_type="kpi",
                entity_key=items[0].name,
                field="value",
                values={f: _fmt(v) for f, v in by_file.items()},
                formats=formats,
                critical="progress" in name,
            ))
    return out


def _task_conflicts(model: PMIDataModel) -> list[Conflict]:
    """Same task title in multiple files with diverging status or progress."""
    groups: dict[str, list] = defaultdict(list)
    for t in model.tasks:
        groups[t.title.strip().lower()].append(t)
    out: list[Conflict] = []
    for title, items in groups.items():
        if len({t.source.file_name for t in items}) < 2:
            continue
        for field in ("status", "progress_pct"):
            by_file, formats = {}, {}
            for t in items:
                v = getattr(t, field)
                if v is None or (field == "status" and v.value == "unknown"):
                    continue
                by_file.setdefault(t.source.file_name, v)
                formats[t.source.file_name] = t.source.file_format
            vals = {_fmt(v) for v in by_file.values()}
            if len(by_file) >= 2 and len(vals) >= 2:
                out.append(Conflict(
                    entity_type="task",
                    entity_key=items[0].title,
                    field=field,
                    values={f: _fmt(v) for f, v in by_file.items()},
                    formats=formats,
                    critical=(field == "progress_pct"),
                ))
    return out


def resolve_conflicts(conflicts: list[Conflict], strategy: str = "priority",
                      user_choices: dict[str, str] | None = None) -> list[Conflict]:
    """strategy: 'priority' (Option B) or 'ask' (Option A).

    user_choices maps "<entity_key>|<field>" -> chosen file_name.
    """
    user_choices = user_choices or {}
    for c in conflicts:
        key = f"{c.entity_key}|{c.field}"
        if key in user_choices and user_choices[key] in c.values:
            chosen = user_choices[key]
            c.resolved_value, c.resolved_from, c.resolution = c.values[chosen], chosen, "user"
            continue
        if strategy == "ask" and c.critical:
            continue  # left unresolved -> UI asks the user
        best = min(c.values, key=lambda f: SOURCE_PRIORITY[c.formats[f]])
        c.resolved_value, c.resolved_from, c.resolution = c.values[best], best, "source_priority"
    return conflicts


def apply_resolutions(model: PMIDataModel) -> PMIDataModel:
    """Write resolved values back into the model (KPI values, task fields)."""
    for c in model.conflicts:
        if c.resolved_value is None:
            continue
        if c.entity_type == "kpi":
            for k in model.kpis:
                if k.name == c.entity_key and k.source.file_name != c.resolved_from:
                    k.value = _num(c.resolved_value) if _num(c.resolved_value) is not None else k.value
        elif c.entity_type == "task":
            for t in model.tasks:
                if t.title == c.entity_key and c.field == "progress_pct":
                    n = _num(c.resolved_value)
                    if n is not None:
                        t.progress_pct = n
    return model


def _fmt(v) -> str:
    if hasattr(v, "value"):
        return str(v.value)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None
