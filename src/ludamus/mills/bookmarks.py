from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.bookmarks import BookmarkServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.bookmarks import BookmarkRepositoryProtocol, BookmarkToggleDTO
    from ludamus.pacts.ids import EventId, SessionId, SphereId, UserId
    from ludamus.pacts.services import TransactionProtocol


class BookmarkService(BookmarkServiceProtocol):
    def __init__(
        self, transaction: TransactionProtocol, repo: BookmarkRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._repo = repo

    def toggle(
        self, *, user_id: UserId, session_id: SessionId, sphere_id: SphereId
    ) -> BookmarkToggleDTO | None:
        with self._transaction.atomic():
            return self._repo.toggle(
                user_id=user_id, session_id=session_id, sphere_id=sphere_id
            )

    def bookmarked_session_ids(
        self, *, user_id: UserId, event_id: EventId
    ) -> set[SessionId]:
        return self._repo.bookmarked_session_ids(user_id=user_id, event_id=event_id)

    def bookmark_counts(self, *, event_id: EventId) -> dict[SessionId, int]:
        return self._repo.bookmark_counts(event_id=event_id)
