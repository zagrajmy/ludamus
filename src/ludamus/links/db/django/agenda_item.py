from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.adapters.db.django.models import AgendaItem
from ludamus.pacts import (
    AgendaItemData,
    AgendaItemDTO,
    AgendaItemRepositoryProtocol,
    AgendaItemUpdateData,
    NotFoundError,
    SessionStatus,
)

if TYPE_CHECKING:
    from datetime import datetime

_SELECT_RELATED = ("session", "session__category", "space")


def _to_dto(item: AgendaItem) -> AgendaItemDTO:
    duration_minutes = int((item.end_time - item.start_time).total_seconds() / 60)
    return AgendaItemDTO(
        end_time=item.end_time,
        pk=item.pk,
        session_confirmed=item.session_confirmed,
        start_time=item.start_time,
        space_id=item.space_id,
        space_name=item.space.name,
        session_id=item.session_id,
        session_title=item.session.title,
        session_description=item.session.description,
        presenter_name=item.session.display_name,
        session_duration_minutes=duration_minutes,
        session_status=SessionStatus(item.session.status),
        category_name=(
            item.session.category.name if item.session.category is not None else None
        ),
    )


class AgendaItemRepository(AgendaItemRepositoryProtocol):
    @staticmethod
    def create(agenda_item_data: AgendaItemData) -> None:
        AgendaItem.objects.create(**agenda_item_data)

    @staticmethod
    def read(pk: int) -> AgendaItemDTO:
        try:
            item = AgendaItem.objects.select_related(*_SELECT_RELATED).get(pk=pk)
        except AgendaItem.DoesNotExist as err:
            raise NotFoundError from err
        return _to_dto(item)

    @staticmethod
    def list_by_event(event_pk: int) -> list[AgendaItemDTO]:
        items = AgendaItem.objects.filter(session__event_id=event_pk).select_related(
            *_SELECT_RELATED
        )
        return [_to_dto(item) for item in items]

    @staticmethod
    def list_by_track(track_pk: int) -> list[AgendaItemDTO]:
        items = AgendaItem.objects.filter(session__tracks__pk=track_pk).select_related(
            *_SELECT_RELATED
        )
        return [_to_dto(item) for item in items]

    @staticmethod
    def read_by_session(session_pk: int) -> AgendaItemDTO | None:
        try:
            item = AgendaItem.objects.select_related(*_SELECT_RELATED).get(
                session_id=session_pk
            )
        except AgendaItem.DoesNotExist:
            return None
        return _to_dto(item)

    @staticmethod
    def list_overlapping_in_space(
        space_pk: int,
        start_time: datetime,
        end_time: datetime,
        exclude_session_pk: int | None = None,
    ) -> list[AgendaItemDTO]:
        qs = AgendaItem.objects.filter(
            space_id=space_pk, start_time__lt=end_time, end_time__gt=start_time
        ).select_related(*_SELECT_RELATED)
        if exclude_session_pk is not None:
            qs = qs.exclude(session_id=exclude_session_pk)
        return [_to_dto(item) for item in qs]

    @staticmethod
    def list_overlapping_by_facilitator(
        facilitator_pk: int,
        start_time: datetime,
        end_time: datetime,
        exclude_session_pk: int | None = None,
    ) -> list[AgendaItemDTO]:
        qs = AgendaItem.objects.filter(
            session__facilitators__pk=facilitator_pk,
            start_time__lt=end_time,
            end_time__gt=start_time,
        ).select_related(*_SELECT_RELATED)
        if exclude_session_pk is not None:
            qs = qs.exclude(session_id=exclude_session_pk)
        return [_to_dto(item) for item in qs]

    @staticmethod
    def update(pk: int, data: AgendaItemUpdateData) -> None:
        AgendaItem.objects.filter(pk=pk).update(**data)

    @staticmethod
    def confirm_all_by_event(event_pk: int) -> None:
        AgendaItem.objects.filter(session__event_id=event_pk).update(
            session_confirmed=True
        )

    @staticmethod
    def confirm_all_by_track(track_pk: int) -> None:
        AgendaItem.objects.filter(session__tracks__pk=track_pk).update(
            session_confirmed=True
        )

    @staticmethod
    def delete(pk: int) -> None:
        AgendaItem.objects.filter(pk=pk).delete()
