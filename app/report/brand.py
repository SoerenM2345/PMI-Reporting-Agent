"""One brand, shared by every format.

The Deloitte palette used to live as `RGBColor`s in `pptx_report.py`, as hex
strings in `xlsx_dashboard.py`, again in `charts.py`, and a fourth time in the
frontend's Tailwind config. Four copies of `#046A38` is three chances for the
deck, the workbook, the charts and the dashboard to disagree about what green
means — and nothing tied them together.

These are the source of truth. The hex strings are what a stylesheet and
xlsxwriter want; `rgb()` hands the same values to python-pptx.

The logo is extracted once from the master template and cached base64, so the
HTML dashboard can inline it into a single self-contained file. When the
template is absent it falls back to a CSS wordmark — exactly as the pptx path
already falls back to a blank deck.
"""
from __future__ import annotations

import base64
import logging
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger("pmi.brand")

# The palette, as hex. `#046A38` is the dark green that reads on white; `#86BC25`
# is the signature accent.
GREEN = "#046A38"
BRIGHT = "#86BC25"
DARK = "#222222"
GREY = "#75787B"
RED = "#DA291C"
AMBER = "#F2A900"
WHITE = "#FFFFFF"

# The RAG palette, matching `frontend/tailwind.config.js`, `charts.py` and the
# workbook. RAG greens/ambers/reds are softer than the brand accents on purpose
# — a full-strength brand green on a status cell reads as decoration, not signal.
RAG_GREEN = "#2E7D32"
RAG_AMBER = "#F9A825"
RAG_RED = "#C62828"
RAG_GREY = "#757575"


def rgb(hex_color: str):
    """The colour as a python-pptx `RGBColor`, from the same hex the rest use."""
    from pptx.dml.color import RGBColor

    value = hex_color.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


@lru_cache(maxsize=1)
def logo_data_uri() -> Optional[str]:
    """The template's logo as a `data:` URI, or `None` if it cannot be had.

    Cached because it reads and decodes a zip member; a dashboard rebuilt on
    every generate should not re-open the pptx each time.
    """
    png = _logo_bytes()
    if png is None:
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _logo_bytes() -> Optional[bytes]:
    # A previously extracted copy wins — the template need not be present in a
    # deployed image once the logo has been vendored.
    vendored = _brand_dir() / "logo.png"
    if vendored.is_file():
        return vendored.read_bytes()

    from app.config import get_settings

    template = getattr(get_settings(), "pptx_template", None)
    if not template or not Path(template).is_file():
        return None

    try:
        with zipfile.ZipFile(template) as archive:
            media = [n for n in archive.namelist()
                     if n.startswith("ppt/media/") and n.lower().endswith(".png")]
            if not media:
                return None
            # The smallest PNG in a corporate master is almost always the logo;
            # the large ones are slide backgrounds and photography.
            smallest = min(media, key=lambda n: archive.getinfo(n).file_size)
            data = archive.read(smallest)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("could not extract a logo from %s (%s)", template, exc)
        return None

    # Vendor it so later runs — and images built without the template — still
    # have it.
    try:
        _brand_dir().mkdir(parents=True, exist_ok=True)
        vendored.write_bytes(data)
    except OSError:
        pass
    return data


def _brand_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "brand"
