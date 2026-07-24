from typing import Protocol

from pydantic import BaseModel


class BookmarkToggleDTO(BaseModel):
    bookmarked: bool
    count: int


class BookmarkRepositoryProtocol(Protocol):
    @staticmethod
    def toggle(
        *, user_id: int, session_id: int, sphere_id: int
    ) -> BookmarkToggleDTO | None: ...
    @staticmethod
    def bookmarked_session_ids(*, user_id: int, event_id: int) -> set[int]: ...
    @staticmethod
    def bookmark_counts(*, event_id: int) -> dict[int, int]: ...


class BookmarkServiceProtocol(Protocol):
    def toggle(
        self, *, user_id: int, session_id: int, sphere_id: int
    ) -> BookmarkToggleDTO | None: ...
    def bookmarked_session_ids(self, *, user_id: int, event_id: int) -> set[int]: ...
    def bookmark_counts(self, *, event_id: int) -> dict[int, int]: ...
