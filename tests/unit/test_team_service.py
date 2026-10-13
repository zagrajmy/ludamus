from datetime import UTC, datetime, timedelta
from itertools import starmap

import pytest

from ludamus.mills.team import SphereTeamService
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.team import (
    AcceptInvitationOutcome,
    InvitationPreviewDTO,
    SphereInvitationDTO,
    TeamMemberDTO,
)
from tests.unit.factories import FakeTransaction

SPHERE_PK = 3
INVITER_PK = 5
NEWCOMER_PK = 8
# secrets.token_urlsafe(32): 32 random bytes, base64-encoded without padding.
URLSAFE_32_BYTES_LENGTH = 43


class FakeTeam:
    """An in-memory team: invitations are open while unaccepted and unexpired."""

    def __init__(self):
        self.invitations = {}
        self.accepted = {}
        self.members = {}

    def _open(self, *, sphere_id, now):
        return [
            (pk, data)
            for pk, data in self.invitations.items()
            if data["sphere_id"] == sphere_id
            and pk not in self.accepted
            and data["expires_at"] > now
        ]

    @staticmethod
    def _dto(pk, data):
        return SphereInvitationDTO(
            pk=pk,
            role=data["role"],
            token=data["token"],
            invited_by="Inviter",
            creation_time=data["expires_at"] - timedelta(days=7),
            expires_at=data["expires_at"],
        )

    def list_members(self, *, sphere_id):
        return [
            TeamMemberDTO(user_id=user_id, name="Member", email=None, role=role)
            for (sphere, user_id), role in self.members.items()
            if sphere == sphere_id
        ]

    def list_open_invitations(self, *, sphere_id, now):
        return list(starmap(self._dto, self._open(sphere_id=sphere_id, now=now)))

    def create_invitation(self, data):
        pk = len(self.invitations) + 1
        self.invitations[pk] = data
        return self._dto(pk, data)

    def delete_open_invitation(self, *, sphere_id, pk, now):
        if pk not in dict(self._open(sphere_id=sphere_id, now=now)):
            return False
        del self.invitations[pk]
        return True

    def lock_open_invitation(self, *, sphere_id, token, now):
        found = [
            self._dto(pk, data)
            for pk, data in self._open(sphere_id=sphere_id, now=now)
            if data["token"] == token
        ]
        return found[0] if found else None

    def read_open_invitation(self, *, sphere_id, token, now):
        invitation = self.lock_open_invitation(
            sphere_id=sphere_id, token=token, now=now
        )
        if invitation is None:
            return None
        return InvitationPreviewDTO(
            sphere_name="Sphere", role=invitation.role, invited_by="Inviter"
        )

    def is_member(self, *, sphere_id, user_id):
        return (sphere_id, user_id) in self.members

    def add_member(self, *, sphere_id, user_id, role):
        self.members[sphere_id, user_id] = role

    def mark_accepted(self, *, pk, user_id, now):
        self.accepted[pk] = (user_id, now)


def _service(team):
    return SphereTeamService(transaction=FakeTransaction(), team=team)


def _invite(service, role=SphereRole.COMMS):
    return service.invite(sphere_id=SPHERE_PK, role=role, invited_by_id=INVITER_PK)


class TestInvite:
    def test_each_link_is_its_own_unguessable_week_long_token(self):
        team = FakeTeam()
        service = _service(team)
        before = datetime.now(tz=UTC)

        first = _invite(service)
        second = _invite(service)

        assert first.token != second.token
        assert len(first.token) == URLSAFE_32_BYTES_LENGTH
        assert before + timedelta(days=7) <= first.expires_at
        assert first.expires_at <= datetime.now(tz=UTC) + timedelta(days=7)
        assert team.invitations[first.pk]["created_by_id"] == INVITER_PK
        assert service.list_open_invitations(sphere_id=SPHERE_PK) == [first, second]


class TestRevoke:
    def test_revokes_an_open_link_once(self):
        team = FakeTeam()
        service = _service(team)
        invitation = _invite(service)

        assert service.revoke(sphere_id=SPHERE_PK, pk=invitation.pk) is True
        assert service.revoke(sphere_id=SPHERE_PK, pk=invitation.pk) is False
        assert service.preview(sphere_id=SPHERE_PK, token=invitation.token) is None


class TestAccept:
    def test_a_newcomer_joins_with_the_invited_role_and_spends_the_link(self):
        team = FakeTeam()
        service = _service(team)
        invitation = _invite(service, role=SphereRole.MANAGER)

        outcome = service.accept(
            sphere_id=SPHERE_PK, token=invitation.token, user_id=NEWCOMER_PK
        )

        assert outcome is AcceptInvitationOutcome.JOINED
        assert service.list_members(sphere_id=SPHERE_PK) == [
            TeamMemberDTO(
                user_id=NEWCOMER_PK, name="Member", email=None, role=SphereRole.MANAGER
            )
        ]
        again = service.accept(
            sphere_id=SPHERE_PK, token=invitation.token, user_id=NEWCOMER_PK + 1
        )
        assert again is AcceptInvitationOutcome.INVALID

    def test_a_member_leaves_the_link_for_its_intended_person(self):
        team = FakeTeam()
        team.add_member(sphere_id=SPHERE_PK, user_id=NEWCOMER_PK, role=SphereRole.COMMS)
        service = _service(team)
        invitation = _invite(service, role=SphereRole.MANAGER)

        outcome = service.accept(
            sphere_id=SPHERE_PK, token=invitation.token, user_id=NEWCOMER_PK
        )

        assert outcome is AcceptInvitationOutcome.ALREADY_MEMBER
        assert team.members[SPHERE_PK, NEWCOMER_PK] is SphereRole.COMMS
        assert service.preview(sphere_id=SPHERE_PK, token=invitation.token) == (
            InvitationPreviewDTO(
                sphere_name="Sphere", role=SphereRole.MANAGER, invited_by="Inviter"
            )
        )

    @pytest.mark.parametrize(
        ("sphere_offset", "token"),
        ((0, "nope"), (1, None)),
        ids=("unknown-token", "other-sphere"),
    )
    def test_an_unknown_or_other_spheres_token_grants_nothing(
        self, sphere_offset, token
    ):
        team = FakeTeam()
        service = _service(team)
        invitation = _invite(service)

        outcome = service.accept(
            sphere_id=SPHERE_PK + sphere_offset,
            token=token or invitation.token,
            user_id=NEWCOMER_PK,
        )

        assert outcome is AcceptInvitationOutcome.INVALID
        assert not team.members
