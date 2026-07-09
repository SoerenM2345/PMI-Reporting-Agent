"""Excel extractor (pandas + openpyxl). Highest-priority source."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.extractors.base import classify_table, find_progress_mentions, make_source, rows_to_records
from app.models.pmi import SourceFormat


def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    xls = pd.ExcelFile(path)
    for sheet in xls.sheet_names:
        df = xls.parse(sheet, header=None)
        if df.empty:
            continue
        header_idx = _find_header_row(df)
        if header_idx is None:
            continue
        headers = [str(c) if pd.notna(c) else "" for c in df.iloc[header_idx]]
        body = df.iloc[header_idx + 1:]
        rows = [[None if pd.isna(c) else c for c in row] for row in body.itertuples(index=False)]
        rtype = classify_table(headers, context=sheet)
        source = make_source(path.name, SourceFormat.EXCEL, location=f"sheet '{sheet}'")
        records.extend(rows_to_records(headers, rows, rtype, source))
        # scan stray cells for progress claims (e.g. a summary cell "Progress: 82%")
        text = " ".join(str(c) for c in df.to_numpy().flatten() if pd.notna(c))
        for pct in find_progress_mentions(text):
            records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                            "unit": "%", "source": source})
    return records


def _find_header_row(df: pd.DataFrame, scan: int = 10) -> int | None:
    """First row where >=2 cells map to known headers."""
    from app.extractors.base import normalize_header

    for i in range(min(scan, len(df))):
        hits = sum(1 for c in df.iloc[i] if pd.notna(c) and normalize_header(c))
        if hits >= 2:
            return i
    return None
