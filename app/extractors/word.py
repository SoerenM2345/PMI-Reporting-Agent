"""Word extractor (python-docx): tables + paragraphs (meeting notes, action items)."""
from __future__ import annotations

from pathlib import Path

from docx import Document

from app.extractors.base import (classify_table, extract_actions_from_text,
                                 find_progress_mentions, make_source, rows_to_records)
from app.models.pmi import SourceFormat


def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    doc = Document(str(path))
    source = make_source(path.name, SourceFormat.WORD)

    for t_idx, tbl in enumerate(doc.tables, start=1):
        grid = [[cell.text.strip() for cell in row.cells] for row in tbl.rows]
        if len(grid) >= 2:
            headers, rows = grid[0], grid[1:]
            rtype = classify_table(headers)
            src = make_source(path.name, SourceFormat.WORD, location=f"table {t_idx}")
            records.extend(rows_to_records(headers, rows, rtype, src))

    text = "\n".join(p.text for p in doc.paragraphs)
    for pct in find_progress_mentions(text):
        records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                        "unit": "%", "source": source})
    for item in extract_actions_from_text(text):
        records.append({**item, "source": source})
    if text.strip():
        records.append({"type": "note", "text": text.strip()[:4000], "source": source})
    return records
