from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.bookmarks import BookmarkServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.bookmarks import BookmarkRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


class BookmarkService(BookmarkServiceProtocol):
    def __init__(
        self, transaction: TransactionProtocol, repo: BookmarkRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._repo = repo

    def toggle(self, *, user_id: int, session_id: int, sphere_id: int) -> bool | None:
        with self._transaction.atomic():
            return self._repo.toggle(
                user_id=user_id, session_id=session_id, sphere_id=sphere_id
            )

    def bookmarked_session_ids(self, *, user_id: int, event_id: int) -> set[int]:
        return self._repo.bookmarked_session_ids(user_id=user_id, event_id=event_id)
