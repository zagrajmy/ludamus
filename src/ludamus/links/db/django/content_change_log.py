from __future__ import annotations

from ludamus.adapters.db.django.models import ContentChangeLog
from ludamus.links.db.django.change_log_base import (
    base_log_fields,
    latest_log_pk,
    latest_log_pks_by_session,
)
from ludamus.pacts import (
    ContentChangeLogData,
    ContentChangeLogDTO,
    ContentChangeLogRepositoryProtocol,
    NotFoundError,
)

_SELECT_RELATED = ("session", "user")


def _to_dto(log: ContentChangeLog) -> ContentChangeLogDTO:
    return ContentChangeLogDTO.model_validate(
        {
            **base_log_fields(log),
            "changes": log.changes,
            "creation_time": log.creation_time,
        }
    )


class ContentChangeLogRepository(ContentChangeLogRepositoryProtocol):
    @staticmethod
    def create(data: ContentChangeLogData) -> None:
        ContentChangeLog.objects.create(**data)

    @staticmethod
    def read(pk: int) -> ContentChangeLogDTO:
        try:
            log = ContentChangeLog.objects.select_related(*_SELECT_RELATED).get(pk=pk)
        except ContentChangeLog.DoesNotExist as err:
            msg = f"ContentChangeLog {pk} not found"
            raise NotFoundError(msg) from err
        return _to_dto(log)

    @staticmethod
    def list_by_event(event_pk: int) -> list[ContentChangeLogDTO]:
        qs = ContentChangeLog.objects.filter(event_id=event_pk).select_related(
            *_SELECT_RELATED
        )
        return [_to_dto(log) for log in qs]

    @staticmethod
    def latest_pks_by_session(event_pk: int) -> dict[int, int]:
        return latest_log_pks_by_session(
            ContentChangeLog.objects.filter(event_id=event_pk)
        )

    @staticmethod
    def latest_pk_for_session(event_pk: int, session_id: int) -> int | None:
        return latest_log_pk(
            ContentChangeLog.objects.filter(event_id=event_pk, session_id=session_id)
        )
