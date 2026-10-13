"""Repository for the sphere team: memberships and invitation links.

Every query is scoped to the sphere from the request context, so a pk or a
token belonging to another sphere matches nothing here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import Sphere, SphereInvitation, SphereMembership
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.team import (
    InvitationPreviewDTO,
    SphereInvitationDTO,
    SphereTeamRepositoryProtocol,
    TeamMemberDTO,
)

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet

    from ludamus.links.db.django.models import User
    from ludamus.pacts.team import SphereInvitationCreateData


def _open_invitations(*, sphere_id: int, now: datetime) -> QuerySet[SphereInvitation]:
    return SphereInvitation.objects.filter(
        sphere_id=sphere_id, accepted_at__isnull=True, expires_at__gt=now
    )


def _name(user: User | None) -> str:
    # The raw name, not `full_name`: that one falls back to a placeholder
    # person, and an invitation from a stranger by that name misleads.
    return user.name if user is not None else ""


def _invitation_dto(invitation: SphereInvitation) -> SphereInvitationDTO:
    return SphereInvitationDTO(
        pk=invitation.pk,
        role=SphereRole(invitation.role),
        note=invitation.note,
        invited_by=_name(invitation.created_by),
        creation_time=invitation.creation_time,
        expires_at=invitation.expires_at,
    )


class SphereTeamRepository(SphereTeamRepositoryProtocol):
    @staticmethod
    def list_members(*, sphere_id: int) -> list[TeamMemberDTO]:
        memberships = (
            SphereMembership.objects.filter(sphere_id=sphere_id)
            .select_related("user")
            .order_by("user__name", "pk")
        )
        return [
            TeamMemberDTO(
                user_id=membership.user_id,
                name=_name(membership.user),
                email=membership.user.email or None,
                role=SphereRole(membership.role),
            )
            for membership in memberships
        ]

    @staticmethod
    def list_open_invitations(
        *, sphere_id: int, now: datetime
    ) -> list[SphereInvitationDTO]:
        invitations = (
            _open_invitations(sphere_id=sphere_id, now=now)
            .select_related("created_by")
            .order_by("-creation_time", "-pk")
        )
        return [_invitation_dto(invitation) for invitation in invitations]

    @staticmethod
    def create_invitation(data: SphereInvitationCreateData) -> SphereInvitationDTO:
        invitation = SphereInvitation.objects.create(**data)
        return _invitation_dto(invitation)

    @staticmethod
    def delete_open_invitation(*, sphere_id: int, pk: int, now: datetime) -> bool:
        deleted, _ = (
            _open_invitations(sphere_id=sphere_id, now=now).filter(pk=pk).delete()
        )
        return deleted > 0

    @staticmethod
    def read_open_invitation(
        *, sphere_id: int, token_hash: str, now: datetime
    ) -> InvitationPreviewDTO | None:
        invitation = (
            _open_invitations(sphere_id=sphere_id, now=now)
            .select_related("created_by")
            .filter(token_hash=token_hash)
            .first()
        )
        if invitation is None:
            return None
        return InvitationPreviewDTO(
            role=SphereRole(invitation.role), invited_by=_name(invitation.created_by)
        )

    @staticmethod
    def read_sphere_name(*, sphere_id: int) -> str:
        return Sphere.objects.values_list("name", flat=True).get(pk=sphere_id)

    @staticmethod
    def lock_open_invitation(
        *, sphere_id: int, token_hash: str, now: datetime
    ) -> SphereInvitationDTO | None:
        invitation = (
            _open_invitations(sphere_id=sphere_id, now=now)
            .select_for_update()
            .select_related("created_by")
            .filter(token_hash=token_hash)
            .first()
        )
        return None if invitation is None else _invitation_dto(invitation)

    @staticmethod
    def read_member_role(*, sphere_id: int, user_id: int) -> SphereRole | None:
        role = (
            SphereMembership.objects.filter(sphere_id=sphere_id, user_id=user_id)
            .values_list("role", flat=True)
            .first()
        )
        return None if role is None else SphereRole(role)

    @staticmethod
    def add_member(*, sphere_id: int, user_id: int, role: SphereRole) -> bool:
        # get_or_create absorbs the unique (sphere, user) race: two links
        # accepted at once by one person add one membership, not a 500.
        _, created = SphereMembership.objects.get_or_create(
            sphere_id=sphere_id, user_id=user_id, defaults={"role": role}
        )
        return created

    @staticmethod
    def mark_accepted(*, pk: int, user_id: int, now: datetime) -> None:
        SphereInvitation.objects.filter(pk=pk).update(
            accepted_by_id=user_id, accepted_at=now
        )
