from typing import NamedTuple

from pydantic import BaseModel


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


class StoredFile(NamedTuple):
    url: str
    original_name: str = ""


def stored_file(url: str, original_name: str = "") -> StoredFile | None:
    return StoredFile(url, original_name) if url else None


class HasStoredCover(BaseModel):
    cover_image_url: str = ""
    cover_image_original_name: str = ""

    @property
    def stored_cover(self) -> StoredFile | None:
        return stored_file(self.cover_image_url, self.cover_image_original_name)


class HasStoredLogo(BaseModel):
    logo_url: str = ""
    logo_original_name: str = ""

    @property
    def stored_logo(self) -> StoredFile | None:
        return stored_file(self.logo_url, self.logo_original_name)


class HasStoredHeader(BaseModel):
    header_image_url: str = ""
    header_image_original_name: str = ""

    @property
    def stored_header(self) -> StoredFile | None:
        return stored_file(self.header_image_url, self.header_image_original_name)
