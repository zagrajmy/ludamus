"""Slug shape shared by the gates' previews and the mills' generators."""

import re

from unidecode import unidecode


def slugify(value: str, *, max_length: int = 50) -> str:
    # ASCII slug mirroring the live TS preview (simov/slugify with locale="pl").
    # Unidecode transliterates the full Unicode range (Polish ł/Ł, German ß,
    # CJK, etc.) rather than relying on NFKD decomposition, which silently
    # drops non-decomposable characters like ł. Capped at max_length to fit the
    # SlugField column (default 50); strip again so truncation never leaves a
    # trailing dash.
    transliterated = unidecode(value).lower()
    slug = re.sub(r"[^\w\s-]", "", transliterated)
    # pragma: no mutate start
    return re.sub(r"[-\s]+", "-", slug).strip("-")[:max_length].strip("-")
    # pragma: no mutate end
