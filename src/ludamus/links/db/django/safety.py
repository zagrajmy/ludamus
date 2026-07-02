from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.adapters.db.django.models import (
    REASON_MAX_LENGTH,
    AgendaItem,
    EventBan,
    Shadowban,
)
from ludamus.pacts import NotFoundError, SessionParticipationStatus
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.safety import (
    EventBanDTO,
    EventBanRepositoryProtocol,
    SessionShadowbanWarningDTO,
    ShadowbanCandidateDTO,
    ShadowbanEventSignupDTO,
    ShadowbanHitDTO,
    ShadowbanRepositoryProtocol,
)

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


def _resolve_user(identifier: str) -> User | None:
    # Account resolution by either handle; shared so the "no enumeration"
    # contract has a single home.
    return (
        User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        )
        .order_by("pk")
        .first()
    )


class ShadowbanRepository(ShadowbanRepositoryProtocol):
    @staticmethod
    def list_candidates(owner_id: int) -> list[ShadowbanCandidateDTO]:
        banned_ids = set(
            Shadowban.objects.filter(owner_id=owner_id).values_list(
                "target_id", flat=True
            )
        )
        # Players the proposer has met (participated in a session they run) plus
        # anyone already shadowbanned, so a ban can always be lifted.
        players = (
            User.objects.filter(
                Q(session_participations__session__presenter_id=owner_id)
                | Q(shadowbanned_by__id=owner_id)
            )
            .exclude(pk=owner_id)
            .distinct()
            .order_by("name")
        )
        return [
            ShadowbanCandidateDTO(
                pk=player.pk,
                name=player.full_name,
                slug=player.slug,
                is_shadowbanned=player.pk in banned_ids,
            )
            for player in players
        ]

    @staticmethod
    def banned_user_ids(owner_id: int) -> set[int]:
        return set(
            Shadowban.objects.filter(owner_id=owner_id).values_list(
                "target_id", flat=True
            )
        )

    @staticmethod
    def banning_owner_ids(target_id: int) -> set[int]:
        return set(
            Shadowban.objects.filter(target_id=target_id).values_list(
                "owner_id", flat=True
            )
        )

    @staticmethod
    def set_shadowban(*, owner_id: int, target_slug: str, banned: bool) -> None:
        try:
            target = User.objects.get(slug=target_slug)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        if target.pk == owner_id:
            return
        if banned:
            Shadowban.objects.get_or_create(owner_id=owner_id, target=target)
        else:
            Shadowban.objects.filter(owner_id=owner_id, target=target).delete()

    @staticmethod
    def shadowban_by_identifier(*, owner_id: int, identifier: str) -> bool:
        target = _resolve_user(identifier)
        if target is None or target.pk == owner_id:
            return False
        Shadowban.objects.get_or_create(owner_id=owner_id, target=target)
        return True

    @staticmethod
    def list_session_shadowbanned(
        *, viewer_id: int, session_id: int
    ) -> list[SessionShadowbanWarningDTO]:
        occupying = (
            SessionParticipationStatus.CONFIRMED,
            SessionParticipationStatus.WAITING,
            SessionParticipationStatus.OFFERED,
        )
        rows = (
            Shadowban.objects.filter(
                owner_id=viewer_id,
                target__session_participations__session_id=session_id,
                target__session_participations__status__in=occupying,
            )
            .select_related("target")
            .distinct()
            .order_by("target__name")
        )
        return [
            SessionShadowbanWarningDTO(
                user=UserDTO.model_validate(row.target), shadowbanned_at=row.created_at
            )
            for row in rows
        ]

    @staticmethod
    def read_event_signup(
        *, session_id: int, signed_up_ids: list[int]
    ) -> ShadowbanEventSignupDTO | None:
        if not signed_up_ids:
            return None
        agenda_item = (
            AgendaItem.objects.select_related("session__event")
            .filter(session_id=session_id)
            .order_by("pk")
            .first()
        )
        if agenda_item is None:
            return None
        event = agenda_item.session.event
        # Presenters with a scheduled session in this event who shadowbanned any
        # of the players that just signed up.
        rows = (
            User.objects.filter(
                presented_sessions__event_id=event.pk,
                presented_sessions__agenda_item__isnull=False,
                shadowbanned__id__in=signed_up_ids,
            )
            .values_list("pk", "email", "shadowbanned__id")
            .distinct()
        )
        return ShadowbanEventSignupDTO(
            event_slug=event.slug,
            event_name=event.name,
            hits=[
                ShadowbanHitDTO(
                    presenter_id=presenter_id,
                    presenter_email=email,
                    banned_user_id=banned_user_id,
                )
                for presenter_id, email, banned_user_id in rows
            ],
        )


class EventBanRepository(EventBanRepositoryProtocol):
    @staticmethod
    def list_by_event(event_id: int) -> list[EventBanDTO]:
        rows = (
            EventBan.objects.filter(event_id=event_id)
            .select_related("user")
            .order_by("user__name")
        )
        return [
            EventBanDTO(
                pk=ban.pk,
                user_name=ban.user.full_name,
                user_slug=ban.user.slug,
                reason=ban.reason,
                created_at=ban.created_at,
            )
            for ban in rows
        ]

    @staticmethod
    def is_banned(*, event_id: int, user_id: int) -> bool:
        return EventBan.objects.filter(event_id=event_id, user_id=user_id).exists()

    @staticmethod
    def ban(*, event_id: int, identifier: str, reason: str) -> bool:
        if (user := _resolve_user(identifier)) is None:
            return False
        # Bound to the column width so a long note can't crash the write on
        # backends that enforce max_length (e.g. Postgres).
        EventBan.objects.update_or_create(
            event_id=event_id,
            user=user,
            defaults={"reason": reason[:REASON_MAX_LENGTH]},
        )
        return True

    @staticmethod
    def unban(*, event_id: int, ban_id: int) -> None:
        EventBan.objects.filter(event_id=event_id, pk=ban_id).delete()
