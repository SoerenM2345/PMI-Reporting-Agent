"""PowerPoint extractor (python-pptx): tables + text frames."""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from app.extractors.base import (classify_table, extract_actions_from_text,
                                 find_progress_mentions, make_source, rows_to_records)
from app.models.pmi import SourceFormat


def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    prs = Presentation(str(path))
    for idx, slide in enumerate(prs.slides, start=1):
        source = make_source(path.name, SourceFormat.POWERPOINT, location=f"slide {idx}")
        slide_text_parts: list[str] = []
        title = ""
        for shape in slide.shapes:
            if shape.has_table:
                tbl = shape.table
                grid = [[cell.text.strip() for cell in row.cells] for row in tbl.rows]
                if len(grid) >= 2:
                    headers, rows = grid[0], grid[1:]
                    rtype = classify_table(headers, context=title)
                    records.extend(rows_to_records(headers, rows, rtype, source))
            if shape.has_text_frame:
                txt = shape.text_frame.text
                slide_text_parts.append(txt)
                if shape == slide.shapes.title:
                    title = txt
        text = "\n".join(slide_text_parts)
        for pct in find_progress_mentions(text):
            records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                            "unit": "%", "source": source})
        for item in extract_actions_from_text(text):
            records.append({**item, "source": source})
        if text.strip():
            records.append({"type": "note", "text": text.strip()[:2000], "source": source})
    return records
