from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.links.db.django.models import (
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


def _chat_user(user_id: int) -> User | None:
    return User.objects.filter(
        pk=user_id, is_active=True, user_type=UserType.ACTIVE
    ).first()


def _retained_events(user_id: int, window: ParleyTimeWindow) -> QuerySet[Event]:
    return Event.objects.filter(
        sphere__parley_enabled=True, end_time__gt=window.retained_after
    ).exclude(pk__in=EventBan.objects.filter(user_id=user_id).values("event_id"))


def _sessions(
    *, user_id: int, moderated: frozenset[int], window: ParleyTimeWindow
) -> QuerySet[Session]:
    own = Q(
        session_participations__user_id=user_id,
        session_participations__status=SessionParticipationStatus.CONFIRMED,
    ) | Q(facilitators__user_id=user_id)
    return Session.objects.filter(
        Q(event__sphere_id__in=moderated) | own,
        event__in=_retained_events(user_id, window),
    ).distinct()


def _events(
    *, user_id: int, moderated: frozenset[int], window: ParleyTimeWindow
) -> QuerySet[Event]:
    taking_part = Session.objects.filter(
        Q(session_participations__user_id=user_id)
        | Q(facilitators__user_id=user_id, status=SessionStatus.ACCEPTED)
    ).values("event_id")
    # NOTE: `specs.parley.event_chat_on` in SQL; keep the two the same.
    chat_on = Q(parley_enabled=True) | Q(
        parley_enabled__isnull=True, sphere__parley_events_enabled=True
    )
    return _retained_events(user_id, window).filter(
        chat_on, Q(sphere_id__in=moderated) | Q(pk__in=taking_part)
    )


def _organizers_rooms(moderated: frozenset[int]) -> QuerySet[Sphere]:
    return Sphere.objects.filter(pk__in=moderated, parley_organizers_enabled=True)


class ParleyRepository(ParleyRepositoryProtocol):
    @staticmethod
    def read_access(
        *, user_id: int, window: ParleyTimeWindow, moderated: frozenset[int]
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
            ParleyRoomDTO(
                kind=ParleyRoomKind.EVENT,
                sphere_id=event.sphere_id,
                pk=event.pk,
                title=event.name,
                can_write=event.end_time > window.writable_after,
                can_moderate=event.sphere_id in moderated,
                ends_at=int(event.end_time.timestamp()),
            )
            for event in _events(
                user_id=user_id, moderated=moderated, window=window
            ).order_by("start_time", "name", "pk")
        )
        rooms.extend(
            ParleyRoomDTO(
                kind=ParleyRoomKind.SESSION,
                sphere_id=session.event.sphere_id,
                pk=session.pk,
                event_pk=session.event_id,
                title=session.title,
                can_write=(
                    session.status == SessionStatus.ACCEPTED
                    and session.event.end_time > window.writable_after
                ),
                can_moderate=session.event.sphere_id in moderated,
                ends_at=int(session.event.end_time.timestamp()),
            )
            for session in (
                _sessions(user_id=user_id, moderated=moderated, window=window)
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
    def has_rooms(
        *, user_id: int, window: ParleyTimeWindow, moderated: frozenset[int]
    ) -> bool:
        if _chat_user(user_id) is None:
            return False
        return (
            _organizers_rooms(moderated).exists()
            or _events(user_id=user_id, moderated=moderated, window=window).exists()
            or _sessions(user_id=user_id, moderated=moderated, window=window).exists()
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
