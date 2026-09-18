"""Session cards for the public event page.

The schedule is read as plain rows, one query per relation, grouped by
session in Python: a big event has a thousand sessions, and the page reads an
attribute or two of each relation, so model instances with prefetch caches (a
queryset and a cache per session per relation) cost more than the page
itself. Proposals, an organizer's short review queue, still come from
instances and share the card shape.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, TypeAdapter

from ludamus.links.db.django.models import (
    Session,
    SessionFieldValue,
    SessionParticipation,
    Space,
    Track,
    User,
    effective_participants_limit,
)
from ludamus.links.db.django.repositories.chronology import (
    location_data,
    public_scheduled_sessions,
    session_card_stats,
)
from ludamus.links.db.django.repositories.sessions import (
    annotate_session_participation_counts,
    field_value_dto,
)
from ludamus.links.db.django.users import user_dto
from ludamus.pacts import (
    NO_LOCATION,
    AgendaItemDTO,
    SessionDTO,
    SessionFieldValueDTO,
    SessionParticipationStatus,
    SessionStatus,
    TimeSlotDTO,
)
from ludamus.pacts.chronology import SessionCardDTO, SessionCardStatsDTO, SessionSeatDTO
from ludamus.pacts.legacy import LocationData

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from django.db.models import QuerySet

    from ludamus.links.db.django.models import EnrollmentConfig, Event
    from ludamus.pacts.crowd import UserDTO


class _SessionRow(BaseModel):
    # One row of the schedule read: the session's own columns, its agenda
    # item and category joined in, and the participation counts annotated.
    # Validated on the way in, so the values() dicts get a type at the one
    # place they enter.
    pk: int
    category_id: int | None
    contact_email: str
    creation_time: datetime
    description: str
    duration: str
    min_age: int
    modification_time: datetime
    participants_limit: int
    presenter_id: int | None
    facilitator_name: str
    slug: str
    status: SessionStatus
    title: str
    cover_image: str
    cover_image_original_name: str
    category__name: str | None
    agenda_item__pk: int
    agenda_item__start_time: datetime
    agenda_item__end_time: datetime
    agenda_item__session_confirmed: bool
    agenda_item__space_id: int
    enrolled_count_cached: int
    waiting_count_cached: int


class _FieldValueRow(BaseModel):
    session_id: int
    value: str | list[str] | bool
    field_id: int
    field__allow_custom: bool
    field__icon: str
    field__name: str
    field__order: int
    field__question: str
    field__slug: str
    field__field_type: str
    field__is_public: bool


class _SpaceRow(BaseModel):
    pk: int
    parent_id: int | None
    name: str
    order: int
    programme_order: int


_SESSION_ROWS = TypeAdapter(list[_SessionRow])
_FIELD_VALUE_ROWS = TypeAdapter(list[_FieldValueRow])
_SPACE_ROWS = TypeAdapter(list[_SpaceRow])
_COVER_STORAGE = Session.cover_image.field.storage


def _session_dto(row: _SessionRow) -> SessionDTO:
    return SessionDTO(
        category_id=row.category_id,
        contact_email=row.contact_email,
        creation_time=row.creation_time,
        description=row.description,
        duration=row.duration,
        min_age=row.min_age,
        modification_time=row.modification_time,
        participants_limit=row.participants_limit,
        pk=row.pk,
        presenter_id=row.presenter_id,
        facilitator_name=row.facilitator_name,
        slug=row.slug,
        status=row.status,
        title=row.title,
        cover_image_url=_COVER_STORAGE.url(row.cover_image) if row.cover_image else "",
        cover_image_original_name=row.cover_image_original_name,
    )


def _agenda_item_dto(row: _SessionRow) -> AgendaItemDTO:
    return AgendaItemDTO(
        pk=row.agenda_item__pk,
        start_time=row.agenda_item__start_time,
        end_time=row.agenda_item__end_time,
        session_confirmed=row.agenda_item__session_confirmed,
        space_id=row.agenda_item__space_id,
        session_id=row.pk,
    )


def _field_value(row: _FieldValueRow) -> SessionFieldValueDTO:
    return SessionFieldValueDTO(
        allow_custom=row.field__allow_custom,
        field_icon=row.field__icon,
        field_id=row.field_id,
        field_name=row.field__name,
        field_order=row.field__order,
        field_question=row.field__question,
        field_slug=row.field__slug,
        field_type=row.field__field_type,
        is_public=row.field__is_public,
        value=row.value,
    )


def _stats(
    row: _SessionRow, *, active_configs: Collection[EnrollmentConfig]
) -> SessionCardStatsDTO:
    limit = row.participants_limit
    eligible = [
        config
        for config in active_configs
        if config.can_seat(
            participants_limit=limit, start_time=row.agenda_item__start_time
        )
    ]
    effective = effective_participants_limit(
        participants_limit=limit, eligible_configs=eligible
    )
    enrolled = row.enrolled_count_cached
    return SessionCardStatsDTO(
        enrolled_count=enrolled,
        waiting_count=row.waiting_count_cached,
        is_full=limit != 0 and enrolled >= effective,
        enrollment_window_ids=frozenset(config.pk for config in eligible),
        effective_participants_limit=effective,
    )


def _location_index(event_id: int) -> dict[int, LocationData]:
    # Every space of the event in one read, then the root-to-leaf chain walked
    # in memory: the same answer location_data gives from a loaded instance,
    # without SPACE_MAX_DEPTH joins on every session row.
    rows = _SPACE_ROWS.validate_python(
        list(
            Space.objects.filter(event_id=event_id)
            .order_by()
            .values("pk", "parent_id", "name", "order", "programme_order")
        )
    )
    spaces = {row.pk: row for row in rows}
    index: dict[int, LocationData] = {}
    for pk, space in spaces.items():
        chain = [space]
        while (parent_id := chain[-1].parent_id) and parent_id in spaces:
            chain.append(spaces[parent_id])
        chain.reverse()
        parent = spaces.get(space.parent_id) if space.parent_id else None
        index[pk] = LocationData(
            space_id=pk,
            parent_id=space.parent_id or 0,
            space_name=space.name,
            parent_name=parent.name if parent else "",
            path=" > ".join(node.name for node in chain),
            sort_path=tuple((node.order, node.name, node.pk) for node in chain),
            programme_order=space.programme_order,
        )
    return index


def _location(space_id: int, *, index: dict[int, LocationData]) -> LocationData:
    if (found := index.get(space_id)) is not None:
        return found
    # A room filed under another event: the schema allows it, nothing writes
    # it. Answered per room, so the anomaly costs its own chain walk and no
    # more.
    return location_data(Space.objects.get(pk=space_id))


def _presenters(user_ids: Collection[int]) -> dict[int, UserDTO]:
    if not user_ids:
        return {}
    return {user.pk: user_dto(user) for user in User.objects.filter(pk__in=user_ids)}


def _field_values_by_session(
    session_ids: Collection[int],
) -> dict[int, list[SessionFieldValueDTO]]:
    grouped: dict[int, list[SessionFieldValueDTO]] = defaultdict(list)
    rows = _FIELD_VALUE_ROWS.validate_python(
        list(
            SessionFieldValue.objects.filter(
                session_id__in=session_ids, field__is_public=True
            )
            .order_by("field__order", "field__name", "pk")
            .values(
                "session_id",
                "value",
                "field_id",
                "field__allow_custom",
                "field__icon",
                "field__name",
                "field__order",
                "field__question",
                "field__slug",
                "field__field_type",
                "field__is_public",
            )
        )
    )
    for row in rows:
        grouped[row.session_id].append(_field_value(row))
    return grouped


def _track_names_by_session(session_ids: Collection[int]) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    rows = (
        Track.objects.filter(sessions__pk__in=session_ids)
        .order_by("name")
        .values_list("sessions__pk", "name")
    )
    for session_id, name in rows:
        grouped[session_id].append(name)
    return grouped


def _seats_by_session(session_ids: Collection[int]) -> dict[int, list[SessionSeatDTO]]:
    grouped: dict[int, list[SessionSeatDTO]] = defaultdict(list)
    rows = (
        SessionParticipation.objects.filter(session_id__in=session_ids)
        .select_related("user")
        .order_by("pk")
    )
    for participation in rows:
        grouped[participation.session_id].append(
            SessionSeatDTO(
                user=user_dto(participation.user),
                status=SessionParticipationStatus(participation.status),
                creation_time=participation.creation_time,
            )
        )
    return grouped


# The schedule read's columns, one per _SessionRow field. Named apart from
# the call so the annotated counts pass through values() like any column.
_SCHEDULE_COLUMNS = tuple(_SessionRow.model_fields)


def _scheduled_rows(event_id: int) -> list[_SessionRow]:
    return _SESSION_ROWS.validate_python(
        list(
            annotate_session_participation_counts(public_scheduled_sessions(event_id))
            .order_by("agenda_item__start_time")
            .values(*_SCHEDULE_COLUMNS)
        )
    )


def scheduled_session_cards(event: Event, *, roster_up_to: int) -> list[SessionCardDTO]:
    """Read every public scheduled session of the event, earliest first.

    Returns:
        The cards, with seat holders only when the schedule holds fewer than
        ``roster_up_to`` sessions: the card grid draws them, the compact
        schedule a bigger event switches to does not.
    """
    if not (rows := _scheduled_rows(event.pk)):
        return []
    session_ids = [row.pk for row in rows]
    locations = _location_index(event.pk)
    presenters = _presenters({row.presenter_id for row in rows if row.presenter_id})
    field_values = _field_values_by_session(session_ids)
    track_names = _track_names_by_session(session_ids)
    seats = _seats_by_session(session_ids) if len(rows) < roster_up_to else {}
    active_configs = event.get_active_enrollment_configs()
    return [
        SessionCardDTO(
            session=_session_dto(row),
            agenda_item=_agenda_item_dto(row),
            presenter=(presenters.get(row.presenter_id) if row.presenter_id else None),
            location=_location(row.agenda_item__space_id, index=locations),
            field_values=field_values.get(row.pk, []),
            track_names=track_names.get(row.pk, []),
            category_name=row.category__name or "",
            participations=seats.get(row.pk, []),
            preferred_time_slots=[],
            **_stats(row, active_configs=active_configs).model_dump(),
        )
        for row in rows
    ]


def _card_from_session(session: Session) -> SessionCardDTO:
    agenda_item = getattr(session, "agenda_item", None)
    return SessionCardDTO(
        session=SessionDTO.model_validate(session),
        agenda_item=(
            AgendaItemDTO.model_validate(agenda_item)
            if agenda_item is not None
            else None
        ),
        presenter=(
            user_dto(session.presenter) if session.presenter is not None else None
        ),
        location=(
            location_data(agenda_item.space) if agenda_item is not None else NO_LOCATION
        ),
        field_values=sorted(
            (
                field_value_dto(value)
                for value in session.field_values.all()
                if value.field.is_public
            ),
            key=lambda value: (value.field_order, value.field_name),
        ),
        track_names=[track.name for track in session.tracks.all()],
        category_name=session.category.name if session.category else "",
        participations=[
            SessionSeatDTO(
                user=user_dto(participation.user),
                status=SessionParticipationStatus(participation.status),
                creation_time=participation.creation_time,
            )
            for participation in session.session_participations.all()
        ],
        preferred_time_slots=(
            []
            if agenda_item is not None
            else [TimeSlotDTO.model_validate(slot) for slot in session.time_slots.all()]
        ),
        **session_card_stats(session).model_dump(),
    )


def proposal_cards(
    proposals: QuerySet[Session] | Iterable[Session],
) -> list[SessionCardDTO]:
    """Shape a review queue's proposals as cards, in the queue's order."""
    # Instances, not rows: the queue is short and comes with its relations
    # prefetched (review_inbox_proposals), slots included.
    return [_card_from_session(session) for session in proposals]
