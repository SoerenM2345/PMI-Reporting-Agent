"""CSV extractor (spec §5.1).

Ranked alongside Excel in source priority: a CSV export of a system tracker is the
same system of record, just without the formatting.

CSVs from PMI tools are messier than the format suggests — European exports use
semicolons, tools prepend a title row above the header, and encodings vary by
whoever hit "Export". All three are sniffed rather than assumed, because guessing
wrong here silently yields zero rows instead of an error.
"""
from __future__ import annotations

import csv as _csv
import io
from pathlib import Path

from app.extractors.base import (
    classify_table,
    find_progress_mentions,
    make_source,
    normalize_header,
    rows_to_records,
)
from app.models.pmi import ExtractionMethod, SourceFormat

suffixes: tuple[str, ...] = (".csv", ".tsv")
format: SourceFormat = SourceFormat.CSV

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_MAX_HEADER_SCAN = 10


def extract(path: Path) -> list[dict]:
    text = _read(path)
    if not text.strip():
        return []

    rows = list(_csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text, path)))
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return []

    header_idx = _find_header_row(rows)
    if header_idx is None:
        # No recognisable columns. Rather than drop the file, keep its text so free-text
        # extraction and progress mentions still have a chance.
        return _fallback_note(path, text)

    headers = [str(c).strip() for c in rows[header_idx]]
    body = rows[header_idx + 1:]

    record_type = classify_table(headers, context=path.stem)
    source = make_source(
        path.name, format,
        table_name=path.stem,
        extraction_method=ExtractionMethod.TABLE_PARSE,
    )
    # +2: CSV rows are 1-based, and the header itself occupies one.
    records = rows_to_records(headers, body, record_type, source,
                              first_data_row=header_idx + 2)

    for pct in find_progress_mentions(text):
        records.append({
            "type": "kpi", "name": "Overall Progress", "value": pct, "unit": "%",
            "source": source,
        })

    return records


def _read(path: Path) -> str:
    for encoding in _ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    # Last resort: keep going with replacement characters rather than losing the file.
    return path.read_text(encoding="utf-8", errors="replace")


def _sniff_delimiter(text: str, path: Path) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    try:
        return _csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
    except _csv.Error:
        # Sniffer fails on short or irregular files. Fall back to whichever candidate
        # appears most on the first line — a German export is full of semicolons.
        first = text.splitlines()[0] if text.splitlines() else ""
        return max(",;\t|", key=first.count)


def _find_header_row(rows: list[list[str]]) -> int | None:
    """First row where at least two cells map to fields we understand."""
    for i, row in enumerate(rows[:_MAX_HEADER_SCAN]):
        hits = sum(1 for c in row if c and normalize_header(c))
        if hits >= 2:
            return i
    return None


def _fallback_note(path: Path, text: str) -> list[dict]:
    source = make_source(path.name, format,
                         extraction_method=ExtractionMethod.TEXT_REGEX)
    records: list[dict] = [{
        "type": "note",
        "text": text[:2000],
        "source": source,
    }]
    for pct in find_progress_mentions(text):
        records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                        "unit": "%", "source": source})
    return records
