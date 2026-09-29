from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.party import PartyService
from ludamus.pacts.crowd import CompanionDTO, UserType
from ludamus.pacts.party import (
    CompanionAddOutcome,
    EnrollmentPartyMemberDTO,
    PartiesOverviewDTO,
    PartyActionContextDTO,
    PartyConsentMode,
    PartyDTO,
    PartyMemberDTO,
    PartyMembershipStatus,
)

VIEWER_PK = 1
FOREIGN_LEADER_PK = 99
OWN_PARTY_PK = 7


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


class FakeParties:
    def __init__(self, *, lead=None):
        self.lead = lead
        self.parties = []
        self.companion_dtos = []
        self.memberships = []

    def overview(self, _viewer_pk):
        return PartiesOverviewDTO(parties=self.parties, invites=[])

    def owned_companions(self, *, manager_pk):
        assert manager_pk == VIEWER_PK
        return self.companion_dtos

    def lock_owned_companions(self, *, manager_pk):
        assert manager_pk == VIEWER_PK
        return self.companion_dtos

    def read_active_member_party(self, *, member_pk, party_pk):
        assert (member_pk, party_pk) == (VIEWER_PK, OWN_PARTY_PK)
        return self.lead

    def get_or_create_membership(self, **kwargs):
        self.memberships.append(kwargs)
        return True


class FakeNotifier:
    def notify_party_invited(self, notification):
        raise AssertionError(notification)


def _service(parties):
    return PartyService(FakeTransaction(), parties, FakeNotifier())


class TestAddCompanion:
    def test_ambiguous_name(self):
        parties = FakeParties(
            lead=PartyActionContextDTO(name="Ekipa", actor_name="Lena")
        )
        parties.companion_dtos = [_companion_dto(), _companion_dto()]

        outcome = _service(parties).add_companion(
            member_pk=VIEWER_PK, party_pk=OWN_PARTY_PK, display_name="Kid"
        )

        assert outcome == CompanionAddOutcome.AMBIGUOUS_NAME
        assert not parties.memberships


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


class TestEnrollmentSelection:
    def test_garbage_request_is_flagged_invalid(self):
        parties = FakeParties()
        parties.parties = [_party(OWN_PARTY_PK, is_leader=True)]

        selection = _service(parties).enrollment_selection(
            viewer_pk=VIEWER_PK, requested_party="ekipa"
        )

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
