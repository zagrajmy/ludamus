from __future__ import annotations

from ludamus.adapters.db.django.models import ContentChangeLog
from ludamus.links.db.django.change_log_base import base_log_fields
from ludamus.pacts import (
    ContentChangeLogData,
    ContentChangeLogDTO,
    ContentChangeLogRepositoryProtocol,
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
    def list_by_event(event_pk: int) -> list[ContentChangeLogDTO]:
        qs = ContentChangeLog.objects.filter(event_id=event_pk).select_related(
            *_SELECT_RELATED
        )
        return [_to_dto(log) for log in qs]
