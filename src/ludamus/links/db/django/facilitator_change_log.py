from __future__ import annotations

from ludamus.links.db.django.models import FacilitatorChangeLog
from ludamus.pacts import (
    FacilitatorChangeLogData,
    FacilitatorChangeLogDTO,
    FacilitatorChangeLogRepositoryProtocol,
)

_SELECT_RELATED = ("facilitator", "user")


def _to_dto(log: FacilitatorChangeLog) -> FacilitatorChangeLogDTO:
    return FacilitatorChangeLogDTO.model_validate(
        {
            "pk": log.pk,
            "event_id": log.event_id,
            "facilitator_id": log.facilitator_id,
            "facilitator_name": log.facilitator.display_name,
            "user_id": log.user_id,
            "user_name": log.user.name if log.user else "",
            "changes": log.changes,
            "creation_time": log.creation_time,
        }
    )


class FacilitatorChangeLogRepository(FacilitatorChangeLogRepositoryProtocol):
    @staticmethod
    def create(data: FacilitatorChangeLogData) -> None:
        FacilitatorChangeLog.objects.create(**data)

    @staticmethod
    def list_by_event(event_pk: int) -> list[FacilitatorChangeLogDTO]:
        qs = FacilitatorChangeLog.objects.filter(event_id=event_pk).select_related(
            *_SELECT_RELATED
        )
        return [_to_dto(log) for log in qs]
