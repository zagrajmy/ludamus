from __future__ import annotations

from typing import Protocol


class _SessionLike(Protocol):
    @property
    def title(self) -> str: ...


class _UserLike(Protocol):
    @property
    def name(self) -> str: ...


class _LoggableChange(Protocol):
    @property
    def pk(self) -> int: ...
    @property
    def event_id(self) -> int: ...
    @property
    def session_id(self) -> int: ...
    @property
    def user_id(self) -> int | None: ...
    @property
    def session(self) -> _SessionLike: ...
    @property
    def user(self) -> _UserLike | None: ...


def base_log_fields(log: _LoggableChange) -> dict[str, object]:
    # Common DTO fields shared by every change-log row (schedule, content, …).
    return {
        "pk": log.pk,
        "event_id": log.event_id,
        "session_id": log.session_id,
        "session_title": log.session.title,
        "user_id": log.user_id,
        "user_name": log.user.name if log.user else "",
    }
