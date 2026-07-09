"""HTML extractor (BeautifulSoup4): tables + visible text. Lowest-priority source."""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from app.extractors.base import (classify_table, extract_actions_from_text,
                                 find_progress_mentions, make_source, rows_to_records)
from app.models.pmi import SourceFormat


def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    source = make_source(path.name, SourceFormat.HTML)

    for t_idx, tbl in enumerate(soup.find_all("table"), start=1):
        rows = []
        for tr in tbl.find_all("tr"):
            rows.append([td.get_text(strip=True) for td in tr.find_all(["td", "th"])])
        if len(rows) >= 2:
            src = make_source(path.name, SourceFormat.HTML, location=f"table {t_idx}")
            rtype = classify_table(rows[0])
            records.extend(rows_to_records(rows[0], rows[1:], rtype, src))

    text = soup.get_text("\n")
    for pct in find_progress_mentions(text):
        records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                        "unit": "%", "source": source})
    for item in extract_actions_from_text(text):
        records.append({**item, "source": source})
    return records
