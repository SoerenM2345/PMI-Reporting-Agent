"""HTML extractor (spec §5.5): exported project portals, dashboards, emails saved as HTML.

Ranked low in source priority (§9) — an HTML export is a rendering of a system,
usually stale by the time it lands in someone's inbox.

Uses lxml where available (faster, and far more tolerant of the malformed markup
that email exports are made of), falling back to the stdlib parser.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from app.extractors.base import (
    classify_table,
    extract_actions_from_text,
    find_progress_mentions,
    make_source,
    rows_to_records,
)
from app.models.pmi import ExtractionMethod, SourceFormat

suffixes: tuple[str, ...] = (".html", ".htm")
format: SourceFormat = SourceFormat.HTML

#: Markup that carries no information for us — and, left in, poisons the text pass
#: with CSS rules and JavaScript that regexes happily mistake for content.
_NOISE = ("script", "style", "noscript", "svg", "head")


def extract(path: Path) -> list[dict]:
    soup = BeautifulSoup(
        path.read_text(encoding="utf-8", errors="replace"), _parser()
    )
    for tag in soup(_NOISE):
        tag.decompose()

    records: list[dict] = []

    for index, table in enumerate(soup.find_all("table"), start=1):
        rows = [
            [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
            for tr in table.find_all("tr")
        ]
        rows = [r for r in rows if any(r)]
        if len(rows) < 2:
            continue

        caption = table.find("caption")
        name = caption.get_text(strip=True) if caption else f"table {index}"
        source = make_source(
            path.name, format,
            table_name=name,
            extraction_method=ExtractionMethod.TABLE_PARSE,
        )
        records.extend(rows_to_records(
            rows[0], rows[1:], classify_table(rows[0], context=name), source,
        ))

    text = soup.get_text("\n")
    source = make_source(path.name, format,
                         extraction_method=ExtractionMethod.TEXT_REGEX)

    for pct in find_progress_mentions(text):
        records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                        "unit": "%", "source": source})
    for item in extract_actions_from_text(text):
        records.append({**item, "source": source})

    # The original extractor emitted no note record here, unlike every other format —
    # so free text in an exported status page was read for actions and progress, then
    # thrown away.
    body = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if body:
        records.append({"type": "note", "text": body[:2000], "source": source})

    return records


def _parser() -> str:
    try:
        import lxml  # noqa: F401

        return "lxml"
    except ImportError:
        return "html.parser"
