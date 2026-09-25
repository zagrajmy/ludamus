from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from ludamus.pacts.ids import EventId, SessionId, SphereId, UserId


class BookmarkStateDTO(BaseModel):
    bookmarked: bool
    count: int


class BookmarkRepositoryProtocol(Protocol):
    @staticmethod
    def toggle(
        *, user_id: UserId, session_id: SessionId, sphere_id: SphereId
    ) -> BookmarkStateDTO | None: ...
    @staticmethod
    def bookmarked_session_ids(
        *, user_id: UserId, event_id: EventId
    ) -> set[SessionId]: ...
    @staticmethod
    def bookmark_counts(*, event_id: EventId) -> dict[SessionId, int]: ...
    @staticmethod
    def session_state(
        *, user_id: UserId | None, session_id: SessionId
    ) -> BookmarkStateDTO: ...


class BookmarkServiceProtocol(Protocol):
    def toggle(
        self, *, user_id: UserId, session_id: SessionId, sphere_id: SphereId
    ) -> BookmarkStateDTO | None: ...
    def bookmarked_session_ids(
        self, *, user_id: UserId, event_id: EventId
    ) -> set[SessionId]: ...
    def bookmark_counts(self, *, event_id: EventId) -> dict[SessionId, int]: ...
    def session_state(
        self, *, user_id: UserId | None, session_id: SessionId
    ) -> BookmarkStateDTO: ...
