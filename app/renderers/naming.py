"""Name output files after the project, not after the system that made them.

Every export used to be called `PMI_Report_Executive_2026-07-25.pptx` — the
audience enum and a date, with `PMI_Report` standing in for a project name that
was the literal default `"PMI Project"`. A folder of those is unnavigable.
"""
from __future__ import annotations

import re
from datetime import date

EXTENSIONS = {"pptx": "pptx", "docx": "docx", "pdf": "pdf", "html": "html",
              "xlsx": "xlsx", "md": "md", "markdown": "md"}


def output_name(deliverable, context, fmt: str) -> str:
    """`MedAxis-NordCare_steerco-pack_2026-07-30.pptx`."""
    extension = EXTENSIONS.get(fmt, fmt)
    project = slug(context.display_name()) or "report"
    kind = slug(deliverable.document_kind) or "report"
    when = (context.reporting_date or date.today()).isoformat()
    return f"{project}_{kind}_{when}.{extension}"


def slug(text: str, *, limit: int = 48) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip()).strip("-")
    return cleaned[:limit].strip("-")
