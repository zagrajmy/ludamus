from typing import NamedTuple


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
