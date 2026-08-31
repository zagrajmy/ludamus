"""Enrollment windows: who a window is for, and when it is theirs.

The window policy the rest of the enrollment mills read: which windows an
actor is allowed into, what seating they get from them, and — for a stored
window, which knows its period — whether one is open now or still to come.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ludamus.pacts.enrollment import EnrollmentAccessDTO

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime


class EnrollmentWindowLike(Protocol):
    allow_anonymous_enrollment: bool
    max_waitlist_sessions: int
    percentage_slots: int
    restrict_to_configured_users: bool


class DatedEnrollmentWindow(EnrollmentWindowLike, Protocol):
    """A stored window: it knows its period and can be named by id."""

    end_time: datetime
    pk: int
    start_time: datetime


def admits(window: EnrollmentWindowLike, *, is_configured_user: bool) -> bool:
    """Answer whether this actor is allowed into this window at all.

    Returns:
        True when the window is open to everyone, or the actor holds passes.
    """
    return is_configured_user or not window.restrict_to_configured_users


def _seating_rank(window: EnrollmentWindowLike) -> tuple[int, bool]:
    return (window.percentage_slots, not window.restrict_to_configured_users)


def restricts_everyone(windows: Iterable[EnrollmentWindowLike]) -> bool:
    listed = list(windows)
    return (
        bool(listed)
        and not EnrollmentPolicy.for_actor(listed, is_configured_user=False).can_enroll
    )


@dataclass(frozen=True)
class EnrollmentPolicy:
    """What one actor may do across the enrollment windows open to them.

    A window grants access for its period, so the windows an actor can use are
    unioned. Selecting first and aggregating second is what keeps capacity from
    being drawn from a window the actor is not allowed into.
    """

    windows: tuple[EnrollmentWindowLike, ...]

    @classmethod
    def for_actor(
        cls, windows: Iterable[EnrollmentWindowLike], *, is_configured_user: bool
    ) -> EnrollmentPolicy:
        return cls(
            tuple(
                window
                for window in windows
                if admits(window, is_configured_user=is_configured_user)
            )
        )

    @classmethod
    def for_anonymous(cls, windows: Iterable[EnrollmentWindowLike]) -> EnrollmentPolicy:
        usable_windows = cls.for_actor(windows, is_configured_user=False).windows
        return cls(
            tuple(
                window for window in usable_windows if window.allow_anonymous_enrollment
            )
        )

    @property
    def can_enroll(self) -> bool:
        return bool(self.windows)

    @property
    def seating_window(self) -> EnrollmentWindowLike | None:
        if not self.windows:
            return None
        return max(self.windows, key=_seating_rank)

    @property
    def percentage_slots(self) -> int:
        return self.seating_window.percentage_slots if self.seating_window else 0

    @property
    def max_waitlist_sessions(self) -> int:
        return max((window.max_waitlist_sessions for window in self.windows), default=0)

    @property
    def requires_slot_allowance(self) -> bool:
        return bool(
            self.seating_window and self.seating_window.restrict_to_configured_users
        )

    def effective_participants_limit(self, *, participants_limit: int) -> int:
        if not self.windows:
            return 0
        return math.ceil(participants_limit * self.percentage_slots / 100)

    def is_full(self, *, participants_limit: int, enrolled_count: int) -> bool:
        if not self.windows:
            return False
        return enrolled_count >= self.effective_participants_limit(
            participants_limit=participants_limit
        )

    def available_slots(self, *, participants_limit: int, enrolled_count: int) -> int:
        limit = self.effective_participants_limit(participants_limit=participants_limit)
        return max(0, limit - enrolled_count)


def viewer_access(
    *,
    windows: Iterable[DatedEnrollmentWindow],
    configured_window_ids: frozenset[int],
    now: datetime,
) -> EnrollmentAccessDTO:
    """Name the windows this viewer may use now, and when the next one starts.

    Returns:
        The viewer's own open windows, and the start of their next one.
    """
    # `admits` is the one place that decides who a window is for; this adds
    # the only thing it has no opinion on, which of them the clock has
    # reached. A pass is held per window: early access to one says nothing
    # about another, so the answer is asked window by window.
    usable = [
        window
        for window in windows
        if admits(window, is_configured_user=window.pk in configured_window_ids)
    ]
    return EnrollmentAccessDTO(
        open_window_ids=frozenset(
            window.pk for window in usable if window.start_time <= now < window.end_time
        ),
        opens_at=min(
            (window.start_time for window in usable if window.start_time > now),
            default=None,
        ),
    )
