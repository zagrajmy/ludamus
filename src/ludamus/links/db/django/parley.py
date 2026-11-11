from __future__ import annotations

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


class ParleyRepository(ParleyRepositoryProtocol):
    @staticmethod
    def read_access(
        *, sphere_id: int, user_id: int, window: ParleyTimeWindow
    ) -> ParleyAccessDTO | None:
        try:
            sphere = Sphere.objects.get(pk=sphere_id, parley_enabled=True)
            user = User.objects.get(
                pk=user_id, is_active=True, user_type=UserType.ACTIVE
            )
        except Sphere.DoesNotExist, User.DoesNotExist:
            return None

        is_manager = user.is_superuser or sphere.managers.filter(pk=user_id).exists()
        eligible = Q(
            session_participations__user_id=user_id,
            session_participations__status=SessionParticipationStatus.CONFIRMED,
        ) | Q(facilitators__user_id=user_id)
        sessions = Session.objects.filter(
            event__sphere_id=sphere_id, event__end_time__gt=window.retained_after
        ).exclude(
            event_id__in=EventBan.objects.filter(user_id=user_id).values("event_id")
        )
        if not is_manager:
            sessions = sessions.filter(eligible)

        rooms = [
            ParleyRoomDTO(
                id=f"sphere:{sphere.pk}",
                kind=ParleyRoomKind.SPHERE,
                title=sphere.name,
                can_write=True,
                can_moderate=is_manager,
            )
        ]
        rooms.extend(
            ParleyRoomDTO(
                id=f"session:{sphere.pk}:{session.pk}",
                kind=ParleyRoomKind.SESSION,
                title=session.title,
                can_write=(
                    session.status == SessionStatus.ACCEPTED
                    and session.event.end_time > window.writable_after
                ),
                can_moderate=is_manager,
                session_id=session.pk,
                ends_at=int(session.event.end_time.timestamp()),
            )
            for session in (
                sessions.select_related("event")
                .distinct()
                .order_by("event__start_time", "title", "pk")
            )
        )
        return ParleyAccessDTO(
            sphere_id=sphere.pk,
            sphere_name=sphere.name,
            user_id=user.pk,
            user_name=user.get_full_name(),
            user_avatar_url=user.avatar_url,
            rooms=rooms,
            is_manager=is_manager,
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
