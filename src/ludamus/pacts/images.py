from pathlib import PurePosixPath
from typing import Literal, NamedTuple


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

ORIGINAL_FILENAME_MAX_LENGTH = 255

# Which way a cover upload loses pixels once it is placed. Covers that meet a
# full-bleed banner ("edges") are cropped on both axes; covers that only ever
# sit in a wide strip inside a card ("top-and-bottom") keep their full width.
# The upload help text and the dropzone's crop guide both follow from it.
CoverCrop = Literal["edges", "top-and-bottom"]


def original_filename(name: str) -> str:
    return PurePosixPath(name.replace("\\", "/")).name[:ORIGINAL_FILENAME_MAX_LENGTH]


class StoredFile(NamedTuple):
    url: str
    original_name: str = ""


def stored_file(url: str, original_name: str = "") -> StoredFile | None:
    return StoredFile(url, original_name) if url else None
