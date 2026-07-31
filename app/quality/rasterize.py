"""Turn a rendered artifact into page images, where that is possible.

PDF and HTML rasterise with PyMuPDF, which is already a dependency. **PowerPoint
does not**: only a real layout engine can lay out a `.pptx`, and the only one
available is LibreOffice, which is not installed here.

`pptx_pages` therefore returns `None` rather than raising or, worse, returning
something approximate. Callers skip; `app/quality/overflow.py` does the analytic
checks instead and its docstring says plainly what that does and does not catch.
The alternative — silently substituting a weaker check — would let a green test
suite imply somebody had looked at the deck.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("pmi.quality.rasterize")

DEFAULT_DPI = 110
#: LibreOffice on a cold start is slow, and a hung conversion must not hang a
#: request.
SOFFICE_TIMEOUT_S = 120


def has_soffice() -> bool:
    """Whether a PowerPoint file can be rasterised on this machine at all."""
    return soffice_path() is not None


def soffice_path() -> Optional[str]:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(mac) if mac.is_file() else None


def pdf_pages(path: Path, *, dpi: int = DEFAULT_DPI,
              limit: int = 40) -> list[bytes]:
    """Each page as PNG bytes."""
    import fitz

    out: list[bytes] = []
    with fitz.open(str(path)) as document:
        for page in list(document)[:limit]:
            out.append(page.get_pixmap(dpi=dpi).tobytes("png"))
    return out


def html_pages(path: Path, *, dpi: int = DEFAULT_DPI) -> list[bytes]:
    """Rasterise a dashboard, via PyMuPDF's Story API.

    This is a rough approximation: the Story API is not a browser and ignores
    most of the CSS. It is enough to catch a page that renders empty, and not
    enough to review a layout. Stated rather than implied.
    """
    import fitz

    try:
        story = fitz.Story(html=path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "story.pdf"
            writer = fitz.DocumentWriter(str(pdf))
            rect = fitz.paper_rect("a4")
            more = 1
            while more:
                device = writer.begin_page(rect)
                more, _ = story.place(rect + (36, 36, -36, -36))
                story.draw(device)
                writer.end_page()
            writer.close()
            return pdf_pages(pdf, dpi=dpi)
    except Exception as exc:                                   # noqa: BLE001
        log.info("could not rasterise the dashboard (%s)", exc)
        return []


def pptx_pages(path: Path, *, dpi: int = DEFAULT_DPI) -> Optional[list[bytes]]:
    """Each slide as PNG bytes, or `None` when LibreOffice is unavailable.

    `None` means "not checked", never "checked and fine".
    """
    binary = soffice_path()
    if binary is None:
        log.info("LibreOffice is not installed; the deck was not rasterised. "
                 "Visual checking of the deck is analytic only.")
        return None

    with tempfile.TemporaryDirectory() as directory:
        try:
            subprocess.run(
                [binary, "--headless", "--convert-to", "pdf", "--outdir",
                 directory, str(path)],
                check=True, capture_output=True, timeout=SOFFICE_TIMEOUT_S)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                OSError) as exc:
            log.warning("LibreOffice could not convert %s (%s)", path.name, exc)
            return None
        pdf = Path(directory) / f"{path.stem}.pdf"
        return pdf_pages(pdf, dpi=dpi) if pdf.is_file() else None


def pages(path: Path, *, dpi: int = DEFAULT_DPI) -> Optional[list[bytes]]:
    """Rasterise whatever this is, or `None` if it cannot be done here."""
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return pdf_pages(path, dpi=dpi)
    if suffix in (".html", ".htm"):
        return html_pages(path, dpi=dpi)
    if suffix == ".pptx":
        return pptx_pages(path, dpi=dpi)
    return None


def is_blank(png: bytes, *, threshold: int = 6) -> bool:
    """Whether a page image is effectively one flat colour."""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(png)) as image:
        small = image.convert("L").resize((64, 64))
        return len(set(small.getdata())) < threshold
