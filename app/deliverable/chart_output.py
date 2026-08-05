"""Plan and render standalone charts from the Deliverable's stored ChartSpecs."""
from __future__ import annotations

from pathlib import Path

from app.deliverable.model import ChartElement, Deliverable, PageDesign


def ensure_spec(deliverable: Deliverable, context) -> list[str]:
    """Ensure a chart output has at least one validated, previewable ChartSpec."""
    if deliverable.primary_format != "chart" or deliverable.specs.charts:
        return []

    from app.generation import chart_planner
    from app.visualizations import builder, validator

    priorities = _requested_kinds(context.user_request) + [
        "workstream", "risk", "milestone", "budget", "synergy", "kpi", "task"
    ]
    seen: set[str] = set()
    for kind in priorities:
        if kind in seen:
            continue
        seen.add(kind)
        items = [item for item in context.evidence.of_kind(kind)
                 if not item.is_absence]
        if not items:
            continue
        page = PageDesign(
            page_id="standalone-chart", title=_title(kind),
            subtitle="Standalone chart requested by the user",
        )
        element = ChartElement(
            element_id="standalone-chart.chart", spec_id="standalone-chart",
            caption=_title(kind), evidence_ids=[item.evidence_id for item in items[:20]],
        )
        request = chart_planner.fallback_chart(element, page, items)
        if request is None:
            continue
        spec = builder.build_chart(request, context.evidence)
        checked = validator.validate_chart(spec, context.evidence)
        if not checked.ok:
            continue
        spec.warnings.extend(checked.warnings)
        deliverable.specs.charts[spec.spec_id] = spec
        page.elements = [element]
        page.evidence_ids = list(spec.evidence_ids)
        deliverable.pages = [page]
        deliverable.title = spec.title or page.title
        deliverable.governing_message = spec.insight
        deliverable.renumber()
        return []
    return ["No chart could be built from the available quantitative evidence."]


def render(deliverable: Deliverable, context, out_dir: Path) -> list[Path]:
    """Render exactly the ChartSpecs the user reviewed; never add topic extras."""
    from app.visualizations import charts

    brand = context.brand_system
    if brand is None:
        from app.templates import template_registry

        brand = template_registry.default().brand
    return [charts.to_png(spec, brand, out_dir)
            for spec in deliverable.specs.charts.values()]


def _requested_kinds(text: str) -> list[str]:
    lowered = (text or "").casefold()
    mapping = {
        "workstream": ("workstream", "progress"),
        "risk": ("risk", "risks"),
        "milestone": ("milestone", "timeline", "schedule"),
        "budget": ("budget", "cost", "finance"),
        "synergy": ("synergy", "synergies"),
        "kpi": ("kpi", "indicator"),
        "task": ("task", "activity"),
    }
    return [kind for kind, words in mapping.items()
            if any(word in lowered for word in words)]


def _title(kind: str) -> str:
    return {
        "workstream": "Workstream progress",
        "risk": "Risk profile",
        "milestone": "Milestone status",
        "budget": "Budget position",
        "synergy": "Synergy realization",
        "kpi": "Key indicators",
        "task": "Task progress",
    }.get(kind, kind.replace("_", " ").title())
