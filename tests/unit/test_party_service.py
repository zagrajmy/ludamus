from contextlib import contextmanager

from ludamus.mills.party import PartyService
from ludamus.pacts.party import (
    DeletePartyOutcome,
    InvitedUserDTO,
    InviteOutcome,
    LedPartyDTO,
    PartiesOverviewDTO,
)

FRIEND_PK = 9


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
        self.calls = []

    def overview(self, viewer_pk):
        self.calls.append(("overview", viewer_pk))
        return PartiesOverviewDTO(parties=[], invites=[])

    def create(self, *, leader_pk, name):
        self.calls.append(("create", leader_pk, name))
        return 7

    def rename(self, *, leader_pk, party_pk, name):
        self.calls.append(("rename", leader_pk, party_pk, name))
        return True

    def has_companions(self, party_pk):
        self.calls.append(("has_companions", party_pk))
        return self.companions

    def delete(self, *, leader_pk, party_pk):
        self.calls.append(("delete", leader_pk, party_pk))
        return True

    def read_led_party(self, *, leader_pk, party_pk):
        self.calls.append(("read_led_party", leader_pk, party_pk))
        return self.lead

    def find_invitable_user(self, email):
        self.calls.append(("find_invitable_user", email))
        return self.user

    def membership_exists(self, *, party_pk, user_pk):
        self.calls.append(("membership_exists", party_pk, user_pk))
        return self.member_exists

    def create_invited_membership(self, *, party_pk, user_pk):
        self.calls.append(("create_invited_membership", party_pk, user_pk))

    def accept_invite(self, *, membership_pk, user_pk):
        self.calls.append(("accept_invite", membership_pk, user_pk))
        return True

    def decline_invite(self, *, membership_pk, user_pk):
        self.calls.append(("decline_invite", membership_pk, user_pk))
        return True

    def remove_member(self, *, leader_pk, party_pk, membership_pk):
        self.calls.append(("remove_member", leader_pk, party_pk, membership_pk))
        return True

    def leave(self, *, user_pk, party_pk):
        self.calls.append(("leave", user_pk, party_pk))
        return True


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify_party_invited(self, notification):
        self.sent.append(notification)


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
        parties = FakeParties()
        parties.delete = lambda **__: False

        outcome = _service(parties).delete(leader_pk=1, party_pk=2)

        assert outcome == DeletePartyOutcome.NOT_FOUND


class TestInvite:
    def test_invites_and_notifies(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena Leader"),
            user=InvitedUserDTO(pk=FRIEND_PK, email="f@e.com"),
        )
        notifier = FakeNotifier()

        outcome = _service(parties, notifier).invite(
            leader_pk=1, party_pk=2, email="f@e.com"
        )

        assert outcome == InviteOutcome.INVITED
        assert ("create_invited_membership", 2, FRIEND_PK) in parties.calls
        [notification] = notifier.sent
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
            leader_pk=1, party_pk=2, email="f@e.com"
        )

        assert outcome == InviteOutcome.NO_SUCH_USER
        assert notifier.sent == []

    def test_unknown_email(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena"), user=None
        )

        outcome = _service(parties).invite(leader_pk=1, party_pk=2, email="x@e.com")

        assert outcome == InviteOutcome.NO_SUCH_USER
        assert ("create_invited_membership", 2, FRIEND_PK) not in parties.calls

    def test_already_member(self):
        parties = FakeParties(
            lead=LedPartyDTO(name="Ekipa", leader_name="Lena"),
            user=InvitedUserDTO(pk=FRIEND_PK, email="f@e.com"),
            member_exists=True,
        )
        notifier = FakeNotifier()

        outcome = _service(parties, notifier).invite(
            leader_pk=1, party_pk=2, email="f@e.com"
        )

        assert outcome == InviteOutcome.ALREADY_MEMBER
        assert ("create_invited_membership", 2, FRIEND_PK) not in parties.calls
        assert notifier.sent == []
