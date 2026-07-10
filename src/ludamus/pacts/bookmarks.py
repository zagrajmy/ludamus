from typing import Protocol


class BookmarkRepositoryProtocol(Protocol):
    @staticmethod
    def toggle(*, user_id: int, session_id: int, sphere_id: int) -> bool | None: ...
    @staticmethod
    def bookmarked_session_ids(*, user_id: int, event_id: int) -> set[int]: ...


class BookmarkServiceProtocol(Protocol):
    def toggle(
        self, *, user_id: int, session_id: int, sphere_id: int
    ) -> bool | None: ...
    def bookmarked_session_ids(self, *, user_id: int, event_id: int) -> set[int]: ...
