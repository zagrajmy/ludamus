"""Slug shape and the one rule for making a slug unique.

Every slugged row (events, sessions, facilitators, guilds, users, spaces,
tracks, fields, categories) sits in a `SlugField()` varchar(50), so one
generator serves them all: callers hand it the human text, never a slug.
"""

import re
import string
from secrets import choice
from typing import TYPE_CHECKING

from unidecode import unidecode

if TYPE_CHECKING:
    from collections.abc import Callable

SLUG_MAX_LENGTH = 50
# Each retry draws ~26 random bits; eight misses in a row means the check is
# lying (or every candidate is taken), not bad luck. The suffix alphabet has no
# dash, so a suffix can never double the separator or end on one.
_UNIQUE_SLUG_ATTEMPTS = 8
_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits
_SUFFIX_LENGTH = 5


class SlugCollisionError(Exception):
    # Raised when a unique slug can't be found within the retry budget, so the
    # caller fails loudly instead of handing a colliding slug to the DB.
    def __init__(self, base_slug: str) -> None:
        super().__init__(f"Could not generate a unique slug for {base_slug!r}.")
        self.base_slug = base_slug


def slugify(value: str, *, max_length: int = SLUG_MAX_LENGTH) -> str:
    # NOTE: the live TS preview (import-recipe.ts) only approximates this one.
    # Unidecode transliterates the full Unicode range (Polish ł/Ł, German ß,
    # CJK, etc.) rather than relying on NFKD decomposition, which silently
    # drops non-decomposable characters like ł. Capped at max_length to fit the
    # SlugField column; strip again so truncation never leaves a trailing dash.
    transliterated = unidecode(value).lower()
    slug = re.sub(r"[^\w\s-]", "", transliterated)
    # pragma: no mutate start
    return re.sub(r"[-\s]+", "-", slug).strip("-")[:max_length].strip("-")
    # pragma: no mutate end


def unique_slug(title: str, *, exists: Callable[[str], bool], fallback: str) -> str:
    """Slug `title` (or `fallback` when nothing sluggable is left) uniquely.

    Raises:
        SlugCollisionError: every candidate in the retry budget was taken.
    """
    base_slug = slugify(title) or slugify(fallback)
    slug = base_slug
    for _ in range(_UNIQUE_SLUG_ATTEMPTS):
        if not exists(slug):
            return slug
        suffix = "".join(choice(_SUFFIX_ALPHABET) for _ in range(_SUFFIX_LENGTH))
        trimmed = slugify(base_slug, max_length=SLUG_MAX_LENGTH - len(suffix) - 1)
        slug = f"{trimmed}-{suffix}"
    raise SlugCollisionError(base_slug)
