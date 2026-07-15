"""Repository for the party subdomain (RFC 0001).

Implements `PartyRepositoryProtocol`: the overview read model for the parties
page and the leader-scoped mutations. Ownership guards live in the queries
(conditional filters), mirroring the claim repository's style.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Prefetch, Q

from ludamus.adapters.db.django.models import Party, PartyMembership
from ludamus.links.db.django.companions import active_companions
from ludamus.links.db.django.users import display_avatar_url
from ludamus.pacts.crowd import CompanionDTO, UserType
from ludamus.pacts.party import (
    InvitablePartyDTO,
    InvitedUserDTO,
    PartiesOverviewDTO,
    PartyActionContextDTO,
    PartyConsentMode,
    PartyDTO,
    PartyInviteDTO,
    PartyJoinResult,
    PartyMemberDTO,
    PartyMembershipStatus,
    PartyRepositoryProtocol,
)

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


def _party_dto(party: Party, *, viewer_pk: int) -> PartyDTO:
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
            claim_token=(
                membership.member.claim_token
                if membership.member.manager_id == viewer_pk
                else ""
            ),
            avatar_url=display_avatar_url(membership.member),
            is_managed_by_viewer=membership.member.manager_id == viewer_pk,
        )
        for membership in party.memberships.all()
    ]
    members.sort(key=lambda member: not member.is_leader)
    return PartyDTO(
        pk=party.pk,
        name=party.name,
        leader_pk=party.leader_id,
        leader_name=party.leader.get_full_name(),
        is_leader=party.leader_id == viewer_pk,
        is_active_member=any(
            member.user_pk == viewer_pk
            and member.status == PartyMembershipStatus.ACTIVE
            for member in members
        ),
        created_at=party.created_at,
        members=members,
    )


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
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=PartyMembership.objects.select_related("member").order_by(
                        "pk"
                    ),
                )
            )
            .distinct()
            .order_by("pk")
        )
        party_dtos = [_party_dto(party, viewer_pk=viewer_pk) for party in parties]
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
    def read_for_viewer(*, party_pk: int, viewer_pk: int) -> PartyDTO | None:
        party = (
            Party.objects.filter(
                Q(leader_id=viewer_pk)
                | Q(
                    memberships__member_id=viewer_pk,
                    memberships__status=PartyMembershipStatus.ACTIVE,
                ),
                pk=party_pk,
            )
            .select_related("leader")
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=PartyMembership.objects.select_related("member").order_by(
                        "pk"
                    ),
                )
            )
            .distinct()
            .first()
        )
        if party is None:
            return None
        return _party_dto(party, viewer_pk=viewer_pk)

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
    def delete(*, leader_pk: int, party_pk: int) -> bool:
        deleted, __ = Party.objects.filter(pk=party_pk, leader_id=leader_pk).delete()
        return bool(deleted)

    @staticmethod
    def read_active_member_party(
        *, member_pk: int, party_pk: int
    ) -> PartyActionContextDTO | None:
        membership = (
            PartyMembership.objects.select_for_update()
            .filter(
                party_id=party_pk,
                member_id=member_pk,
                status=PartyMembershipStatus.ACTIVE,
            )
            .select_related("party", "member")
            .first()
        )
        if membership is None:
            return None
        return PartyActionContextDTO(
            name=membership.party.name, actor_name=membership.member.get_full_name()
        )

    @staticmethod
    def lock_owned_companions(*, manager_pk: int) -> list[CompanionDTO]:
        companions = User.objects.select_for_update().filter(
            manager_id=manager_pk, user_type=UserType.CONNECTED
        )
        return [CompanionDTO.model_validate(companion) for companion in companions]

    @staticmethod
    def find_invitable_users(identifier: str) -> list[InvitedUserDTO]:
        if not (identifier := identifier.strip().lstrip("@")):
            return []
        by_email = (
            User.objects.filter(email__iexact=identifier, user_type=UserType.ACTIVE)
            .order_by("pk")
            .first()
        )
        if by_email is not None:
            return [InvitedUserDTO.model_validate(by_email)]
        by_discord = User.objects.filter(
            discord_username__iexact=identifier, user_type=UserType.ACTIVE
        ).order_by("pk")
        return [InvitedUserDTO.model_validate(user) for user in by_discord[:2]]

    @staticmethod
    def set_invite_token(*, leader_pk: int, party_pk: int, token: str) -> bool:
        return bool(
            Party.objects.filter(pk=party_pk, leader_id=leader_pk).update(
                invite_token=token
            )
        )

    @staticmethod
    def read_invite_token(*, leader_pk: int, party_pk: int) -> str:
        party = (
            Party.objects.filter(pk=party_pk, leader_id=leader_pk)
            .only("invite_token")
            .first()
        )
        return party.invite_token if party is not None else ""

    @staticmethod
    def read_party_by_invite_token(
        *, token: str, viewer_pk: int
    ) -> InvitablePartyDTO | None:
        if not token:
            return None
        party = (
            Party.objects.filter(invite_token=token).select_related("leader").first()
        )
        if party is None:
            return None
        return InvitablePartyDTO(
            pk=party.pk,
            name=party.name,
            leader_name=party.leader.get_full_name(),
            already_member=PartyMembership.objects.filter(
                party_id=party.pk,
                member_id=viewer_pk,
                status=PartyMembershipStatus.ACTIVE,
            ).exists(),
        )

    @staticmethod
    def join_via_token(*, token: str, user_pk: int) -> PartyJoinResult | None:
        if not token:
            return None
        if (
            party := Party.objects.select_for_update()
            .filter(invite_token=token)
            .first()
        ) is None:
            return None
        membership, created = PartyMembership.objects.select_for_update().get_or_create(
            party_id=party.pk,
            member_id=user_pk,
            defaults={
                "consent_mode": PartyConsentMode.ACCEPT_INVITES,
                "status": PartyMembershipStatus.ACTIVE,
            },
        )
        joined = created or membership.status == PartyMembershipStatus.INVITED
        if not created and joined:
            membership.status = PartyMembershipStatus.ACTIVE
            membership.save(update_fields=["status"])
        return PartyJoinResult(party_pk=party.pk, joined=joined)

    @staticmethod
    def get_or_create_membership(
        *,
        party_pk: int,
        user_pk: int,
        consent_mode: PartyConsentMode = PartyConsentMode.ACCEPT_INVITES,
        status: PartyMembershipStatus = PartyMembershipStatus.INVITED,
    ) -> bool:
        __, created = PartyMembership.objects.get_or_create(
            party_id=party_pk,
            member_id=user_pk,
            defaults={"consent_mode": consent_mode, "status": status},
        )
        return created

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
        membership = (
            PartyMembership.objects.select_for_update()
            .filter(
                pk=membership_pk,
                member_id=user_pk,
                status=PartyMembershipStatus.INVITED,
            )
            .first()
        )
        if membership is None:
            return False
        deleted, __ = membership.delete()
        return bool(deleted)

    @staticmethod
    def remove_member(
        *, leader_pk: int, party_pk: int, membership_pk: int
    ) -> PartyMembershipStatus | None:
        membership = (
            PartyMembership.objects.select_for_update()
            .filter(pk=membership_pk, party_id=party_pk, party__leader_id=leader_pk)
            .exclude(member_id=leader_pk)
            .first()
        )
        if membership is None:
            return None
        status = PartyMembershipStatus(membership.status)
        membership.delete()
        return status

    @staticmethod
    def led_party_companions(
        *, leader_pk: int, party_pk: int | None
    ) -> list[CompanionDTO]:
        if party_pk is None:
            leader = User.objects.filter(
                pk=leader_pk, user_type=UserType.ACTIVE
            ).first()
            if leader is None:
                return []
            companions = active_companions(leader.slug).order_by("pk")
        else:
            party = (
                Party.objects.filter(pk=party_pk, leader_id=leader_pk)
                .select_related("leader")
                .first()
            )
            if party is None:
                return []
            companions = User.objects.filter(
                user_type=UserType.CONNECTED, party_memberships__party_id=party_pk
            ).order_by("pk")
        return [CompanionDTO.model_validate(companion) for companion in companions]

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
