"""PDF extractor (pdfplumber): tables + page text."""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from app.extractors.base import (classify_table, extract_actions_from_text,
                                 find_progress_mentions, make_source, rows_to_records)
from app.models.pmi import SourceFormat


def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for p_idx, page in enumerate(pdf.pages, start=1):
            source = make_source(path.name, SourceFormat.PDF, location=f"page {p_idx}")
            for tbl in page.extract_tables() or []:
                if tbl and len(tbl) >= 2:
                    headers = [h or "" for h in tbl[0]]
                    rtype = classify_table(headers)
                    records.extend(rows_to_records(headers, tbl[1:], rtype, source))
            text = page.extract_text() or ""
            for pct in find_progress_mentions(text):
                records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                                "unit": "%", "source": source})
            for item in extract_actions_from_text(text):
                records.append({**item, "source": source})
            if text.strip():
                records.append({"type": "note", "text": text.strip()[:2000], "source": source})
    return records
