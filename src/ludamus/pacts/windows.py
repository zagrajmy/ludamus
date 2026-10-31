"""Half-open time windows: a window holds `start` and stops just before `end`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

type Window = tuple[datetime, datetime]


def windows_overlap(window: Window, other: Window) -> bool:
    start, end = window
    other_start, other_end = other
    return start < other_end and other_start < end
