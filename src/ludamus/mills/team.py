"""Sphere team: listing who runs a sphere and inviting more people to.

Every method takes the sphere id from the caller's request context and the
repository scopes each query to it, so an invitation id or token from another
sphere is simply not found here.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.team import (
    AcceptInvitationOutcome,
    IssuedInvitationDTO,
    JoinPageDTO,
    SphereTeamServiceProtocol,
)
from ludamus.specs.permissions import INVITATION_LIFETIME

if TYPE_CHECKING:
    from ludamus.pacts.multiverse import SphereRole
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.team import (
        SphereInvitationDTO,
        SphereTeamRepositoryProtocol,
        TeamMemberDTO,
    )


def token_hash(token: str) -> str:
    # SAFETY: only this digest is stored. A leaked table or backup then holds
    # no link that would still let its reader join a team.
    return hashlib.sha256(token.encode()).hexdigest()


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
        self, *, sphere_id: int, role: SphereRole, note: str, invited_by_id: int
    ) -> IssuedInvitationDTO:
        token = secrets.token_urlsafe(32)
        with self._transaction.atomic():
            invitation = self._team.create_invitation(
                {
                    "sphere_id": sphere_id,
                    "role": role,
                    "token_hash": token_hash(token),
                    "note": note.strip(),
                    "created_by_id": invited_by_id,
                    "expires_at": datetime.now(tz=UTC) + INVITATION_LIFETIME,
                }
            )
        return IssuedInvitationDTO(invitation=invitation, token=token)

    def reissue(
        self, *, sphere_id: int, pk: int, reissued_by_id: int
    ) -> IssuedInvitationDTO | None:
        token = secrets.token_urlsafe(32)
        now = datetime.now(tz=UTC)
        with self._transaction.atomic():
            invitation = self._team.rotate_open_invitation(
                sphere_id=sphere_id,
                pk=pk,
                rotation={
                    "token_hash": token_hash(token),
                    "created_by_id": reissued_by_id,
                    "creation_time": now,
                    "expires_at": now + INVITATION_LIFETIME,
                },
                now=now,
            )
        if invitation is None:
            return None
        return IssuedInvitationDTO(invitation=invitation, token=token)

    def revoke(self, *, sphere_id: int, pk: int) -> bool:
        with self._transaction.atomic():
            return self._team.delete_open_invitation(
                sphere_id=sphere_id, pk=pk, now=datetime.now(tz=UTC)
            )

    def join_page(
        self, *, sphere_id: int, token: str, viewer_id: int | None
    ) -> JoinPageDTO:
        return JoinPageDTO(
            sphere_name=self._team.read_sphere_name(sphere_id=sphere_id),
            invitation=self._team.read_open_invitation(
                sphere_id=sphere_id,
                token_hash=token_hash(token),
                now=datetime.now(tz=UTC),
            ),
            member_role=(
                None
                if viewer_id is None
                else self._team.read_member_role(sphere_id=sphere_id, user_id=viewer_id)
            ),
        )

    def accept(
        self, *, sphere_id: int, token: str, user_id: int
    ) -> AcceptInvitationOutcome:
        now = datetime.now(tz=UTC)
        with self._transaction.atomic():
            if self._team.read_member_role(sphere_id=sphere_id, user_id=user_id):
                return AcceptInvitationOutcome.ALREADY_MEMBER
            # Locked, so two people opening one link at once cannot both join.
            invitation = self._team.lock_open_invitation(
                sphere_id=sphere_id, token_hash=token_hash(token), now=now
            )
            if invitation is None:
                return AcceptInvitationOutcome.INVALID
            if not self._team.add_member(
                sphere_id=sphere_id, user_id=user_id, role=invitation.role
            ):
                return AcceptInvitationOutcome.ALREADY_MEMBER
            self._team.mark_accepted(pk=invitation.pk, user_id=user_id, now=now)
            return AcceptInvitationOutcome.JOINED
