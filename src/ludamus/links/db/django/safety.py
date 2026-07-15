from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.adapters.db.django.models import (
    REASON_MAX_LENGTH,
    AgendaItem,
    EventBan,
    SessionParticipation,
    Shadowban,
)
from ludamus.links.db.django.users import display_avatar_url
from ludamus.pacts import NotFoundError, SessionParticipationStatus
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.safety import (
    EventBanDTO,
    EventBanRepositoryProtocol,
    SessionShadowbanWarningDTO,
    ShadowbanCandidateDTO,
    ShadowbanEventSignupDTO,
    ShadowbanHitDTO,
    ShadowbanMeetSessionDTO,
    ShadowbanRepositoryProtocol,
)

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


def _resolve_user(identifier: str) -> User | None:
    return (
        User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        )
        .order_by("pk")
        .first()
    )


def _met_sessions_by_player(
    owner_id: int, player_ids: list[int]
) -> dict[int, list[ShadowbanMeetSessionDTO]]:
    if not player_ids:
        return {}

    confirmed = SessionParticipationStatus.CONFIRMED
    rows: dict[tuple[int, int], ShadowbanMeetSessionDTO] = {}

    presented = SessionParticipation.objects.filter(
        user_id__in=player_ids, session__presenter_id=owner_id
    )
    alongside = SessionParticipation.objects.filter(
        user_id__in=player_ids,
        status=confirmed,
        session__session_participations__user_id=owner_id,
        session__session_participations__status=confirmed,
    )
    for queryset in (presented, alongside):
        for row in queryset.values(
            "user_id",
            "session_id",
            "session__title",
            "session__event__slug",
            "session__event__name",
            "session__event__sphere__name",
            "session__event__sphere__site__domain",
        ).distinct():
            rows.setdefault(
                (row["user_id"], row["session_id"]),
                ShadowbanMeetSessionDTO(
                    session_id=row["session_id"],
                    title=row["session__title"],
                    event_slug=row["session__event__slug"],
                    event_name=row["session__event__name"],
                    sphere_name=row["session__event__sphere__name"],
                    sphere_domain=row["session__event__sphere__site__domain"],
                ),
            )

    by_player: dict[int, list[ShadowbanMeetSessionDTO]] = {
        player_id: [] for player_id in player_ids
    }
    for (user_id, _session_id), dto in rows.items():
        by_player[user_id].append(dto)

    for sessions in by_player.values():
        sessions.sort(key=lambda session: session.title.casefold())

    return by_player


class ShadowbanRepository(ShadowbanRepositoryProtocol):
    @staticmethod
    def list_candidates(owner_id: int) -> list[ShadowbanCandidateDTO]:
        banned_ids = set(
            Shadowban.objects.filter(owner_id=owner_id).values_list(
                "target_id", flat=True
            )
        )
        confirmed = SessionParticipationStatus.CONFIRMED
        played_alongside = Q(
            session_participations__status=confirmed,
            session_participations__session__session_participations__user_id=owner_id,
            session_participations__session__session_participations__status=confirmed,
        )
        players = (
            User.objects.filter(
                Q(session_participations__session__presenter_id=owner_id)
                | played_alongside
                | Q(shadowbanned_by__id=owner_id)
            )
            .exclude(pk=owner_id)
            .distinct()
            .order_by("name")
        )
        met_by_player = _met_sessions_by_player(
            owner_id, [player.pk for player in players]
        )
        candidates = [
            ShadowbanCandidateDTO(
                pk=player.pk,
                full_name=player.full_name,
                username=player.username,
                slug=player.slug,
                avatar_url=display_avatar_url(player),
                is_shadowbanned=player.pk in banned_ids,
                met_sessions=met_by_player[player.pk],
            )
            for player in players
        ]
        candidates.sort(key=lambda candidate: not candidate.is_shadowbanned)
        return candidates

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
        presenter_rows = (
            User.objects.filter(
                presented_sessions__event_id=event.pk,
                presented_sessions__agenda_item__isnull=False,
                shadowbanned__id__in=signed_up_ids,
            )
            .values_list("pk", "email", "shadowbanned__id")
            .distinct()
        )
        occupying = (
            SessionParticipationStatus.CONFIRMED,
            SessionParticipationStatus.WAITING,
            SessionParticipationStatus.OFFERED,
        )
        player_rows = (
            User.objects.filter(
                session_participations__session_id=session_id,
                session_participations__status__in=occupying,
                shadowbanned__id__in=signed_up_ids,
            )
            .values_list("pk", "email", "shadowbanned__id")
            .distinct()
        )
        in_session_pairs = {
            (recipient_id, banned_user_id)
            for recipient_id, _email, banned_user_id in player_rows
        }
        hits: dict[tuple[int, int], ShadowbanHitDTO] = {}
        for recipient_id, email, banned_user_id in (*presenter_rows, *player_rows):
            hits[recipient_id, banned_user_id] = ShadowbanHitDTO(
                recipient_id=recipient_id,
                recipient_email=email,
                banned_user_id=banned_user_id,
                in_session=(recipient_id, banned_user_id) in in_session_pairs,
            )
        return ShadowbanEventSignupDTO(
            event_slug=event.slug,
            event_name=event.name,
            session_title=agenda_item.session.title,
            hits=list(hits.values()),
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
    def banned_event_ids(*, event_ids: set[int], user_id: int) -> set[int]:
        return set(
            EventBan.objects.filter(
                event_id__in=event_ids, user_id=user_id
            ).values_list("event_id", flat=True)
        )

    @staticmethod
    def ban(*, event_id: int, identifier: str, reason: str) -> bool:
        if (user := _resolve_user(identifier)) is None:
            return False
        EventBan.objects.update_or_create(
            event_id=event_id,
            user=user,
            defaults={"reason": reason[:REASON_MAX_LENGTH]},
        )
        return True

    @staticmethod
    def unban(*, event_id: int, ban_id: int) -> None:
        EventBan.objects.filter(event_id=event_id, pk=ban_id).delete()
