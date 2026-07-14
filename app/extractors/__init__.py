"""Dispatch: file extension -> extractor (spec §5).

Each extractor module declares the suffixes it claims and the `SourceFormat` it
produces, so the table below is derived rather than hand-maintained — adding an
extractor means writing the module, not remembering to register it twice.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app.extractors import csv, excel, html, image, pdf, powerpoint, word
from app.models.pmi import SourceFormat

log = logging.getLogger("pmi.extract")

#: Every format in spec §4 step 1: spreadsheets, presentations, documents, web, images.
_MODULES = (excel, csv, powerpoint, word, pdf, html, image)

EXTENSION_MAP: dict[str, Callable[[Path], list[dict]]] = {
    suffix: module.extract
    for module in _MODULES
    for suffix in module.suffixes
}

FORMAT_MAP: dict[str, SourceFormat] = {
    suffix: module.format
    for module in _MODULES
    for suffix in module.suffixes
}

SUPPORTED_EXTENSIONS = frozenset(EXTENSION_MAP)


def extract_file(path: Path) -> list[dict]:
    """Run the right extractor. Raises ValueError on an unsupported type — the
    caller (the upload route, the graph) decides whether that sinks the run."""
    extractor = EXTENSION_MAP.get(path.suffix.lower())
    if extractor is None:
        raise ValueError(
            f"Unsupported file type '{path.suffix}' ({path.name}). "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    records = extractor(path)
    log.info("%s -> %d record(s)", path.name, len(records))
    return records


def format_of(path: Path) -> SourceFormat | None:
    return FORMAT_MAP.get(path.suffix.lower())
