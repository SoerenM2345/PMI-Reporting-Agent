"""What the LLM decides: the request, the argument, the pages.

    request_interpreter.interpret(context)      -> OutputBrief
    storyline.develop(context, brief)           -> StorylinePlan
    section_planner.validate / enforce_coverage -> warnings, coverage restored
    visual_planner.design_pages(...)            -> DocumentDesign
    visual_planner.bind_layouts(...)            -> [PageDesign]

`app/deliverable/engine.py` sequences all five. Nothing in this package renders,
and no schema in it has a field that can carry a figure.
"""
from __future__ import annotations

from app.planning.schemas import (
    CompleteReportPlan,
    Composition,
    DocumentDesign,
    DocumentTitles,
    ElementIntent,
    OutputBrief,
    PageCopy,
    PageIntent,
    PageTitle,
    SectionIntent,
    StorylinePlan,
)

__all__ = [
    "Composition",
    "DocumentDesign",
    "CompleteReportPlan",
    "DocumentTitles",
    "ElementIntent",
    "OutputBrief",
    "PageCopy",
    "PageIntent",
    "PageTitle",
    "SectionIntent",
    "StorylinePlan",
]
