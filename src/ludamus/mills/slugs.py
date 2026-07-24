"""Unique-slug generation shared by the panel create services."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# 45 keeps base + "-XXXX" retry suffix within SlugField's varchar(50).
_SLUG_BASE_MAX_LENGTH = 45


def unique_slug(*, base: str, default: str, exists: Callable[[str], bool]) -> str:
    capped = (base or default)[:_SLUG_BASE_MAX_LENGTH]
    slug = capped
    for _attempt in range(4):
        if not exists(slug):
            break
        slug = f"{capped}-{token_urlsafe(3)}"
    return slug
