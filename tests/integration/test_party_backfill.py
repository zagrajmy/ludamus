import pytest
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction

from ludamus.adapters.db.django.models import Party, PartyMembership, User
from ludamus.links.db.django.party_backfill import backfill_parties
from ludamus.pacts.crowd import UserType
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus


def _active(username, slug):
    return User.objects.create(
        username=username,
        slug=slug,
        name=username,
        user_type=UserType.ACTIVE,
        password=make_password(None),
    )


def _connected(username, slug, manager):
    return User.objects.create(
        username=username,
        slug=slug,
        name=username,
        user_type=UserType.CONNECTED,
        manager=manager,
        password=make_password(None),
    )


def _run():
    return backfill_parties(
        user_model=User, party_model=Party, membership_model=PartyMembership
    )


class TestBackfillParties:
    def test_one_party_per_manager_with_companions(self):
        manager = _active("mgr", "mgr")
        kid1 = _connected("connected|k1", "k1", manager)
        kid2 = _connected("connected|k2", "k2", manager)

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
        _active("solo", "solo")

        created = _run()

        assert created == 0
        assert not Party.objects.exists()

    def test_two_managers_get_two_parties(self):
        a = _active("a", "a")
        _connected("connected|a1", "a1", a)
        b = _active("b", "b")
        _connected("connected|b1", "b1", b)

        created = _run()

        leaders = {p.leader_id for p in Party.objects.all()}
        assert leaders == {a.pk, b.pk}
        assert created == len(leaders)


class TestPartyMembershipConstraint:
    def test_member_unique_per_party(self):
        manager = _active("mgr", "mgr")
        party = Party.objects.create(leader=manager, name="")
        PartyMembership.objects.create(party=party, member=manager)

        with pytest.raises(IntegrityError), transaction.atomic():
            PartyMembership.objects.create(party=party, member=manager)
