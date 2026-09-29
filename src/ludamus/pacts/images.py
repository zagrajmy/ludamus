from pathlib import PurePosixPath
from typing import Literal, NamedTuple, Protocol, runtime_checkable


@runtime_checkable
class UploadedFileProtocol(Protocol):
    name: str | None

    def read(self, size: int = -1) -> bytes: ...


def parse_uploaded_file(value: object) -> UploadedFileProtocol | None:
    # Boundary parser: recover a typed upload from the untyped form-data value
    # (a file on upload, "" / False / None otherwise), so callers narrow once
    # here instead of casting.
    return value if isinstance(value, UploadedFileProtocol) else None


def resolve_uploaded_file_field(raw: object) -> UploadedFileProtocol | str | None:
    # ClearableFileInput's tri-state in one place: a file on upload becomes the
    # new value, False clears it (""), and any other value (None / unchanged)
    # returns None so the caller leaves the stored file untouched.
    if uploaded := parse_uploaded_file(raw):
        return uploaded
    return "" if raw is False else None


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
