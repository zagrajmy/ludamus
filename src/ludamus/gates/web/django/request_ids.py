"""Ids a request carries in its query string or body.

`str.isdigit()` is true for superscripts and other non-ASCII digits that
`int()` then refuses, and `int()` alone takes signs, underscores and Arabic-
Indic digits. An id is ASCII digits and nothing else; whatever is not one reads
as absent, so a tampered value narrows nothing instead of crashing the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# NOTE: a primary key is a 64-bit integer at most, and `int()` refuses strings
# past 4300 digits outright.
MAX_ID_DIGITS = 18


def parse_id(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = raw.strip()
    if not (text.isascii() and text.isdigit()) or len(text) > MAX_ID_DIGITS:
        return None
    return int(text)


def parse_ids(raws: Iterable[str]) -> list[int]:
    # Order kept, duplicates kept: a caller that means a set builds one.
    return [pk for raw in raws if (pk := parse_id(raw)) is not None]
