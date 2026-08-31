"""Upload validation shared by every gate that stores user images.

Single home for the size, pixel, format, and SVG-sanitization guarantees so
the web forms and the MCP tools can't drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.utils.translation import gettext
from lxml import etree
from PIL import Image, UnidentifiedImageError

from ludamus.pacts.images import ALLOWED_IMAGE_FORMATS

if TYPE_CHECKING:
    from collections.abc import Callable

    from lxml.etree import _Element as Element

MAX_IMAGE_SIZE = 8 * 1024 * 1024
# SAFETY: a small (≤8 MB) file can still decode to a huge bitmap; cap pixel
MAX_IMAGE_PIXELS = 24_000_000


class UploadValidationError(ValidationError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.problem = message


@runtime_checkable
class _CheckedImageUpload(Protocol):
    image: Image.Image


def validate_uploaded_image_size(image: object) -> None:
    if isinstance(image, File) and image.size > MAX_IMAGE_SIZE:
        raise UploadValidationError(gettext("Image too large. Maximum size is 8 MB."))


def _validate_raster(
    *, image_format: str | None, pixels: int, format_error: str
) -> None:
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise UploadValidationError(format_error)
    if pixels > MAX_IMAGE_PIXELS:
        raise UploadValidationError(gettext("Image dimensions are too large."))


def _raster_format_error() -> str:
    return gettext("Unsupported image format. Use JPG, PNG, WebP, or AVIF.")


def validate_uploaded_image_format(image: object) -> None:
    pil_image = image.image if isinstance(image, _CheckedImageUpload) else None
    _validate_raster(
        image_format=pil_image.format if pil_image else None,
        pixels=pil_image.width * pil_image.height if pil_image else 0,
        format_error=_raster_format_error(),
    )


def validate_uploaded_image(image: object) -> None:
    if image:
        validate_uploaded_image_size(image)
        validate_uploaded_image_format(image)


_SVG_FORBIDDEN_TAGS = frozenset({"script", "foreignobject"})
# SAFETY: libxml2 caps entity amplification (no billion laughs); unresolved
_SVG_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def _xml_local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _xml_text(value: str | bytes) -> str:
    return value if isinstance(value, str) else value.decode(errors="replace")


def _svg_element_is_safe(element: Element) -> bool:
    if _xml_local_name(str(element.tag)) in _SVG_FORBIDDEN_TAGS:
        return False
    for name, value in element.attrib.items():
        if _xml_local_name(_xml_text(name)).startswith("on"):
            return False
        if "javascript:" in "".join(_xml_text(value).split()).lower():
            return False
    return True


def _validate_uploaded_svg(uploaded: File[bytes]) -> None:
    uploaded.seek(0)
    content: bytes = uploaded.read()
    uploaded.seek(0)
    try:
        # SAFETY: fromstring, not parse: parse() takes a filename too, so
        root: Element = etree.fromstring(content, _SVG_PARSER)
    except SyntaxError as error:
        raise UploadValidationError(gettext("Invalid or unsafe SVG file.")) from error
    if _xml_local_name(str(root.tag)) != "svg" or not all(
        _svg_element_is_safe(element) for element in root.iter(etree.Element)
    ):
        raise UploadValidationError(gettext("Invalid or unsafe SVG file."))


def _validate_raster_upload(uploaded: File[bytes], *, format_error: str) -> None:
    uploaded.seek(0)
    try:
        with Image.open(uploaded) as pil_image:
            image_format = pil_image.format
            pixels = pil_image.width * pil_image.height
    except UnidentifiedImageError:
        image_format, pixels = None, 0
    except Image.DecompressionBombError as error:
        raise UploadValidationError(
            gettext("Image dimensions are too large.")
        ) from error
    finally:
        uploaded.seek(0)
    _validate_raster(
        image_format=image_format, pixels=pixels, format_error=format_error
    )


def _looks_like_svg(uploaded: File[bytes]) -> bool:
    uploaded.seek(0)
    head: bytes = uploaded.read(64)
    uploaded.seek(0)
    return head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<")


def validate_uploaded_logo(uploaded: File[bytes] | None) -> None:
    if not uploaded:
        return
    validate_uploaded_image_size(uploaded)
    if _looks_like_svg(uploaded):
        _validate_uploaded_svg(uploaded)
    else:
        _validate_raster_upload(
            uploaded,
            format_error=gettext(
                "Unsupported image format. Use JPG, PNG, WebP, AVIF, or SVG."
            ),
        )


def validate_uploaded_cover(uploaded: File[bytes] | None) -> None:
    if not uploaded:
        return
    validate_uploaded_image_size(uploaded)
    _validate_raster_upload(uploaded, format_error=_raster_format_error())


def upload_error(
    validate: Callable[[File[bytes]], None], uploaded: File[bytes]
) -> str | None:
    try:
        validate(uploaded)
    except UploadValidationError as error:
        return error.problem
    return None
