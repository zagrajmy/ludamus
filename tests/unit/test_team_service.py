from datetime import UTC, datetime, timedelta

from ludamus.mills import team as team_mills
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.team import (
    AcceptInvitationOutcome,
    InvitationPreviewDTO,
    JoinPageDTO,
    SphereInvitationDTO,
    TeamMemberDTO,
)
from tests.unit.factories import FakeTransaction

SPHERE_PK = 3
INVITER_PK = 5
NEWCOMER_PK = 8
INVITATION_PK = 13
MEMBER = TeamMemberDTO(
    user_id=INVITER_PK, name="Inviter", email=None, role=SphereRole.MANAGER
)
# secrets.token_urlsafe(32): 32 random bytes, base64-encoded without padding.
URLSAFE_32_BYTES_LENGTH = 43
HASH_OF_TOK = team_mills.token_hash("tok")


def _invitation(role=SphereRole.MANAGER):
    now = datetime.now(tz=UTC)
    return SphereInvitationDTO(
        pk=INVITATION_PK,
        role=role,
        note="",
        invited_by="Inviter",
        creation_time=now,
        expires_at=now + timedelta(days=7),
    )


class StubTeam:
    """Answers what a test configures and records what the service writes.

    The open-invitation rule (unaccepted, unexpired, this sphere) belongs to
    the repository and is tested there; here an invitation is open or not
    because the test says so.
    """

    def __init__(self, *, member_role=None, open_invitation=None, add_succeeds=True):
        self.member_role = member_role
        self.open_invitation = open_invitation
        self.add_succeeds = add_succeeds
        self.created = []
        self.added = []
        self.accepted = []
        self.clock = []

    @staticmethod
    def list_members(*, sphere_id):
        return [MEMBER] if sphere_id == SPHERE_PK else []

    def list_open_invitations(self, *, sphere_id, now):
        self.clock.append(now)
        return []

    def create_invitation(self, data):
        self.created.append(data)
        return _invitation(data["role"]).model_copy(
            update={"note": data["note"], "expires_at": data["expires_at"]}
        )

    def rotate_open_invitation(self, *, sphere_id, pk, rotation, now):
        self.clock.append(now)
        if self.open_invitation is None:
            return None
        self.created.append(rotation)
        return self.open_invitation.model_copy(
            update={"expires_at": rotation["expires_at"]}
        )

    def delete_open_invitation(self, *, sphere_id, pk, now):
        self.clock.append(now)
        return True

    @staticmethod
    def read_sphere_name(*, sphere_id):
        return f"Sphere {sphere_id}"

    def read_open_invitation(self, *, sphere_id, token_hash, now):
        if self.open_invitation is None:
            return None
        return InvitationPreviewDTO(
            role=self.open_invitation.role, invited_by="Inviter"
        )

    def lock_open_invitation(self, *, sphere_id, token_hash, now):
        # Only the digest of the link's token finds it.
        return self.open_invitation if token_hash == HASH_OF_TOK else None

    def read_member_role(self, *, sphere_id, user_id):
        return self.member_role

    def add_member(self, *, sphere_id, user_id, role):
        self.added.append((user_id, role))
        return self.add_succeeds

    def mark_accepted(self, *, pk, user_id, now):
        self.accepted.append((pk, user_id))


def _service(team):
    return team_mills.SphereTeamService(transaction=FakeTransaction(), team=team)


def _accept(service):
    return service.accept(sphere_id=SPHERE_PK, token="tok", user_id=NEWCOMER_PK)


class TestInvite:
    def test_each_link_gets_its_own_unguessable_token_and_a_weeks_life(self):
        team = StubTeam()
        service = _service(team)
        before = datetime.now(tz=UTC)

        first = service.invite(
            sphere_id=SPHERE_PK,
            role=SphereRole.COMMS,
            note="  Kasia, programme ",
            invited_by_id=INVITER_PK,
        )
        second = service.invite(
            sphere_id=SPHERE_PK, role=SphereRole.COMMS, note="", invited_by_id=1
        )

        assert first.token != second.token
        assert len(first.token) == URLSAFE_32_BYTES_LENGTH
        assert team.created[0]["token_hash"] == team_mills.token_hash(first.token)
        assert first.token not in team.created[0]["token_hash"]
        assert before + timedelta(days=7) <= first.invitation.expires_at
        assert first.invitation.expires_at <= datetime.now(tz=UTC) + timedelta(days=7)
        assert first.invitation.note == "Kasia, programme"
        assert team.created[0]["created_by_id"] == INVITER_PK


class TestReissue:
    def test_a_new_link_replaces_the_old_one_for_another_week(self):
        team = StubTeam(open_invitation=_invitation(SphereRole.COMMS))
        before = datetime.now(tz=UTC)

        issued = _service(team).reissue(
            sphere_id=SPHERE_PK, pk=INVITATION_PK, reissued_by_id=INVITER_PK
        )

        assert issued is not None
        assert issued.invitation.role is SphereRole.COMMS
        assert len(issued.token) == URLSAFE_32_BYTES_LENGTH
        rotation = team.created[0]
        assert rotation["token_hash"] == team_mills.token_hash(issued.token)
        assert rotation["created_by_id"] == INVITER_PK
        assert rotation["expires_at"] == rotation["creation_time"] + timedelta(days=7)
        assert before <= rotation["creation_time"] == team.clock[0]

    def test_an_invitation_no_longer_open_gets_no_link(self):
        team = StubTeam(open_invitation=None)

        issued = _service(team).reissue(
            sphere_id=SPHERE_PK, pk=INVITATION_PK, reissued_by_id=INVITER_PK
        )

        assert issued is None
        assert not team.created


class TestAccept:
    def test_a_newcomer_joins_with_the_invited_role_and_spends_the_link(self):
        team = StubTeam(open_invitation=_invitation(SphereRole.COMMS))

        outcome = _accept(_service(team))

        assert outcome is AcceptInvitationOutcome.JOINED
        assert team.added == [(NEWCOMER_PK, SphereRole.COMMS)]
        assert team.accepted == [(INVITATION_PK, NEWCOMER_PK)]

    def test_a_member_is_told_so_before_the_link_is_even_considered(self):
        # Their own spent link must not read as dead to them.
        team = StubTeam(member_role=SphereRole.COMMS, open_invitation=None)

        outcome = _accept(_service(team))

        assert outcome is AcceptInvitationOutcome.ALREADY_MEMBER
        assert not team.added
        assert not team.accepted

    def test_a_link_that_is_not_open_grants_nothing(self):
        team = StubTeam(open_invitation=None)

        outcome = _accept(_service(team))

        assert outcome is AcceptInvitationOutcome.INVALID
        assert not team.added

    def test_losing_the_race_to_a_second_link_leaves_this_one_unspent(self):
        team = StubTeam(open_invitation=_invitation(), add_succeeds=False)

        outcome = _accept(_service(team))

        assert outcome is AcceptInvitationOutcome.ALREADY_MEMBER
        assert not team.accepted


class TestJoinPage:
    def test_a_signed_out_viewer_is_offered_the_link_with_no_role_looked_up(self):
        team = StubTeam(member_role=SphereRole.MANAGER, open_invitation=_invitation())

        page = _service(team).join_page(
            sphere_id=SPHERE_PK, token="tok", viewer_id=None
        )

        assert page == JoinPageDTO(
            sphere_name=f"Sphere {SPHERE_PK}",
            invitation=InvitationPreviewDTO(
                role=SphereRole.MANAGER, invited_by="Inviter"
            ),
            member_role=None,
        )

    def test_a_signed_in_member_is_reported_as_one(self):
        team = StubTeam(member_role=SphereRole.COMMS)

        page = _service(team).join_page(
            sphere_id=SPHERE_PK, token="tok", viewer_id=NEWCOMER_PK
        )

        assert page.member_role is SphereRole.COMMS
        assert page.invitation is None


class TestOpenInvitationsAreJudgedNow:
    def test_listing_and_withdrawing_pass_the_current_time(self):
        team = StubTeam()
        service = _service(team)
        before = datetime.now(tz=UTC)

        assert service.list_members(sphere_id=SPHERE_PK) == [MEMBER]
        service.list_open_invitations(sphere_id=SPHERE_PK)
        service.revoke(sphere_id=SPHERE_PK, pk=INVITATION_PK)

        after = datetime.now(tz=UTC)
        assert len(team.clock) == len(("list", "revoke"))
        assert all(before <= moment <= after for moment in team.clock)
