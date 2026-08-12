import re
from posixpath import basename
from typing import NamedTuple
from urllib.parse import unquote, urlsplit


class ImageFormat(NamedTuple):
    # Pillow reports `pil_name` for a decoded upload, browsers match `mime` in an
    # `accept` attribute, and `suffixes` is what may end up in a stored filename.
    # Same format, three vocabularies — keep them in one row so adding a format
    # can't leave one of the three behind.
    pil_name: str
    mime: str
    suffixes: tuple[str, ...]


IMAGE_FORMATS = (
    ImageFormat(pil_name="JPEG", mime="image/jpeg", suffixes=(".jpg", ".jpeg")),
    ImageFormat(pil_name="PNG", mime="image/png", suffixes=(".png",)),
    ImageFormat(pil_name="WEBP", mime="image/webp", suffixes=(".webp",)),
    ImageFormat(pil_name="AVIF", mime="image/avif", suffixes=(".avif",)),
)

ALLOWED_IMAGE_FORMATS = frozenset(f.pil_name for f in IMAGE_FORMATS)
IMAGE_ACCEPT = ",".join(f.mime for f in IMAGE_FORMATS)
IMAGE_SUFFIXES = frozenset(s for f in IMAGE_FORMATS for s in f.suffixes)

SVG_MIME = "image/svg+xml"
SVG_SUFFIX = ".svg"
LOGO_ACCEPT = f"{IMAGE_ACCEPT},{SVG_MIME}"
UPLOAD_SUFFIXES = IMAGE_SUFFIXES | {SVG_SUFFIX}

_HASHED_BASENAME = re.compile(r"^[0-9a-f]{32}(?:\.[a-z0-9]+)?$", re.IGNORECASE)


def stored_file_display_name(path: str) -> str:
    name = unquote(basename(urlsplit(path).path))
    if not name or _HASHED_BASENAME.fullmatch(name):
        return ""
    return name
