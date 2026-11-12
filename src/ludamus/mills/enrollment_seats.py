"""The one way into a seat decision on the enroll paths.

A member enrolling the people they act for and a visitor enrolling with a
code both take their seats here: the Session row first, then the User rows of
everyone whose seat the request decides (`lock_seat_holders`), and only then
the counts the decision reads. docs/agents/architecture.md argues the order
deadlock-free; `formal/enrollment` proves that, taken by every writer, it
neither overbooks a session nor double-books a person.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.mills.enrollment_windows import EnrollmentPolicy
    from ludamus.pacts.enrollment import SeatRepositoryProtocol, SessionSeatingDTO


class SeatDesk:
    def __init__(self, seats: SeatRepositoryProtocol) -> None:
        self._seats = seats

    def lock_session(self, session_id: int) -> SessionSeatingDTO:
        """Take the Session row lock; the first lock of every seat decision.

        Returns:
            The session's seats as they stand under the lock.
        """
        return self._seats.lock_seating(session_id)

    def lock_people(
        self, *, session_id: int, user_ids: Iterable[int], refills: bool
    ) -> None:
        # The second lock, before anything the decision reads about these
        # people. A request that frees a seat refills it in its own
        # transaction, so it holds the session's waiters as well.
        self._seats.lock_seat_holders(
            user_ids=user_ids, waiters_of=session_id if refills else None
        )

    @staticmethod
    def room(
        policy: EnrollmentPolicy, seating: SessionSeatingDTO, *, freed: int = 0
    ) -> int:
        """Count the seats this actor may still take, crediting `freed` back.

        Returns:
            Seats left under the actor's windows; 0 when none admits them.
        """
        return policy.available_slots(
            participants_limit=seating.participants_limit,
            enrolled_count=seating.enrolled_count - freed,
        )
