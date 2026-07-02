import pytest
from django.db import IntegrityError, transaction

from ludamus.adapters.db.django.models import Party, PartyMembership, User
from ludamus.adapters.db.django.party_backfill import backfill_parties
from ludamus.pacts.crowd import UserType
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import UserFactory


def _active(*, username, slug):
    return UserFactory(username=username, slug=slug, user_type=UserType.ACTIVE)


def _connected(*, username, slug, manager):
    return UserFactory(
        username=username, slug=slug, user_type=UserType.CONNECTED, manager=manager
    )


def _run():
    return backfill_parties(
        user_model=User, party_model=Party, membership_model=PartyMembership
    )


class TestBackfillParties:
    def test_one_party_per_manager_with_companions(self):
        manager = _active(username="mgr", slug="mgr")
        kid1 = _connected(username="connected|k1", slug="k1", manager=manager)
        kid2 = _connected(username="connected|k2", slug="k2", manager=manager)

        created = _run()

        assert created == 1
        party = Party.objects.get()
        assert party.leader_id == manager.pk
        members = party.memberships.all()
        assert {m.member_id for m in members} == {manager.pk, kid1.pk, kid2.pk}
        assert all(
            m.consent_mode == PartyConsentMode.ACCEPT_BY_DEFAULT for m in members
        )
        assert all(m.status == PartyMembershipStatus.ACTIVE for m in members)

    def test_solo_user_gets_no_party(self):
        _active(username="solo", slug="solo")

        created = _run()

        assert created == 0
        assert not Party.objects.exists()

    def test_two_managers_get_two_parties(self):
        managers = [_active(username="a", slug="a"), _active(username="b", slug="b")]
        for i, manager in enumerate(managers):
            _connected(username=f"connected|{i}", slug=f"c{i}", manager=manager)

        created = _run()

        assert created == len(managers)
        assert {p.leader_id for p in Party.objects.all()} == {m.pk for m in managers}


class TestPartyMembershipConstraint:
    def test_member_unique_per_party(self):
        manager = _active(username="mgr", slug="mgr")
        party = Party.objects.create(leader=manager, name="")
        PartyMembership.objects.create(party=party, member=manager)

        with pytest.raises(IntegrityError), transaction.atomic():
            PartyMembership.objects.create(party=party, member=manager)
