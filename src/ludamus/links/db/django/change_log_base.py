from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ludamus.adapters.db.django.models import ContentChangeLog, ScheduleChangeLog

    ChangeLogQuerySet = QuerySet[ContentChangeLog] | QuerySet[ScheduleChangeLog]


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


def latest_log_pks_by_session(qs: ChangeLogQuerySet) -> dict[int, int]:
    latest: dict[int, int] = {}
    for session_id, pk in qs.order_by(
        "session_id", "-creation_time", "-pk"
    ).values_list("session_id", "pk"):
        latest.setdefault(session_id, pk)
    return latest


def latest_log_pk(qs: ChangeLogQuerySet) -> int | None:
    return qs.order_by("-creation_time", "-pk").values_list("pk", flat=True).first()
