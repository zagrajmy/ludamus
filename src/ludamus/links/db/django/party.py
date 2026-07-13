"""Repository for the party subdomain (RFC 0001).

Implements `PartyRepositoryProtocol`: the overview read model for the parties
page and the leader-scoped mutations. Ownership guards live in the queries
(conditional filters), mirroring the claim repository's style.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.adapters.db.django.models import (
    Party,
    PartyMembership,
    Session,
    SessionParticipation,
)
from ludamus.links.db.django.companions import active_companions
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import ConnectedUserDTO, UserDTO, UserType
from ludamus.pacts.legacy import (
    AgendaItemDTO,
    LocationData,
    SessionDTO,
    SessionParticipationStatus,
)
from ludamus.pacts.party import (
    InvitedUserDTO,
    LedPartyDTO,
    PartiesOverviewDTO,
    PartyConsentMode,
    PartyDTO,
    PartyEventHistoryDTO,
    PartyInviteDTO,
    PartyMemberDTO,
    PartyMembershipStatus,
    PartyRepositoryProtocol,
    PartySessionHistoryDTO,
    PartySessionSeatDTO,
)

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


class PartyRepository(PartyRepositoryProtocol):
    @staticmethod
    def overview(viewer_pk: int) -> PartiesOverviewDTO:
        parties = (
            Party.objects.filter(
                Q(leader_id=viewer_pk)
                | Q(
                    memberships__member_id=viewer_pk,
                    memberships__status=PartyMembershipStatus.ACTIVE,
                )
            )
            .select_related("leader")
            .distinct()
            .order_by("pk")
        )
        # The viewer's first led party by pk is their default one — the party
        # that sponsors companions (see `_default_led_party` in the crowd repo).
        default_party_pk = next(
            (party.pk for party in parties if party.leader_id == viewer_pk), None
        )
        party_dtos = []
        for party in parties:
            memberships = party.memberships.select_related("member").order_by("pk")
            members = [
                PartyMemberDTO(
                    membership_pk=membership.pk,
                    user_pk=membership.member_id,
                    name=membership.member.name,
                    full_name=membership.member.get_full_name(),
                    username=membership.member.username,
                    slug=membership.member.slug,
                    is_login_less=membership.member.user_type == UserType.CONNECTED,
                    is_leader=membership.member_id == party.leader_id,
                    consent_mode=PartyConsentMode(membership.consent_mode),
                    status=PartyMembershipStatus(membership.status),
                    claim_token=membership.member.claim_token,
                    avatar_url=_display_avatar_url(membership.member),
                )
                for membership in memberships
            ]
            # Leader first, then the rest in creation order.
            members.sort(key=lambda m: (not m.is_leader,))
            party_dtos.append(
                PartyDTO(
                    pk=party.pk,
                    name=party.name,
                    leader_pk=party.leader_id,
                    leader_name=party.leader.get_full_name(),
                    is_leader=party.leader_id == viewer_pk,
                    is_default=party.pk == default_party_pk,
                    created_at=party.created_at,
                    members=members,
                )
            )
        invites = [
            PartyInviteDTO(
                membership_pk=membership.pk,
                party_pk=membership.party_id,
                party_name=membership.party.name,
                leader_name=membership.party.leader.get_full_name(),
            )
            for membership in (
                PartyMembership.objects.filter(
                    member_id=viewer_pk, status=PartyMembershipStatus.INVITED
                )
                .select_related("party__leader")
                .order_by("pk")
            )
        ]
        return PartiesOverviewDTO(parties=party_dtos, invites=invites)

    @staticmethod
    def create(*, leader_pk: int, name: str) -> int:
        party = Party.objects.create(leader_id=leader_pk, name=name)
        PartyMembership.objects.create(
            party=party,
            member_id=leader_pk,
            consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
            status=PartyMembershipStatus.ACTIVE,
        )
        return party.pk

    @staticmethod
    def rename(*, leader_pk: int, party_pk: int, name: str) -> bool:
        return bool(
            Party.objects.filter(pk=party_pk, leader_id=leader_pk).update(name=name)
        )

    @staticmethod
    def has_companions(*, leader_pk: int, party_pk: int) -> bool:
        return PartyMembership.objects.filter(
            party_id=party_pk,
            party__leader_id=leader_pk,
            member__user_type=UserType.CONNECTED,
        ).exists()

    @staticmethod
    def delete(*, leader_pk: int, party_pk: int) -> bool:
        deleted, __ = Party.objects.filter(pk=party_pk, leader_id=leader_pk).delete()
        return bool(deleted)

    @staticmethod
    def read_led_party(*, leader_pk: int, party_pk: int) -> LedPartyDTO | None:
        party = (
            Party.objects.filter(pk=party_pk, leader_id=leader_pk)
            .select_related("leader")
            .first()
        )
        if party is None:
            return None
        return LedPartyDTO(name=party.name, leader_name=party.leader.get_full_name())

    @staticmethod
    def find_invitable_user(email: str) -> InvitedUserDTO | None:
        if not email:
            return None
        user = (
            User.objects.filter(email__iexact=email, user_type=UserType.ACTIVE)
            .order_by("pk")
            .first()
        )
        return InvitedUserDTO.model_validate(user) if user is not None else None

    @staticmethod
    def membership_exists(*, party_pk: int, user_pk: int) -> bool:
        return PartyMembership.objects.filter(
            party_id=party_pk, member_id=user_pk
        ).exists()

    @staticmethod
    def create_invited_membership(*, party_pk: int, user_pk: int) -> None:
        PartyMembership.objects.create(
            party_id=party_pk,
            member_id=user_pk,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

    @staticmethod
    def accept_invite(*, membership_pk: int, user_pk: int) -> bool:
        return bool(
            PartyMembership.objects.filter(
                pk=membership_pk,
                member_id=user_pk,
                status=PartyMembershipStatus.INVITED,
            ).update(status=PartyMembershipStatus.ACTIVE)
        )

    @staticmethod
    def decline_invite(*, membership_pk: int, user_pk: int) -> bool:
        deleted, __ = PartyMembership.objects.filter(
            pk=membership_pk, member_id=user_pk, status=PartyMembershipStatus.INVITED
        ).delete()
        return bool(deleted)

    @staticmethod
    def remove_member(
        *, leader_pk: int, party_pk: int, membership_pk: int
    ) -> PartyMembershipStatus | None:
        # Companions are excluded: their identity row lives and dies with the
        # sponsorship, and the connected-user delete action owns that flow.
        membership = (
            PartyMembership.objects.filter(
                pk=membership_pk, party_id=party_pk, party__leader_id=leader_pk
            )
            .exclude(member_id=leader_pk)
            .exclude(member__user_type=UserType.CONNECTED)
            .first()
        )
        if membership is None:
            return None
        status = PartyMembershipStatus(membership.status)
        membership.delete()
        return status

    @staticmethod
    def led_party_companions(
        *, leader_pk: int, party_pk: int
    ) -> list[ConnectedUserDTO]:
        party = (
            Party.objects.filter(pk=party_pk, leader_id=leader_pk)
            .select_related("leader")
            .first()
        )
        if party is None:
            return []
        return [
            ConnectedUserDTO.model_validate(companion)
            for companion in (
                active_companions(party.leader.slug)
                .filter(party_memberships__party_id=party_pk)
                .order_by("pk")
            )
        ]

    @staticmethod
    def set_consent(*, user_pk: int, party_pk: int, mode: PartyConsentMode) -> bool:
        # Only a real member adjusts their own consent; the leader's own row is
        # meaningless here (self-enrollment needs no consent) and login-less
        # companions have no say by definition.
        return bool(
            PartyMembership.objects.filter(
                party_id=party_pk,
                member_id=user_pk,
                status=PartyMembershipStatus.ACTIVE,
            )
            .exclude(party__leader_id=user_pk)
            .exclude(member__user_type=UserType.CONNECTED)
            .update(consent_mode=mode)
        )

    @staticmethod
    def leave(*, user_pk: int, party_pk: int) -> bool:
        deleted, __ = (
            PartyMembership.objects.filter(
                party_id=party_pk,
                member_id=user_pk,
                status=PartyMembershipStatus.ACTIVE,
            )
            .exclude(party__leader_id=user_pk)
            .delete()
        )
        return bool(deleted)

    @staticmethod
    def session_history(
        *, party_pk: int, viewer_pk: int
    ) -> list[PartyEventHistoryDTO] | None:
        is_member = Party.objects.filter(
            Q(leader_id=viewer_pk)
            | Q(
                memberships__member_id=viewer_pk,
                memberships__status=PartyMembershipStatus.ACTIVE,
            ),
            pk=party_pk,
        ).exists()
        if not is_member:
            return None
        session_ids = (
            SessionParticipation.objects.filter(
                party_id=party_pk, status=SessionParticipationStatus.CONFIRMED
            )
            .values_list("session_id", flat=True)
            .distinct()
        )
        sessions = (
            Session.objects.filter(pk__in=session_ids, agenda_item__isnull=False)
            .select_related("event", "presenter", "agenda_item__space__parent")
            .prefetch_related("session_participations__user")
            .order_by("agenda_item__start_time")
        )
        groups: dict[int, PartyEventHistoryDTO] = {}
        for session in sessions:
            space = session.agenda_item.space
            item = PartySessionHistoryDTO(
                session=SessionDTO.model_validate(session),
                agenda_item=AgendaItemDTO.model_validate(session.agenda_item),
                presenter=(
                    _user_dto_with_display_avatar(session.presenter)
                    if session.presenter is not None
                    else None
                ),
                participations=[
                    PartySessionSeatDTO(
                        user=_user_dto_with_display_avatar(sp.user),
                        status=sp.status,
                        creation_time=sp.creation_time,
                    )
                    for sp in session.session_participations.all()
                ],
                location=LocationData(
                    space_name=space.name,
                    parent_slug=space.parent.slug if space.parent else "",
                    parent_name=space.parent.name if space.parent else "",
                    path=str(space),
                ),
                enrolled_count=session.enrolled_count,
                waiting_count=session.waiting_count,
                is_full=session.is_full,
                is_enrollment_available=session.is_enrollment_available,
                effective_participants_limit=session.effective_participants_limit,
                full_participant_info=session.full_participant_info,
                viewer_enrolled=any(
                    sp.user_id == viewer_pk
                    and sp.status == SessionParticipationStatus.CONFIRMED
                    for sp in session.session_participations.all()
                ),
            )
            group = groups.get(session.event_id)
            if group is None:
                groups[session.event_id] = PartyEventHistoryDTO(
                    event_pk=session.event_id,
                    event_name=session.event.name,
                    event_slug=session.event.slug,
                    sessions=[item],
                )
            else:
                group.sessions.append(item)
        return sorted(
            groups.values(),
            key=lambda g: g.sessions[-1].agenda_item.start_time,
            reverse=True,
        )


def _display_avatar_url(user: User) -> str:
    if user.use_gravatar:
        return gravatar_url(user.email) or ""
    return user.avatar_url or gravatar_url(user.email) or ""


def _user_dto_with_display_avatar(user: User) -> UserDTO:
    return UserDTO.model_validate(user).model_copy(
        update={"avatar_url": _display_avatar_url(user)}
    )
