"""Sphere team: listing who runs a sphere and inviting more people to.

Every method takes the sphere id from the caller's request context and the
repository scopes each query to it, so an invitation id or token from another
sphere is simply not found here.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.team import AcceptInvitationOutcome, SphereTeamServiceProtocol
from ludamus.specs.permissions import INVITATION_LIFETIME

if TYPE_CHECKING:
    from ludamus.pacts.multiverse import SphereRole
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.team import (
        InvitationPreviewDTO,
        SphereInvitationDTO,
        SphereTeamRepositoryProtocol,
        TeamMemberDTO,
    )


class SphereTeamService(SphereTeamServiceProtocol):
    def __init__(
        self, *, transaction: TransactionProtocol, team: SphereTeamRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._team = team

    def list_members(self, *, sphere_id: int) -> list[TeamMemberDTO]:
        return self._team.list_members(sphere_id=sphere_id)

    def list_open_invitations(self, *, sphere_id: int) -> list[SphereInvitationDTO]:
        return self._team.list_open_invitations(
            sphere_id=sphere_id, now=datetime.now(tz=UTC)
        )

    def invite(
        self, *, sphere_id: int, role: SphereRole, invited_by_id: int
    ) -> SphereInvitationDTO:
        with self._transaction.atomic():
            return self._team.create_invitation(
                {
                    "sphere_id": sphere_id,
                    "role": role,
                    "token": secrets.token_urlsafe(32),
                    "created_by_id": invited_by_id,
                    "expires_at": datetime.now(tz=UTC) + INVITATION_LIFETIME,
                }
            )

    def revoke(self, *, sphere_id: int, pk: int) -> bool:
        with self._transaction.atomic():
            return self._team.delete_open_invitation(
                sphere_id=sphere_id, pk=pk, now=datetime.now(tz=UTC)
            )

    def preview(self, *, sphere_id: int, token: str) -> InvitationPreviewDTO | None:
        return self._team.read_open_invitation(
            sphere_id=sphere_id, token=token, now=datetime.now(tz=UTC)
        )

    def accept(
        self, *, sphere_id: int, token: str, user_id: int
    ) -> AcceptInvitationOutcome:
        now = datetime.now(tz=UTC)
        with self._transaction.atomic():
            # Locked, so two people opening one link at once cannot both join.
            invitation = self._team.lock_open_invitation(
                sphere_id=sphere_id, token=token, now=now
            )
            if invitation is None:
                return AcceptInvitationOutcome.INVALID
            if self._team.is_member(sphere_id=sphere_id, user_id=user_id):
                return AcceptInvitationOutcome.ALREADY_MEMBER
            self._team.add_member(
                sphere_id=sphere_id, user_id=user_id, role=invitation.role
            )
            self._team.mark_accepted(pk=invitation.pk, user_id=user_id, now=now)
            return AcceptInvitationOutcome.JOINED
