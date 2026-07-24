"""Unique-slug generation shared by the panel create services."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Cap the base at 45 so neither it nor a "-XXXX" retry suffix overflows the
# SlugField() varchar(50) column — Postgres raises DataError on overflow, SQLite
# ignores the limit, so an over-long title 500s only in production.
_SLUG_BASE_MAX_LENGTH = 45


def unique_slug(*, base: str, default: str, exists: Callable[[str], bool]) -> str:
    # `base` arrives already slugified — mills can't import Django's slugify,
    # so the gate does that half. Cap after the fallback so an over-long
    # default can't overflow either.
    capped = (base or default)[:_SLUG_BASE_MAX_LENGTH]
    slug = capped
    for _attempt in range(4):
        if not exists(slug):
            break
        slug = f"{capped}-{token_urlsafe(3)}"
    return slug
