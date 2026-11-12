from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.links.db.django.models import (
    Event,
    EventBan,
    ParleyReport,
    Session,
    Sphere,
    User,
)
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.parley import (
    ParleyAccessDTO,
    ParleyReportRecord,
    ParleyRepositoryProtocol,
    ParleyRoomDTO,
    ParleyRoomKind,
    ParleyTimeWindow,
)
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.user import UserType

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet


def _chat_user(user_id: int) -> User | None:
    return User.objects.filter(
        pk=user_id, is_active=True, user_type=UserType.ACTIVE
    ).first()


def _managed_sphere_ids(user_id: int) -> set[int]:
    return set(
        Sphere.objects.filter(parley_enabled=True, managers=user_id).values_list(
            "pk", flat=True
        )
    )


def _retained_events(user_id: int, window: ParleyTimeWindow) -> QuerySet[Event]:
    return Event.objects.filter(
        sphere__parley_enabled=True, end_time__gt=window.retained_after
    ).exclude(pk__in=EventBan.objects.filter(user_id=user_id).values("event_id"))


def _sessions(
    *, user_id: int, managed: set[int], window: ParleyTimeWindow
) -> QuerySet[Session]:
    own = Q(
        session_participations__user_id=user_id,
        session_participations__status=SessionParticipationStatus.CONFIRMED,
    ) | Q(facilitators__user_id=user_id)
    return Session.objects.filter(
        Q(event__sphere_id__in=managed) | own,
        event__in=_retained_events(user_id, window),
    ).distinct()


def _events(
    *, user_id: int, managed: set[int], window: ParleyTimeWindow
) -> QuerySet[Event]:
    taking_part = Session.objects.filter(
        Q(session_participations__user_id=user_id) | Q(facilitators__user_id=user_id)
    ).values("event_id")
    return _retained_events(user_id, window).filter(
        Q(sphere_id__in=managed) | Q(pk__in=taking_part), parley_enabled=True
    )


class ParleyRepository(ParleyRepositoryProtocol):
    @staticmethod
    def read_access(
        *, user_id: int, window: ParleyTimeWindow
    ) -> ParleyAccessDTO | None:
        if (user := _chat_user(user_id)) is None:
            return None
        managed = _managed_sphere_ids(user_id)
        rooms = [
            ParleyRoomDTO(
                id=f"organizers:{sphere.pk}",
                kind=ParleyRoomKind.ORGANIZERS,
                title=sphere.name,
                can_write=True,
                can_moderate=True,
            )
            for sphere in Sphere.objects.filter(pk__in=managed).order_by("name", "pk")
        ]
        rooms.extend(
            ParleyRoomDTO(
                id=f"event:{event.sphere_id}:{event.pk}",
                kind=ParleyRoomKind.EVENT,
                title=event.name,
                can_write=event.end_time > window.writable_after,
                can_moderate=event.sphere_id in managed,
                ends_at=int(event.end_time.timestamp()),
            )
            for event in _events(
                user_id=user_id, managed=managed, window=window
            ).order_by("start_time", "name", "pk")
        )
        rooms.extend(
            ParleyRoomDTO(
                id=f"session:{session.event.sphere_id}:{session.pk}",
                kind=ParleyRoomKind.SESSION,
                title=session.title,
                can_write=(
                    session.status == SessionStatus.ACCEPTED
                    and session.event.end_time > window.writable_after
                ),
                can_moderate=session.event.sphere_id in managed,
                ends_at=int(session.event.end_time.timestamp()),
            )
            for session in (
                _sessions(user_id=user_id, managed=managed, window=window)
                .select_related("event")
                .order_by("event__start_time", "title", "pk")
            )
        )
        return ParleyAccessDTO(
            user_id=user.pk,
            user_name=user.get_full_name(),
            user_avatar_url=user.avatar_url,
            rooms=rooms,
            managed_sphere_ids=sorted(managed),
        )

    @staticmethod
    def has_rooms(*, user_id: int, window: ParleyTimeWindow) -> bool:
        if _chat_user(user_id) is None:
            return False
        managed = _managed_sphere_ids(user_id)
        return (
            bool(managed)
            or _events(user_id=user_id, managed=managed, window=window).exists()
            or _sessions(user_id=user_id, managed=managed, window=window).exists()
        )

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
