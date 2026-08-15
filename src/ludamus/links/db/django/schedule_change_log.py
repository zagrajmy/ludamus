from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

from ludamus.links.db.django.change_log_base import (
    base_log_fields,
    latest_log_pk,
    latest_log_pks_by_session,
)
from ludamus.links.db.django.models import ScheduleChangeLog
from ludamus.pacts import (
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    ScheduleChangeLogDTO,
    ScheduleChangeLogRepositoryProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

_SELECT_RELATED = ("session", "user", "old_space", "new_space", "acknowledged_by")


def _to_dto(log: ScheduleChangeLog) -> ScheduleChangeLogDTO:
    return ScheduleChangeLogDTO.model_validate(
        {
            **base_log_fields(log),
            "action": ScheduleChangeAction(log.action),
            "old_space_id": log.old_space_id,
            "old_space_name": log.old_space.name if log.old_space else None,
            "new_space_id": log.new_space_id,
            "new_space_name": log.new_space.name if log.new_space else None,
            "old_start_time": log.old_start_time,
            "old_end_time": log.old_end_time,
            "new_start_time": log.new_start_time,
            "new_end_time": log.new_end_time,
            "creation_time": log.creation_time,
            "acknowledgement_time": log.acknowledgement_time,
            "acknowledged_by_name": (
                log.acknowledged_by.name if log.acknowledged_by else ""
            ),
        }
    )


class ScheduleChangeLogRepository(ScheduleChangeLogRepositoryProtocol):
    @staticmethod
    def create(data: ScheduleChangeLogData) -> None:
        ScheduleChangeLog.objects.create(**data)

    @staticmethod
    def read(pk: int) -> ScheduleChangeLogDTO:
        try:
            log = ScheduleChangeLog.objects.select_related(*_SELECT_RELATED).get(pk=pk)
        except ScheduleChangeLog.DoesNotExist as err:
            msg = f"ScheduleChangeLog {pk} not found"
            raise NotFoundError(msg) from err
        return _to_dto(log)

    @staticmethod
    def list_by_event(
        event_pk: int, *, space_pk: int | None = None
    ) -> list[ScheduleChangeLogDTO]:
        qs = (
            ScheduleChangeLog.objects.filter(event_id=event_pk)
            .select_related(*_SELECT_RELATED)
            .order_by("-creation_time", "-pk")
        )
        if space_pk is not None:
            qs = qs.filter(Q(old_space_id=space_pk) | Q(new_space_id=space_pk))
        return [_to_dto(log) for log in qs]

    @staticmethod
    def list_since(event_pk: int, since: datetime) -> list[ScheduleChangeLogDTO]:
        qs = (
            ScheduleChangeLog.objects.filter(
                event_id=event_pk, creation_time__gte=since
            )
            .select_related(*_SELECT_RELATED)
            .order_by("-creation_time", "-pk")
        )
        return [_to_dto(log) for log in qs]

    @staticmethod
    def set_acknowledged(
        *, event_pk: int, log_pks: list[int], user_id: int, acknowledged: bool
    ) -> None:
        # Scoped by event: panel access proves which event the caller manages,
        # never which pks the request happens to name.
        ScheduleChangeLog.objects.filter(event_id=event_pk, pk__in=log_pks).update(
            acknowledged_by=user_id if acknowledged else None,
            acknowledgement_time=timezone.now() if acknowledged else None,
        )

    @staticmethod
    def list_by_session(session_id: int) -> list[ScheduleChangeLogDTO]:
        qs = (
            ScheduleChangeLog.objects.filter(session_id=session_id)
            .select_related(*_SELECT_RELATED)
            .order_by("-creation_time", "-pk")
        )
        return [_to_dto(log) for log in qs]

    @staticmethod
    def latest_pks_by_session(event_pk: int) -> dict[int, int]:
        return latest_log_pks_by_session(
            ScheduleChangeLog.objects.filter(event_id=event_pk)
        )

    @staticmethod
    def latest_pk_for_session(event_pk: int, session_id: int) -> int | None:
        return latest_log_pk(
            ScheduleChangeLog.objects.filter(event_id=event_pk, session_id=session_id)
        )
