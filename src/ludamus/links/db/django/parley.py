from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict

from django.db.models import BooleanField, ExpressionWrapper, Q

from ludamus.links.db.django.models import (
    Encounter,
    Event,
    EventBan,
    ParleyReport,
    Session,
    Sphere,
    SphereMembership,
    User,
)
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.parley import (
    ParleyAccessDTO,
    ParleyModeratedEventDTO,
    ParleyReportedRef,
    ParleyReportRecord,
    ParleyRepositoryProtocol,
    ParleyRoomDTO,
    ParleyRoomKind,
    ParleyTeamSeat,
    ParleyTimeWindow,
)
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.sphere import SphereRole
from ludamus.pacts.user import UserType

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet
    from django_stubs_ext import WithAnnotations

    class _Own(TypedDict):
        own: bool


def _chat_user(user_id: int) -> User | None:
    return User.objects.filter(
        pk=user_id, is_active=True, user_type=UserType.ACTIVE
    ).first()


def _retained_events(user_id: int, window: ParleyTimeWindow) -> QuerySet[Event]:
    return Event.objects.filter(
        sphere__parley_enabled=True, end_time__gt=window.retained_after
    ).exclude(pk__in=EventBan.objects.filter(user_id=user_id).values("event_id"))


def _own_sessions(user_id: int) -> Q:
    return Q(
        pk__in=Session.objects.filter(
            Q(
                session_participations__user_id=user_id,
                session_participations__status=SessionParticipationStatus.CONFIRMED,
            )
            | Q(facilitators__user_id=user_id)
        ).values("pk")
    )


def _own_events(user_id: int) -> Q:
    return Q(
        pk__in=Session.objects.filter(
            Q(session_participations__user_id=user_id)
            | Q(facilitators__user_id=user_id, status=SessionStatus.ACCEPTED)
        ).values("event_id")
    )


# `watched` are the spheres whose every room is listed, not only one's own.
def _sessions(
    *, user_id: int, watched: frozenset[int], window: ParleyTimeWindow
) -> QuerySet[WithAnnotations[Session, _Own]]:
    own = _own_sessions(user_id)
    return Session.objects.filter(
        Q(event__sphere_id__in=watched) | own,
        event__in=_retained_events(user_id, window),
    ).annotate(own=ExpressionWrapper(own, output_field=BooleanField()))


def _events(
    *, user_id: int, watched: frozenset[int], window: ParleyTimeWindow
) -> QuerySet[WithAnnotations[Event, _Own]]:
    own = _own_events(user_id)
    # NOTE: `specs.parley.event_chat_on` in SQL; keep the two the same.
    chat_on = Q(parley_enabled=True) | Q(
        parley_enabled__isnull=True, sphere__parley_events_enabled=True
    )
    return (
        _retained_events(user_id, window)
        .filter(chat_on, Q(sphere_id__in=watched) | own)
        .annotate(own=ExpressionWrapper(own, output_field=BooleanField()))
    )


def _organizers_rooms(moderated: frozenset[int]) -> QuerySet[Sphere]:
    return Sphere.objects.filter(pk__in=moderated, parley_organizers_enabled=True)


def _event_room(
    event: WithAnnotations[Event, _Own],
    *,
    window: ParleyTimeWindow,
    moderated: frozenset[int],
) -> ParleyRoomDTO:
    return ParleyRoomDTO(
        kind=ParleyRoomKind.EVENT,
        sphere_id=event.sphere_id,
        pk=event.pk,
        title=event.name,
        can_write=event.end_time > window.writable_after,
        can_moderate=event.sphere_id in moderated,
        moderating=not event.own,
        starts_at=int(event.start_time.timestamp()),
        ends_at=int(event.end_time.timestamp()),
    )


def _session_room(
    session: WithAnnotations[Session, _Own],
    *,
    window: ParleyTimeWindow,
    moderated: frozenset[int],
) -> ParleyRoomDTO:
    event = session.event
    return ParleyRoomDTO(
        kind=ParleyRoomKind.SESSION,
        sphere_id=event.sphere_id,
        pk=session.pk,
        event_pk=session.event_id,
        title=session.title,
        can_write=(
            session.status == SessionStatus.ACCEPTED
            and event.end_time > window.writable_after
        ),
        can_moderate=event.sphere_id in moderated,
        moderating=not session.own,
        starts_at=int(event.start_time.timestamp()),
        ends_at=int(event.end_time.timestamp()),
    )


class ParleyRepository(ParleyRepositoryProtocol):
    @staticmethod
    def read_access(
        *,
        user_id: int,
        window: ParleyTimeWindow,
        moderated: frozenset[int],
        watched: frozenset[int],
    ) -> ParleyAccessDTO | None:
        if (user := _chat_user(user_id)) is None:
            return None
        rooms = [
            ParleyRoomDTO(
                kind=ParleyRoomKind.ORGANIZERS,
                sphere_id=sphere.pk,
                title=sphere.name,
                can_write=True,
                can_moderate=True,
            )
            for sphere in _organizers_rooms(moderated).order_by("name", "pk")
        ]
        rooms.extend(
            _event_room(event, window=window, moderated=moderated)
            for event in _events(
                user_id=user_id, watched=watched, window=window
            ).order_by("start_time", "name", "pk")
        )
        rooms.extend(
            _session_room(session, window=window, moderated=moderated)
            for session in (
                _sessions(user_id=user_id, watched=watched, window=window)
                .select_related("event")
                .order_by("event__start_time", "title", "pk")
            )
        )
        return ParleyAccessDTO(
            user_id=user.pk,
            user_name=user.get_full_name(),
            user_avatar_url=user.avatar_url,
            rooms=rooms,
        )

    @staticmethod
    def list_moderated(
        *, user_id: int, sphere_id: int, window: ParleyTimeWindow
    ) -> list[ParleyModeratedEventDTO]:
        watched = frozenset({sphere_id})
        events: dict[int, Event] = {}
        rooms: defaultdict[int, list[ParleyRoomDTO]] = defaultdict(list)
        # Each event's own chat goes before its programme points'.
        for event in _events(user_id=user_id, watched=watched, window=window).filter(
            own=False
        ):
            events[event.pk] = event
            rooms[event.pk].append(_event_room(event, window=window, moderated=watched))
        for session in (
            _sessions(user_id=user_id, watched=watched, window=window)
            .filter(own=False)
            .select_related("event")
            .order_by("title", "pk")
        ):
            events[session.event_id] = session.event
            rooms[session.event_id].append(
                _session_room(session, window=window, moderated=watched)
            )
        return [
            ParleyModeratedEventDTO(title=event.name, slug=event.slug, rooms=rooms[pk])
            for pk, event in sorted(
                events.items(), key=lambda item: (item[1].start_time, item[0])
            )
        ]

    @staticmethod
    def has_rooms(
        *,
        user_id: int,
        window: ParleyTimeWindow,
        moderated: frozenset[int],
        watched: frozenset[int],
    ) -> bool:
        if _chat_user(user_id) is None:
            return False
        return (
            _organizers_rooms(moderated).exists()
            or _events(user_id=user_id, watched=watched, window=window).exists()
            or _sessions(user_id=user_id, watched=watched, window=window).exists()
        )

    @staticmethod
    def list_team_seats(user_id: int) -> list[ParleyTeamSeat]:
        return [
            ParleyTeamSeat(sphere_id=sphere_id, role=SphereRole(role))
            for sphere_id, role in (
                SphereMembership.objects.filter(
                    user_id=user_id, sphere__parley_enabled=True
                )
                .order_by("sphere_id")
                .values_list("sphere_id", "role")
            )
        ]

    @staticmethod
    def save_report(report: ParleyReportRecord) -> None:
        message = report.message
        copy = (
            {}
            if message is None
            else {
                "author_name": message.author_name,
                "body": message.body,
                "written_at": message.created_at,
                "deleted_at": message.deleted_at,
                # NOTE: the Worker takes authors from passes, whose subjects
                # are Django user ids.
                "reported_user": User.objects.filter(pk=message.author_id).first(),
            }
        )
        # Reporting the same message again keeps the first report.
        ParleyReport.objects.get_or_create(
            reporter_id=report.reporter_id,
            room_id=report.room_id,
            message_id=report.message_id,
            defaults={
                "reason": report.reason,
                "sphere_id": report.sphere_id,
                "conversation_id": report.conversation_id,
                **copy,
            },
        )

    @staticmethod
    def list_reported(report_ids: list[int]) -> list[ParleyReportedRef]:
        return [
            ParleyReportedRef(room_id=room_id, message_id=message_id)
            for room_id, message_id in (
                ParleyReport.objects.filter(pk__in=report_ids)
                .values_list("room_id", "message_id")
                .order_by("room_id", "message_id")
                .distinct()
            )
        ]

    @staticmethod
    def resolve_reports(*, room_id: str, message_id: int, now: datetime) -> None:
        ParleyReport.objects.filter(
            room_id=room_id, message_id=message_id, resolved_at=None
        ).update(resolved_at=now)

    @staticmethod
    def forget_copies_written_before(cutoff: datetime) -> int:
        return (
            ParleyReport.objects.filter(written_at__lte=cutoff)
            .exclude(body="", author_name="")
            .update(body="", author_name="")
        )

    @staticmethod
    def read_event_sphere_id(event_id: int) -> int | None:
        return (
            Event.objects.filter(pk=event_id, sphere__parley_enabled=True)
            .values_list("sphere_id", flat=True)
            .first()
        )

    @staticmethod
    def list_chat_sphere_ids() -> list[int]:
        return list(
            Sphere.objects.filter(parley_enabled=True)
            .order_by("pk")
            .values_list("pk", flat=True)
        )

    @staticmethod
    def list_encounters_with_people(sphere_id: int) -> list[int]:
        return list(
            Encounter.objects.filter(sphere_id=sphere_id)
            .filter(Q(rsvps__isnull=False) | Q(parley_chat__isnull=False))
            .distinct()
            .order_by("pk")
            .values_list("pk", flat=True)
        )
