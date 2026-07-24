"""Image preprocessing and quality assessment (spec §5.6, steps 1-4).

Deterministic Python only — no model involved. This module answers "what are we
looking at, and how legible is it?", which is what lets the extractor score
confidence honestly instead of taking the model's word for it (§21.14).

§5.6 lists the reasons an image reading should be trusted less: low resolution,
blur, handwriting, cropping, unclear traffic-light colours, overlapping values.
The first two are measurable here; the rest come back from the vision pass.
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Literal, Optional

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from app.config import get_settings

log = logging.getLogger("pmi.images")

SUPPORTED_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg")

#: Below this, text in a screenshot is usually unreliable.
_LOW_RES_EDGE = 800
#: Variance-of-Laplacian below this reads as blurry. The classic threshold; it is a
#: heuristic, so it lowers confidence rather than rejecting the image.
_BLUR_THRESHOLD = 100.0


class ImageQuality(BaseModel):
    """Measured, not guessed."""

    width: int
    height: int
    max_edge: int
    is_low_res: bool
    blur_score: float
    is_blurry: bool
    #: preprocessed px -> original px, so regions map back to the user's own file.
    scale_factor: float = 1.0

    @property
    def penalty(self) -> float:
        """Confidence multiplier from measurable image quality alone."""
        factor = 1.0
        if self.is_low_res:
            factor *= 0.85
        if self.is_blurry:
            factor *= 0.90
        return factor


class PreparedImage(BaseModel):
    b64: str
    media_type: Literal["image/png", "image/jpeg"]
    quality: ImageQuality


class UnreadableImage(RuntimeError):
    """The file is not a decodable image."""


def prepare(path: Path, max_edge: Optional[int] = None) -> PreparedImage:
    """Validate, orient, resize and (gently) enhance an image for interpretation.

    Steps 1-4 of §5.6, in order.
    """
    max_edge = max_edge or get_settings().image_max_edge_px

    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:
        raise UnreadableImage(f"{path.name} is not a readable image: {exc}") from exc

    # 2. Correct orientation from EXIF. A phone photo of a whiteboard is routinely
    #    stored rotated with an orientation tag; ignoring it feeds the model a
    #    sideways image, which is a large and entirely avoidable accuracy loss.
    image = ImageOps.exif_transpose(image)
    original_width, original_height = image.size

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    quality_before = _measure(image)

    # 3. Resize. Beyond ~1568px on the long edge the model downsamples anyway, so a
    #    4000px screenshot only costs tokens.
    scale = 1.0
    if max(image.size) > max_edge:
        scale = max(image.size) / max_edge
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)

    # 4. Improve contrast — but only where it helps. Autocontrast on an already
    #    well-exposed screenshot can crush the pale amber of a RAG indicator into
    #    white, destroying the very signal §5.6 warns us to read carefully.
    if _is_low_contrast(image):
        image = ImageOps.autocontrast(image, cutoff=1)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)

    quality = ImageQuality(
        width=original_width,
        height=original_height,
        max_edge=max(original_width, original_height),
        is_low_res=max(original_width, original_height) < _LOW_RES_EDGE,
        blur_score=quality_before.blur_score,
        is_blurry=quality_before.is_blurry,
        scale_factor=scale,
    )

    return PreparedImage(
        b64=base64.standard_b64encode(buffer.getvalue()).decode(),
        media_type="image/png",
        quality=quality,
    )


# ------------------------------------------------------------------- internals
class _Measured(BaseModel):
    blur_score: float
    is_blurry: bool


def _measure(image: Image.Image) -> _Measured:
    """Variance of the Laplacian: low variance = few sharp edges = blurry."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - declared dependency
        return _Measured(blur_score=_BLUR_THRESHOLD, is_blurry=False)

    grey = np.asarray(image.convert("L"), dtype=float)
    if grey.size == 0 or min(grey.shape) < 3:
        return _Measured(blur_score=0.0, is_blurry=True)

    # 3x3 Laplacian via slicing — avoids an OpenCV dependency for one convolution.
    laplacian = (
        -4 * grey[1:-1, 1:-1]
        + grey[:-2, 1:-1] + grey[2:, 1:-1]
        + grey[1:-1, :-2] + grey[1:-1, 2:]
    )
    score = float(laplacian.var())
    return _Measured(blur_score=score, is_blurry=score < _BLUR_THRESHOLD)


def _is_low_contrast(image: Image.Image) -> bool:
    """True when the histogram occupies a narrow band, i.e. a washed-out photo."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return False

    grey = np.asarray(image.convert("L"), dtype=float)
    if grey.size == 0:
        return False
    spread = float(np.percentile(grey, 95) - np.percentile(grey, 5))
    return spread < 100.0  # full range is 255


def rescale_region(
    box: tuple[int, int, int, int], quality: ImageQuality
) -> tuple[int, int, int, int]:
    """Map a box from the prepared image back into the ORIGINAL image's pixels.

    The user will open their own screenshot, not our resized copy, so a region that
    only makes sense in our coordinate space is worse than no region at all.
    """
    factor = quality.scale_factor or 1.0
    x, y, width, height = box
    return (
        int(round(x * factor)),
        int(round(y * factor)),
        int(round(width * factor)),
        int(round(height * factor)),
    )
