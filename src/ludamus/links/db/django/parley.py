from __future__ import annotations

from django.db.models import Q

from ludamus.links.db.django.models import EventBan, ParleyReport, Session, Sphere, User
from ludamus.pacts import SessionParticipationStatus, SessionStatus
from ludamus.pacts.crowd import UserType
from ludamus.pacts.parley import (
    ParleyAccessDTO,
    ParleyReportData,
    ParleyRepositoryProtocol,
    ParleyRoomDTO,
    ParleyRoomKind,
    ParleyTimeWindow,
)


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
                id=f"session:{session.pk}",
                kind=ParleyRoomKind.SESSION,
                title=session.title,
                can_write=(
                    session.status == SessionStatus.ACCEPTED
                    and session.event.end_time > window.writable_after
                ),
                can_moderate=is_manager,
                read_only_at=int(
                    (session.event.end_time + window.read_only_delay).timestamp()
                ),
                delete_at=int((session.event.end_time + window.retention).timestamp()),
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
            moderated_room_ids=([room.id for room in rooms] if is_manager else []),
        )

    def create_report(
        self, *, data: ParleyReportData, window: ParleyTimeWindow
    ) -> bool:
        access = self.read_access(
            sphere_id=data.sphere_id, user_id=data.user_id, window=window
        )
        if access is None or data.room_id not in {room.id for room in access.rooms}:
            return False
        ParleyReport.objects.get_or_create(
            reporter_id=data.user_id,
            room_id=data.room_id,
            message_id=data.message_id,
            defaults={"reason": data.reason, "sphere_id": data.sphere_id},
        )
        return True
