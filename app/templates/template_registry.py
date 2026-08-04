"""Load a template once and hand out its catalog and brand system.

Reading the Deloitte master means opening a 920 KB zip, parsing a theme and
walking 59 layouts. Generation may plan, render, critique and re-render inside
one request, so this is cached on the file's content digest — a template swapped
on disk invalidates it, a template merely re-read does not.

Generation never hard-depends on the asset. When the configured template is
missing or unreadable the registry falls back to python-pptx's own default
presentation, records a `note` explaining exactly what was lost, and continues:
the brand tokens then come from the built-in defaults rather than from a file.
That is the same posture the rest of the app takes toward a missing input —
degrade visibly, never silently.
"""
from __future__ import annotations

import hashlib
import logging
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.templates import brand_system, extract_layouts, extract_theme, layout_catalog
from app.templates.brand_system import BrandSystem
from app.templates.extract_layouts import TemplateLayout
from app.templates.inspect_pptx import inspect
from app.templates.layout_catalog import LayoutCatalog

log = logging.getLogger("pmi.templates.registry")

#: Bumped when this package's extraction semantics change, so a cached
#: `system_id` from an older build is not mistaken for a current one.
EXTRACTOR_VERSION = 1


class TemplateReference(BaseModel):
    """Everything a renderer needs to know about the template it is drawing on."""

    template_path: str = ""
    template_digest: str = ""
    available: bool = True
    catalog: LayoutCatalog
    brand: BrandSystem
    slide_w_in: float = 13.3333
    slide_h_in: float = 7.5
    master_count: int = 0
    layout_count: int = 0
    #: The template ships no table styles, so every table property must be set
    #: explicitly. True for the Deloitte master, whose `tableStyles.xml` is a
    #: 182-byte stub.
    needs_explicit_table_styles: bool = True
    notes: list[str] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return Path(self.template_path).name if self.template_path else "(none)"

    def layout(self, layout_id: str) -> Optional[TemplateLayout]:
        return self.catalog.by_id(layout_id)


def digest(path: Path | str) -> str:
    """A short content digest, used both for caching and for staleness."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    return hashlib.sha1(data).hexdigest()[:16]


def load(path: Path | str | None = None) -> TemplateReference:
    """The template reference for `path`, or the configured default."""
    resolved = Path(path) if path is not None else _configured()
    return _load_cached(str(resolved), digest(resolved))


def default() -> TemplateReference:
    return load(None)


def reset_cache() -> None:
    """Drop the cache. Tests that write a template to a tmp_path need this."""
    _load_cached.cache_clear()


# --------------------------------------------------------------- internals
@lru_cache(maxsize=4)
def _load_cached(path_str: str, content_digest: str) -> TemplateReference:
    path = Path(path_str)
    notes: list[str] = []

    if not content_digest or not path.is_file():
        fallback = _pptx_default_template()
        notes.append(
            f"No PowerPoint template at {path}. Slides will use python-pptx's "
            f"default master, so the brand background, logo and Aptos typography "
            f"are not applied; brand colours fall back to built-in defaults."
        )
        if fallback is None:
            raise FileNotFoundError(
                f"no template at {path} and python-pptx's default is unavailable")
        source, available = fallback, False
    else:
        source, available = path, True

    template = inspect(source)
    palette = extract_theme.extract(template.theme_xml, template.master_xml,
                                    template.layout_xml)
    layouts = extract_layouts.build(template, palette)
    catalog = layout_catalog.build(layouts)

    system_id = hashlib.sha1(
        f"{content_digest}:{EXTRACTOR_VERSION}".encode("ascii")).hexdigest()[:16]
    brand = brand_system.build(
        palette, layouts,
        slide_w_in=template.slide_w_in, slide_h_in=template.slide_h_in,
        source=str(source), system_id=system_id,
        logo_png=_logo_bytes(source) if available else None,
        # A substitute template supplies layouts, never a brand: inheriting
        # python-pptx's Office theme would silently reissue the deliverable in
        # Microsoft's palette.
        derive_brand=available,
    )
    notes.extend(brand.notes)

    if not template.defines_table_styles:
        notes.append("The template defines no table styles, so table formatting "
                     "is applied explicitly rather than inherited.")

    reference = TemplateReference(
        template_path=str(source),
        template_digest=content_digest,
        available=available,
        catalog=catalog,
        brand=brand,
        slide_w_in=template.slide_w_in,
        slide_h_in=template.slide_h_in,
        master_count=template.master_count,
        layout_count=len(layouts),
        needs_explicit_table_styles=not template.defines_table_styles,
        notes=notes,
    )
    log.info("template %s ready: %d layouts, brand %s%s", reference.name,
             reference.layout_count, brand.system_id,
             "" if available else " (FALLBACK — configured template missing)")
    return reference


def _configured() -> Path:
    from app.config import get_settings

    return Path(get_settings().pptx_template)


def _pptx_default_template() -> Optional[Path]:
    try:
        import pptx

        candidate = Path(pptx.__file__).parent / "templates" / "default.pptx"
        return candidate if candidate.is_file() else None
    except Exception:                                          # noqa: BLE001
        return None


def _logo_bytes(path: Path) -> Optional[bytes]:
    """A visible-on-white logo, cropped for report and dashboard covers.

    The Deloitte master contains both dark and white wordmarks. Choosing only by
    compressed file size selected the white variant, which disappeared on Word's
    white cover except for its green dot. Prefer the smallest candidate with
    meaningful dark pixels, then crop transparent master-slide padding.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            media = [n for n in archive.namelist()
                     if n.startswith("ppt/media/") and n.lower().endswith(".png")]
            if not media:
                return None
            candidates = [archive.read(name) for name in media]
            visible = [data for data in candidates if _has_dark_wordmark(data)]
            chosen = min(visible or candidates, key=len)
            return _crop_transparency(chosen)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:    # noqa: BLE001
        log.debug("no logo extracted from %s (%s)", path, exc)
        return None


def _has_dark_wordmark(data: bytes) -> bool:
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGBA")
        return sum(1 for red, green, blue, alpha in image.get_flattened_data()
                   if alpha > 96 and red < 96 and green < 96 and blue < 96) > 1000
    except Exception:                                          # noqa: BLE001
        return False


def _crop_transparency(data: bytes) -> bytes:
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGBA")
        bounds = image.getchannel("A").getbbox()
        if not bounds:
            return data
        cropped = image.crop(bounds)
        output = io.BytesIO()
        cropped.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except Exception:                                          # noqa: BLE001
        return data
