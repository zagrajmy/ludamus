from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ludamus.mills.party import PartyService
from ludamus.pacts.crowd import CompanionDTO, UserType
from ludamus.pacts.party import (
    ENROLL_WITHOUT_PARTY,
    CompanionAddOutcome,
    DeletePartyOutcome,
    EnrollmentPartyChoiceDTO,
    EnrollmentPartyMemberDTO,
    InvitablePartyDTO,
    InvitedUserDTO,
    InviteOutcome,
    PartiesOverviewDTO,
    PartyActionContextDTO,
    PartyConsentMode,
    PartyDTO,
    PartyEnrolledNotification,
    PartyInviteNotification,
    PartyJoinResult,
    PartyMemberDTO,
    PartyMembershipStatus,
)
from tests.unit.factories import FakeTransaction

VIEWER_PK = 1
FOREIGN_LEADER_PK = 99
OWN_PARTY_PK = 7
FOREIGN_PARTY_PK = 8
INVITEE_PK = 5
MEMBERSHIP_PK = 50
_TOKEN_LENGTH = 43


class FakeParties:
    def __init__(self, *, lead=None):
        self.lead = lead
        self.parties = []
        self.companion_dtos = []
        self.memberships = []
        self.invitable = []
        self.state = SimpleNamespace(
            members={(OWN_PARTY_PK, VIEWER_PK)},
            names={OWN_PARTY_PK: "Ekipa"},
            invite_token="",
            pending={MEMBERSHIP_PK: INVITEE_PK},
            consent={},
        )

    def overview(self, viewer_pk):
        return PartiesOverviewDTO(
            parties={VIEWER_PK: self.parties}[viewer_pk], invites=[]
        )

    def owned_companions(self, *, manager_pk):
        assert manager_pk == VIEWER_PK
        return self.companion_dtos

    def lock_owned_companions(self, *, manager_pk):
        assert manager_pk == VIEWER_PK
        return self.companion_dtos

    def read_active_member_party(self, *, member_pk, party_pk):
        if (member_pk, party_pk) == (VIEWER_PK, OWN_PARTY_PK):
            return self.lead
        return None

    def get_or_create_membership(self, **kwargs):
        if (key := (kwargs["party_pk"], kwargs["user_pk"])) in self.state.members:
            return False
        self.state.members.add(key)
        self.memberships.append(kwargs)
        return True

    def find_invitable_users(self, identifier):
        return [user for user in self.invitable if identifier in user.email]

    def create(self, *, leader_pk, name):
        assert leader_pk == VIEWER_PK
        pk = max(self.state.names, default=0) + 1
        self.state.names[pk] = name
        return pk

    def rename(self, *, leader_pk, party_pk, name):
        if leader_pk != VIEWER_PK or party_pk not in self.state.names:
            return False
        self.state.names[party_pk] = name
        return True

    def delete(self, *, leader_pk, party_pk):
        if leader_pk != VIEWER_PK or party_pk not in self.state.names:
            return False
        del self.state.names[party_pk]
        return True

    def set_invite_token(self, *, leader_pk, party_pk, token):
        if leader_pk != VIEWER_PK or party_pk not in self.state.names:
            return False
        self.state.invite_token = token
        return True

    def read_invite_token(self, *, leader_pk, party_pk):
        assert (leader_pk, party_pk) == (VIEWER_PK, OWN_PARTY_PK)
        return self.state.invite_token

    def read_party_by_invite_token(self, *, token, viewer_pk):
        if token != self.state.invite_token:
            return None
        return InvitablePartyDTO(
            pk=OWN_PARTY_PK,
            name=self.state.names[OWN_PARTY_PK],
            leader_name="Lena",
            already_member=(OWN_PARTY_PK, viewer_pk) in self.state.members,
        )

    def join_via_token(self, *, token, user_pk):
        if token != self.state.invite_token:
            return None
        joined = (OWN_PARTY_PK, user_pk) not in self.state.members
        self.state.members.add((OWN_PARTY_PK, user_pk))
        return PartyJoinResult(party_pk=OWN_PARTY_PK, joined=joined)

    def accept_invite(self, *, membership_pk, user_pk):
        if self.state.pending.get(membership_pk) != user_pk:
            return False
        del self.state.pending[membership_pk]
        self.state.members.add((OWN_PARTY_PK, user_pk))
        return True

    def decline_invite(self, *, membership_pk, user_pk):
        if self.state.pending.get(membership_pk) != user_pk:
            return False
        del self.state.pending[membership_pk]
        return True

    def remove_member(self, *, leader_pk, party_pk, membership_pk):
        if leader_pk != VIEWER_PK or party_pk != OWN_PARTY_PK:
            return None
        del self.state.pending[membership_pk]
        return PartyMembershipStatus.INVITED

    def leave(self, *, user_pk, party_pk):
        try:
            self.state.members.remove((party_pk, user_pk))
        except KeyError:
            return False
        return True

    def set_consent(self, *, user_pk, party_pk, mode):
        if (party_pk, user_pk) not in self.state.members:
            return False
        self.state.consent[party_pk, user_pk] = mode
        return True


class FakeNotifier:
    def __init__(self):
        self.invited = []
        self.enrolled = []

    def notify_party_invited(self, notification):
        self.invited.append(notification)

    def notify_party_enrolled(self, notification):
        self.enrolled.append(notification)


def _service(parties, notifier=None):
    return PartyService(FakeTransaction(), parties, notifier or FakeNotifier())


def _lead():
    return PartyActionContextDTO(name="Ekipa", actor_name="Lena")


def _invitee(pk=INVITEE_PK, email="ann@example.com"):
    return InvitedUserDTO(pk=pk, email=email)


class TestCrud:
    def test_overview_passes_through(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]

        assert _service(parties).overview(VIEWER_PK) == PartiesOverviewDTO(
            parties=parties.parties, invites=[]
        )

    def test_create_returns_the_new_pk(self):
        parties = FakeParties()

        pk = _service(parties).create(leader_pk=VIEWER_PK, name="Nowa")

        assert parties.state.names[pk] == "Nowa"

    def test_rename_only_own_party(self):
        parties = FakeParties()
        service = _service(parties)

        assert service.rename(leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, name="X")
        assert not service.rename(
            leader_pk=FOREIGN_LEADER_PK, party_pk=OWN_PARTY_PK, name="Y"
        )
        assert parties.state.names[OWN_PARTY_PK] == "X"

    def test_delete_outcomes(self):
        parties = FakeParties()
        service = _service(parties)

        assert service.delete(leader_pk=FOREIGN_LEADER_PK, party_pk=OWN_PARTY_PK) == (
            DeletePartyOutcome.NOT_FOUND
        )
        assert service.delete(leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK) == (
            DeletePartyOutcome.DELETED
        )
        assert not parties.state.names


class TestInvite:
    @staticmethod
    def _invite(parties, notifier=None, identifier="ann"):
        return _service(parties, notifier).invite(
            member_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, identifier=identifier
        )

    def test_non_member_cannot_invite(self):
        parties = FakeParties()
        parties.invitable = [_invitee()]

        assert self._invite(parties) == InviteOutcome.NO_SUCH_USER
        assert not parties.memberships

    def test_unknown_handle(self):
        assert self._invite(FakeParties(lead=_lead())) == InviteOutcome.NO_SUCH_USER

    def test_ambiguous_handle(self):
        parties = FakeParties(lead=_lead())
        parties.invitable = [_invitee(), _invitee(pk=6, email="ann2@example.com")]

        assert self._invite(parties) == InviteOutcome.AMBIGUOUS_HANDLE
        assert not parties.memberships

    def test_already_a_member_is_not_notified(self):
        parties = FakeParties(lead=_lead())
        parties.invitable = [_invitee()]
        parties.state.members.add((OWN_PARTY_PK, INVITEE_PK))
        notifier = FakeNotifier()

        assert self._invite(parties, notifier) == InviteOutcome.ALREADY_MEMBER
        assert not notifier.invited

    def test_invited_and_notified(self):
        parties = FakeParties(lead=_lead())
        parties.invitable = [_invitee()]
        notifier = FakeNotifier()

        assert self._invite(parties, notifier) == InviteOutcome.INVITED
        assert parties.memberships == [
            {"party_pk": OWN_PARTY_PK, "user_pk": INVITEE_PK}
        ]
        assert notifier.invited == [
            PartyInviteNotification(
                recipient_user_id=INVITEE_PK,
                recipient_email="ann@example.com",
                party_name="Ekipa",
                actor_name="Lena",
            )
        ]


class TestAddCompanion:
    @staticmethod
    def _add(parties, display_name="Kid", party_pk=OWN_PARTY_PK):
        return _service(parties).add_companion(
            member_pk=VIEWER_PK, party_pk=party_pk, display_name=display_name
        )

    def test_ambiguous_name(self):
        parties = FakeParties(lead=_lead())
        parties.companion_dtos = [_companion_dto(), _companion_dto()]

        outcome = self._add(parties)

        assert outcome == CompanionAddOutcome.AMBIGUOUS_NAME
        assert not parties.memberships

    def test_non_member_cannot_add(self):
        parties = FakeParties(lead=_lead())
        parties.companion_dtos = [_companion_dto()]

        assert self._add(parties, party_pk=FOREIGN_PARTY_PK) == (
            CompanionAddOutcome.NO_SUCH_COMPANION
        )

    def test_unknown_name(self):
        parties = FakeParties(lead=_lead())
        parties.companion_dtos = [_companion_dto()]

        assert self._add(parties, "Stranger") == CompanionAddOutcome.NO_SUCH_COMPANION

    def test_already_a_member(self):
        parties = FakeParties(lead=_lead())
        parties.companion_dtos = [_companion_dto()]
        parties.state.members.add((OWN_PARTY_PK, _companion_dto().pk))

        assert self._add(parties) == CompanionAddOutcome.ALREADY_MEMBER

    def test_added_active_by_default_matching_name_case_insensitively(self):
        parties = FakeParties(lead=_lead())
        parties.companion_dtos = [_companion_dto()]

        assert self._add(parties, "  kID ") == CompanionAddOutcome.ADDED
        assert parties.memberships == [
            {
                "party_pk": OWN_PARTY_PK,
                "user_pk": _companion_dto().pk,
                "consent_mode": PartyConsentMode.ACCEPT_BY_DEFAULT,
                "status": PartyMembershipStatus.ACTIVE,
            }
        ]


class TestInviteLink:
    def test_reset_issues_a_fresh_token_for_own_party(self):
        parties = FakeParties()
        service = _service(parties)

        token = service.reset_invite_link(leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK)

        assert token is not None
        assert len(token) == _TOKEN_LENGTH
        assert service.read_invite_token(
            leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK
        ) == (token)

    def test_reset_refused_for_a_foreign_party(self):
        parties = FakeParties()

        assert (
            _service(parties).reset_invite_link(
                leader_pk=FOREIGN_LEADER_PK, party_pk=OWN_PARTY_PK
            )
            is None
        )
        assert not parties.state.invite_token

    def test_read_invitable_party_by_token(self):
        parties = FakeParties()
        parties.state.invite_token = "tok"
        service = _service(parties)

        assert service.read_invitable_party(token="tok", viewer_pk=INVITEE_PK) == (
            InvitablePartyDTO(
                pk=OWN_PARTY_PK, name="Ekipa", leader_name="Lena", already_member=False
            )
        )
        assert service.read_invitable_party(token="tok", viewer_pk=VIEWER_PK) == (
            InvitablePartyDTO(
                pk=OWN_PARTY_PK, name="Ekipa", leader_name="Lena", already_member=True
            )
        )
        assert service.read_invitable_party(token="nope", viewer_pk=INVITEE_PK) is None

    def test_join_via_link(self):
        parties = FakeParties()
        parties.state.invite_token = "tok"
        service = _service(parties)

        assert service.join_via_link(
            token="tok", user_pk=INVITEE_PK
        ) == PartyJoinResult(party_pk=OWN_PARTY_PK, joined=True)
        assert service.join_via_link(
            token="tok", user_pk=INVITEE_PK
        ) == PartyJoinResult(party_pk=OWN_PARTY_PK, joined=False)
        assert service.join_via_link(token="nope", user_pk=INVITEE_PK) is None
        assert parties.state.members == {
            (OWN_PARTY_PK, VIEWER_PK),
            (OWN_PARTY_PK, INVITEE_PK),
        }


class TestMembership:
    @pytest.mark.parametrize("action", ("accept_invite", "decline_invite"))
    def test_invite_answer_only_by_its_recipient(self, action):
        parties = FakeParties()
        service = _service(parties)

        assert (
            getattr(service, action)(user_pk=VIEWER_PK, membership_pk=MEMBERSHIP_PK)
            is False
        )
        assert (
            getattr(service, action)(user_pk=INVITEE_PK, membership_pk=MEMBERSHIP_PK)
            is True
        )
        assert not parties.state.pending

    def test_remove_member_reports_the_removed_status(self):
        parties = FakeParties()
        service = _service(parties)

        assert (
            service.remove_member(
                leader_pk=FOREIGN_LEADER_PK,
                party_pk=OWN_PARTY_PK,
                membership_pk=MEMBERSHIP_PK,
            )
            is None
        )
        assert (
            service.remove_member(
                leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, membership_pk=MEMBERSHIP_PK
            )
            == PartyMembershipStatus.INVITED
        )

    def test_leave(self):
        parties = FakeParties()
        service = _service(parties)

        assert service.leave(user_pk=VIEWER_PK, party_pk=OWN_PARTY_PK) is True
        assert service.leave(user_pk=VIEWER_PK, party_pk=OWN_PARTY_PK) is False
        assert parties.state.members == set()

    def test_set_my_consent_only_as_a_member(self):
        parties = FakeParties()
        service = _service(parties)

        assert (
            service.set_my_consent(
                user_pk=VIEWER_PK,
                party_pk=OWN_PARTY_PK,
                mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
            )
            is True
        )
        assert (
            service.set_my_consent(
                user_pk=INVITEE_PK,
                party_pk=OWN_PARTY_PK,
                mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
            )
            is False
        )
        assert parties.state.consent == {
            (OWN_PARTY_PK, VIEWER_PK): PartyConsentMode.ACCEPT_BY_DEFAULT
        }

    def test_announce_member_enrolled_reaches_the_notifier(self):
        notifier = FakeNotifier()
        notification = PartyEnrolledNotification(
            recipient_user_id=INVITEE_PK,
            recipient_email="ann@example.com",
            actor_name="Lena",
            session_id=3,
            session_title="Game",
            event_slug="con",
        )

        _service(FakeParties(), notifier).announce_member_enrolled(notification)

        assert notifier.enrolled == [notification]


def _member(user_pk, *, is_leader=False):
    return PartyMemberDTO(
        membership_pk=user_pk * 10,
        user_pk=user_pk,
        name=f"user-{user_pk}",
        full_name=f"user-{user_pk}",
        username=f"user-{user_pk}",
        slug=f"user-{user_pk}",
        is_login_less=False,
        is_leader=is_leader,
        consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
        status=PartyMembershipStatus.ACTIVE,
        claim_token="bearer-secret",
    )


def _party(pk, *, is_leader=False, members=()):
    return PartyDTO(
        pk=pk,
        name="",
        leader_pk=VIEWER_PK if is_leader else FOREIGN_LEADER_PK,
        leader_name="Lena Leader",
        is_leader=is_leader,
        is_active_member=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        members=list(members),
    )


def _companion_dto():
    return CompanionDTO(
        avatar_url="",
        date_joined=datetime(2026, 1, 1, tzinfo=UTC),
        discord_username="",
        email="",
        full_name="Kid",
        is_active=True,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name="Kid",
        pk=3,
        slug="kid",
        use_gravatar=False,
        user_type=UserType.CONNECTED,
        username="kid",
    )


def _choice(pk, *, is_own_led):
    return EnrollmentPartyChoiceDTO(
        pk=pk, name="", leader_name="Lena Leader", is_own_led=is_own_led
    )


class TestEnrollmentSelection:
    @staticmethod
    def _select(parties, requested_party):
        return _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=requested_party
        )

    def test_garbage_request_is_flagged_invalid(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]

        selection = self._select(parties, "ekipa")

        assert selection.requested_invalid

    def test_selected_members_carry_no_claim_token(self):
        parties = FakeParties()
        parties.parties = [
            _party(
                OWN_PARTY_PK,
                is_leader=True,
                members=[_member(VIEWER_PK, is_leader=True)],
            )
        ]

        selection = self._select(parties, str(OWN_PARTY_PK))

        assert selection.selected is not None
        assert selection.selected.members == [
            EnrollmentPartyMemberDTO(
                user_pk=VIEWER_PK,
                name=f"user-{VIEWER_PK}",
                slug=f"user-{VIEWER_PK}",
                is_login_less=False,
                is_leader=True,
                consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
                status=PartyMembershipStatus.ACTIVE,
            )
        ]

    def test_just_myself_keeps_own_companions(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]
        parties.companion_dtos = [_companion_dto()]

        selection = self._select(parties, ENROLL_WITHOUT_PARTY)

        assert selection.selected is None
        assert selection.choices == [_choice(OWN_PARTY_PK, is_own_led=True)]
        assert selection.companions == [_companion_dto()]
        assert not selection.requested_invalid

    def test_default_prefers_own_led_party(self):
        parties = FakeParties()
        parties.parties = [
            _party(FOREIGN_PARTY_PK),
            _party(OWN_PARTY_PK, is_leader=True),
        ]
        parties.companion_dtos = [_companion_dto()]

        selection = self._select(parties, None)

        assert selection.selected is not None
        assert selection.selected.pk == OWN_PARTY_PK
        assert selection.companions == [_companion_dto()]

    def test_default_falls_back_to_first_party_and_drops_companions(self):
        parties = FakeParties()
        parties.parties = [_party(FOREIGN_PARTY_PK)]
        parties.companion_dtos = [_companion_dto()]

        selection = self._select(parties, None)

        assert selection.selected is not None
        assert selection.selected.pk == FOREIGN_PARTY_PK
        assert not selection.companions

    def test_no_parties_at_all(self):
        parties = FakeParties()
        parties.companion_dtos = [_companion_dto()]

        selection = self._select(parties, None)

        assert selection.choices == []
        assert selection.selected is None
        assert selection.companions == [_companion_dto()]
