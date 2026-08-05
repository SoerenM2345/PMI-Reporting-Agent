"""Dispatch: file extension -> extractor (PDF spec slide 5, step 3)."""
from __future__ import annotations

from pathlib import Path

from app.extractors import excel, html, image, pdf, powerpoint, word

EXTENSION_MAP = {
    ".xlsx": excel.extract,
    ".xlsm": excel.extract,
    ".xls": excel.extract,
    ".pptx": powerpoint.extract,
    ".docx": word.extract,
    ".pdf": pdf.extract,
    ".html": html.extract,
    ".htm": html.extract,
    ".png": image.extract,
    ".jpg": image.extract,
    ".jpeg": image.extract,
}

SUPPORTED_EXTENSIONS = set(EXTENSION_MAP)


def extract_file(path: Path) -> list[dict]:
    fn = EXTENSION_MAP.get(path.suffix.lower())
    if fn is None:
        raise ValueError(f"Unsupported file type: {path.suffix} ({path.name})")
    return fn(path)
