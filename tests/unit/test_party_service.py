from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.party import PartyService
from ludamus.pacts.crowd import ConnectedUserDTO, UserType
from ludamus.pacts.party import (
    CompanionAddOutcome,
    DeletePartyOutcome,
    EnrollmentPartyChoiceDTO,
    EnrollmentPartyMemberDTO,
    InvitedUserDTO,
    InviteOutcome,
    LedPartyDTO,
    PartiesOverviewDTO,
    PartyConsentMode,
    PartyDTO,
    PartyMemberDTO,
    PartyMembershipStatus,
)

FRIEND_PK = 9
VIEWER_PK = 1
FOREIGN_LEADER_PK = 99
OWN_PARTY_PK = 7
FOREIGN_PARTY_PK = 4


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


class FakeParties:
    def __init__(self, *, lead=None, user=None, member_exists=False):
        self.lead = lead
        self.user = user
        self.member_exists = member_exists
        self.companions = False
        self.parties = []
        self.companion_dtos = []
        self.calls = []

    def overview(self, viewer_pk):
        self.calls.append(("overview", viewer_pk))
        return PartiesOverviewDTO(parties=self.parties, invites=[])

    def led_party_companions(self, *, leader_pk, party_pk):
        self.calls.append(("led_party_companions", leader_pk, party_pk))
        return self.companion_dtos

    def create(self, *, leader_pk, name):
        self.calls.append(("create", leader_pk, name))
        return 7

    def rename(self, *, leader_pk, party_pk, name):
        self.calls.append(("rename", leader_pk, party_pk, name))
        return True

    def has_companions(self, *, leader_pk, party_pk):
        self.calls.append(("has_companions", leader_pk, party_pk))
        return self.companions

    def delete(self, *, leader_pk, party_pk):
        self.calls.append(("delete", leader_pk, party_pk))
        return True

    def read_led_party(self, *, leader_pk, party_pk):
        self.calls.append(("read_led_party", leader_pk, party_pk))
        return self.lead

    def find_invitable_users(self, identifier):
        self.calls.append(("find_invitable_users", identifier))
        if self.user is None:
            return []
        return self.user if isinstance(self.user, list) else [self.user]

    def membership_exists(self, *, party_pk, user_pk):
        self.calls.append(("membership_exists", party_pk, user_pk))
        return self.member_exists

    def create_invited_membership(
        self,
        *,
        party_pk,
        user_pk,
        consent_mode=PartyConsentMode.ACCEPT_INVITES,
        status=PartyMembershipStatus.INVITED,
    ):
        if (
            consent_mode == PartyConsentMode.ACCEPT_INVITES
            and status == PartyMembershipStatus.INVITED
        ):
            self.calls.append(("create_invited_membership", party_pk, user_pk))
        else:
            self.calls.append(
                ("create_invited_membership", party_pk, user_pk, consent_mode, status)
            )

    def accept_invite(self, *, membership_pk, user_pk):
        self.calls.append(("accept_invite", membership_pk, user_pk))
        return True

    def decline_invite(self, *, membership_pk, user_pk):
        self.calls.append(("decline_invite", membership_pk, user_pk))
        return True

    def remove_member(self, *, leader_pk, party_pk, membership_pk):
        self.calls.append(("remove_member", leader_pk, party_pk, membership_pk))
        return PartyMembershipStatus.ACTIVE

    def leave(self, *, user_pk, party_pk):
        self.calls.append(("leave", user_pk, party_pk))
        return True


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify_party_invited(self, notification):
        self.sent.append(notification)


class _DeletesNothing(FakeParties):
    def delete(self, *, leader_pk, party_pk):
        self.calls.append(("delete", leader_pk, party_pk))
        return False


def _service(parties, notifier=None):
    return PartyService(FakeTransaction(), parties, notifier or FakeNotifier())


class TestDelete:
    def test_refuses_party_with_companions(self):
        parties = FakeParties()
        parties.companions = True

        outcome = _service(parties).delete(leader_pk=1, party_pk=2)

        assert outcome == DeletePartyOutcome.HAS_COMPANIONS
        assert ("delete", 1, 2) not in parties.calls

    def test_deletes_empty_party(self):
        parties = FakeParties()

        outcome = _service(parties).delete(leader_pk=1, party_pk=2)

        assert outcome == DeletePartyOutcome.DELETED
        assert ("delete", 1, 2) in parties.calls

    def test_not_found_when_repo_deletes_nothing(self):
        outcome = _service(_DeletesNothing()).delete(leader_pk=1, party_pk=2)

        assert outcome == DeletePartyOutcome.NOT_FOUND


class TestInvite:
    def test_invites_and_notifies(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena Leader"),
            user=InvitedUserDTO(pk=FRIEND_PK, email="f@e.com"),
        )
        notifier = FakeNotifier()

        outcome = _service(parties, notifier).invite(
            leader_pk=1, party_pk=2, identifier="f@e.com"
        )

        assert outcome == InviteOutcome.INVITED
        assert ("create_invited_membership", 2, FRIEND_PK) in parties.calls
        assert len(notifier.sent) == 1
        notification = notifier.sent[0]
        assert notification.recipient_user_id == FRIEND_PK
        assert notification.recipient_email == "f@e.com"
        assert notification.party_name == "Ekipa"
        assert notification.leader_name == "Lena Leader"

    def test_foreign_party_reads_as_no_user(self):
        parties = FakeParties(
            lead=None, user=InvitedUserDTO(pk=FRIEND_PK, email="f@e.com")
        )
        notifier = FakeNotifier()

        outcome = _service(parties, notifier).invite(
            leader_pk=1, party_pk=2, identifier="f@e.com"
        )

        assert outcome == InviteOutcome.NO_SUCH_USER
        assert not notifier.sent

    def test_unknown_email(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena"), user=None
        )

        outcome = _service(parties).invite(
            leader_pk=1, party_pk=2, identifier="x@e.com"
        )

        assert outcome == InviteOutcome.NO_SUCH_USER
        assert ("create_invited_membership", 2, FRIEND_PK) not in parties.calls

    def test_ambiguous_handle(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena"),
            user=[
                InvitedUserDTO(pk=FRIEND_PK, email="f@e.com"),
                InvitedUserDTO(pk=FRIEND_PK + 1, email="g@e.com"),
            ],
        )

        outcome = _service(parties).invite(leader_pk=1, party_pk=2, identifier="ziggy")

        assert outcome == InviteOutcome.AMBIGUOUS_HANDLE
        assert ("create_invited_membership", 2, FRIEND_PK) not in parties.calls

    def test_already_member(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena"),
            user=InvitedUserDTO(pk=FRIEND_PK, email="f@e.com"),
            member_exists=True,
        )
        notifier = FakeNotifier()

        outcome = _service(parties, notifier).invite(
            leader_pk=1, party_pk=2, identifier="f@e.com"
        )

        assert outcome == InviteOutcome.ALREADY_MEMBER
        assert ("create_invited_membership", 2, FRIEND_PK) not in parties.calls
        assert not notifier.sent


class TestAddCompanion:
    def test_adds_owned_companion(self):
        parties = FakeParties(lead=LedPartyDTO(name="Ekipa", leader_name="Lena"))
        parties.companion_dtos = [_companion_dto()]

        outcome = _service(parties).add_companion(
            leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, display_name=" Kid "
        )

        assert outcome == CompanionAddOutcome.ADDED
        assert (
            "create_invited_membership",
            OWN_PARTY_PK,
            3,
            PartyConsentMode.ACCEPT_BY_DEFAULT,
            PartyMembershipStatus.ACTIVE,
        ) in parties.calls

    def test_unknown_companion(self):
        parties = FakeParties(lead=LedPartyDTO(name="Ekipa", leader_name="Lena"))

        outcome = _service(parties).add_companion(
            leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, display_name="Nobody"
        )

        assert outcome == CompanionAddOutcome.NO_SUCH_COMPANION

    def test_ambiguous_name(self):
        parties = FakeParties(lead=LedPartyDTO(name="Ekipa", leader_name="Lena"))
        parties.companion_dtos = [_companion_dto(), _companion_dto()]

        outcome = _service(parties).add_companion(
            leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, display_name="Kid"
        )

        assert outcome == CompanionAddOutcome.AMBIGUOUS_NAME
        assert not any(call[0] == "create_invited_membership" for call in parties.calls)

    def test_already_member(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena"), member_exists=True
        )
        parties.companion_dtos = [_companion_dto()]

        outcome = _service(parties).add_companion(
            leader_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, display_name="Kid"
        )

        assert outcome == CompanionAddOutcome.ALREADY_MEMBER


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


def _party(pk, *, name="", is_leader=False, leader_name="Lena Leader", members=()):
    return PartyDTO(
        pk=pk,
        name=name,
        leader_pk=VIEWER_PK if is_leader else FOREIGN_LEADER_PK,
        leader_name=leader_name,
        is_leader=is_leader,
        is_default=is_leader,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        members=list(members),
    )


def _companion_dto():
    return ConnectedUserDTO(
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


class TestEnrollmentSelection:
    def test_no_parties_yields_empty_selection(self):
        parties = FakeParties()

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=None
        )

        assert not selection.choices
        assert selection.selected is None
        assert not selection.companions
        assert not selection.requested_invalid

    def test_defaults_to_own_led_party(self):
        parties = FakeParties()
        parties.parties = [
            _party(FOREIGN_PARTY_PK, name="Foreign", leader_name="Frida Friend"),
            _party(
                OWN_PARTY_PK,
                is_leader=True,
                members=[_member(VIEWER_PK, is_leader=True)],
            ),
        ]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=None
        )

        assert selection.selected is not None
        assert selection.selected.pk == OWN_PARTY_PK
        assert selection.selected.is_own_led

    def test_defaults_to_first_party_when_none_led(self):
        parties = FakeParties()
        parties.parties = [
            _party(FOREIGN_PARTY_PK, name="Foreign"),
            _party(FOREIGN_PARTY_PK + 1, name="Other"),
        ]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=None
        )

        assert selection.selected is not None
        assert selection.selected.pk == FOREIGN_PARTY_PK
        assert not selection.selected.is_own_led

    def test_just_myself_selects_no_party(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]
        parties.companion_dtos = [_companion_dto()]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party="none"
        )

        assert selection.selected is None
        assert not selection.companions
        assert not selection.requested_invalid
        assert selection.choices == [
            EnrollmentPartyChoiceDTO(
                pk=OWN_PARTY_PK, name="", leader_name="Lena Leader", is_own_led=True
            )
        ]

    def test_unknown_party_is_flagged_invalid(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party="123"
        )

        assert selection.requested_invalid
        assert selection.selected is None
        assert not selection.companions

    def test_garbage_request_is_flagged_invalid(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party="ekipa"
        )

        assert selection.requested_invalid

    def test_own_led_party_returns_companions(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]
        parties.companion_dtos = [_companion_dto()]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=str(OWN_PARTY_PK)
        )

        assert selection.companions == [_companion_dto()]
        assert ("led_party_companions", VIEWER_PK, OWN_PARTY_PK) in parties.calls

    def test_foreign_party_has_no_companions(self):
        parties = FakeParties()
        parties.parties = [
            _party(FOREIGN_PARTY_PK, name="Foreign"),
            _party(OWN_PARTY_PK, is_leader=True),
        ]
        parties.companion_dtos = [_companion_dto()]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=str(FOREIGN_PARTY_PK)
        )

        assert selection.selected is not None
        assert selection.selected.pk == FOREIGN_PARTY_PK
        assert not selection.companions
        assert (
            "led_party_companions",
            VIEWER_PK,
            FOREIGN_PARTY_PK,
        ) not in parties.calls

    def test_selected_members_carry_no_claim_token(self):
        parties = FakeParties()
        parties.parties = [
            _party(
                OWN_PARTY_PK,
                is_leader=True,
                members=[_member(VIEWER_PK, is_leader=True)],
            )
        ]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party=str(OWN_PARTY_PK)
        )

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
