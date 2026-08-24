"""Tiny inline previews of stored images (LQIP).

A cover image is the heaviest thing on a card and the last to arrive, so the
card spends its first moments as a hole. The preview is that image at twenty
pixels wide, small enough to inline into the HTML the card already ships, and
the browser stretches it back up into the blur that stands in until the real
bytes land.

Not to be confused with ``Event.use_session_cover_placeholders``, which picks a
stock cover for a session that has no image at all. This is a preview *of* an
image; that is a substitute *for* a missing one.
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

if TYPE_CHECKING:
    from django.core.files.base import File

logger = logging.getLogger(__name__)

# Twenty pixels wide is the knee of the curve: below it the blur loses the
# composition (a dark band where the sky was), above it the base64 grows faster
# than the fidelity. The result is upscaled by the browser, which interpolates
# smoothly, so the blur costs no filter and no second element.
PREVIEW_WIDTH = 20

# WEBP always: it beats JPEG at this size, keeps alpha, and pinning one format
# means the data URI's media type is a constant rather than something a caller
# has to trust.
PREVIEW_MEDIA_TYPE = "image/webp"
PREVIEW_QUALITY = 60

# The preview travels inline in every page that renders the image, so its cost
# is paid per render, not per download. A cover that will not encode under the
# cap gets no preview rather than a page weighed down by one.
PREVIEW_MAX_LENGTH = 1024


def _encode(image: Image.Image) -> str:
    # RGBA rather than RGB: a palette image with transparency would otherwise
    # flatten onto black, and at this size the extra channel costs bytes we
    # cannot measure.
    preview = ImageOps.exif_transpose(image).convert("RGBA")
    preview.thumbnail((PREVIEW_WIDTH, PREVIEW_WIDTH), Image.Resampling.BOX)
    buffer = BytesIO()
    preview.save(buffer, format="WEBP", quality=PREVIEW_QUALITY, method=6)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{PREVIEW_MEDIA_TYPE};base64,{encoded}"


def image_preview(file: File[bytes]) -> str:
    """Encode an image as a data URI small enough to inline.

    The file is left rewound: callers hand the same handle to storage right
    after, and a half-read upload would be saved truncated.

    Returns:
        A ``data:image/webp;base64,…`` URI, or empty string when the file
        cannot be read as an image or will not fit under the length cap.
    """
    try:
        file.open("rb")
        with Image.open(file) as image:
            uri = _encode(image)
    # UnidentifiedImageError is an OSError, and so is a storage read that dies
    # mid-stream. Either way there is no preview, and neither is worth failing
    # an upload over: the image itself was already validated on the way in, and
    # a page without a blur is a page.
    except OSError, ValueError:
        logger.warning("Could not build an inline preview for %r", file.name)
        return ""
    finally:
        file.seek(0)

    if len(uri) > PREVIEW_MAX_LENGTH:
        logger.warning(
            "Inline preview for %r came out at %d chars, over the %d cap",
            file.name,
            len(uri),
            PREVIEW_MAX_LENGTH,
        )
        return ""
    return uri
