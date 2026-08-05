from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count, Q

from ludamus.links.db.django.models import AgendaItem, Track
from ludamus.pacts import (
    AgendaItemData,
    AgendaItemDTO,
    AgendaItemRepositoryProtocol,
    AgendaItemUpdateData,
    NotFoundError,
    SessionStatus,
)
from ludamus.pacts.legacy import ConfirmationCountsRow, ConfirmationTotalsRow

if TYPE_CHECKING:
    from datetime import datetime

_SELECT_RELATED = ("session", "session__category", "space")


# Confirmation counts for any model holding a `sessions` relation (Track,
# Facilitator). Distinct, because the joins they ride on multiply rows.
def scheduled_item_count() -> Count:
    return Count("sessions__agenda_item", distinct=True)


def confirmed_item_count() -> Count:
    return Count(
        "sessions__agenda_item",
        filter=Q(sessions__agenda_item__session_confirmed=True),
        distinct=True,
    )


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
    def count_confirmations_by_track(event_pk: int) -> list[ConfirmationCountsRow]:
        # One query for the whole table. Every Count is distinct because the
        # three m2m joins (sessions, their facilitators, their agenda items)
        # multiply rows against each other.
        # ponytail: single wide join; split into per-metric queries only if the
        # row product starts to hurt at event scale.
        rows = (
            Track.objects.filter(event_id=event_pk)
            .values("pk", "name")
            .annotate(
                # Only facilitators with a placed session, so the column agrees
                # with the cards the row links to.
                facilitator_count=Count(
                    "sessions__facilitators",
                    filter=Q(sessions__agenda_item__isnull=False),
                    distinct=True,
                ),
                scheduled_count=scheduled_item_count(),
                confirmed_count=confirmed_item_count(),
            )
            .order_by("name")
        )
        return [
            ConfirmationCountsRow(
                key=row["pk"],
                name=row["name"],
                facilitator_count=row["facilitator_count"],
                scheduled_count=row["scheduled_count"],
                confirmed_count=row["confirmed_count"],
            )
            for row in rows
        ]

    @staticmethod
    def count_event_totals(event_pk: int) -> ConfirmationTotalsRow:
        # Counted over the items themselves. Adding up the per-organizer rows
        # would count an item once per facilitator who runs it.
        row = AgendaItem.objects.filter(session__event_id=event_pk).aggregate(
            scheduled=Count("pk"),
            confirmed=Count("pk", filter=Q(session_confirmed=True)),
        )
        return ConfirmationTotalsRow(
            scheduled_count=row["scheduled"], confirmed_count=row["confirmed"]
        )

    @staticmethod
    def set_confirmed_for_facilitator(
        *,
        event_pk: int,
        facilitator_pk: int,
        confirmed: bool,
        contact_email: str | None = None,
        agenda_item_pk: int | None = None,
    ) -> int:
        """Set the confirmation flag over one facilitator's placed items.

        Scoping to agenda items is what keeps an unplaced or pending session
        unconfirmable: it has no row here to update. `contact_email` narrows to
        one address (including the empty one), `agenda_item_pk` to one item.

        Returns:
            How many agenda items the filter matched.
        """
        # One statement, whatever the scope — never a row-by-row save loop.
        queryset = AgendaItem.objects.filter(
            session__event_id=event_pk, session__facilitators__pk=facilitator_pk
        )
        if contact_email is not None:
            queryset = queryset.filter(session__contact_email=contact_email)
        if agenda_item_pk is not None:
            queryset = queryset.filter(pk=agenda_item_pk)
        return queryset.update(session_confirmed=confirmed)

    @staticmethod
    def count_without_facilitator(event_pk: int, track_pk: int | None = None) -> int:
        queryset = AgendaItem.objects.filter(
            session__event_id=event_pk, session__facilitators__isnull=True
        )
        if track_pk is not None:
            queryset = queryset.filter(session__tracks=track_pk)
        return queryset.count()

    @staticmethod
    def delete(pk: int) -> None:
        AgendaItem.objects.filter(pk=pk).delete()
