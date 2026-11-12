import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
    ParleyConversation,
    ParleyConversationMember,
    PartyMembership,
)
from ludamus.pacts.parley import ParleyConversationError, ParleyMemberState
from ludamus.pacts.party import PartyMembershipStatus
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import UserFactory


def _members(party_pk):
    chat = ParleyConversation.objects.get(party_id=party_pk)
    return dict(
        ParleyConversationMember.objects.filter(conversation=chat).values_list(
            "user_id", "state"
        )
    )


@pytest.fixture(name="services")
def _services():
    return Services()


@pytest.fixture(name="leader")
def _leader():
    return UserFactory(age_band=AgeBand.SIXTEEN_PLUS)


def test_a_party_chat_follows_its_members_and_outlives_the_party(services, leader):
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    kid = UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN)
    party_pk = services.parties.create(leader_pk=leader.pk, name="Ekipa")
    assert not ParleyConversation.objects.filter(party_id=party_pk).exists()
    token = services.parties.read_invite_token(leader_pk=leader.pk, party_pk=party_pk)

    for member in (friend, kid):
        services.parties.join_via_link(token=token, user_pk=member.pk)

    assert _members(party_pk) == {
        leader.pk: ParleyMemberState.ACTIVE,
        friend.pk: ParleyMemberState.ACTIVE,
        kid.pk: ParleyMemberState.ACTIVE,
    }
    services.parties.rename(leader_pk=leader.pk, party_pk=party_pk, name="Drużyna")
    [chat] = services.parley_conversations.list_for(leader.pk)
    assert (chat.title, chat.name) == ("Drużyna", "Drużyna")

    services.parties.leave(user_pk=friend.pk, party_pk=party_pk)
    assert set(_members(party_pk).values()) == {ParleyMemberState.LEFT}
    assert services.parley_conversations.list_for(leader.pk) == []

    services.parties.join_via_link(token=token, user_pk=friend.pk)
    assert set(_members(party_pk).values()) == {ParleyMemberState.ACTIVE}
    services.parties.delete(leader_pk=leader.pk, party_pk=party_pk)
    assert ParleyConversation.objects.filter(party_id=party_pk).exists()
    assert set(_members(party_pk).values()) == {ParleyMemberState.LEFT}


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_invites_accepted_at_once_all_land_in_the_one_chat(leader):
    party_pk = Services().parties.create(leader_pk=leader.pk, name="Ekipa")
    joiners = [UserFactory(age_band=AgeBand.SIXTEEN_PLUS) for _ in range(4)]
    invites = {
        user.pk: (
            PartyMembership.objects.create(
                party_id=party_pk, member=user, status=PartyMembershipStatus.INVITED
            ).pk
        )
        for user in joiners
    }
    barrier = threading.Barrier(len(joiners))

    def accept(user):
        barrier.wait()
        try:
            return Services().parties.accept_invite(
                user_pk=user.pk, membership_pk=invites[user.pk]
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(joiners)) as pool:
        accepted = [
            future.result()
            for future in [pool.submit(accept, user) for user in joiners]
        ]

    assert all(accepted)

    assert ParleyConversation.objects.filter(party_id=party_pk).count() == 1
    assert _members(party_pk) == {
        user.pk: ParleyMemberState.ACTIVE for user in (leader, *joiners)
    }


def test_an_accepted_invite_brings_the_member_into_the_chat(services, leader):
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    party_pk = services.parties.create(leader_pk=leader.pk, name="")
    membership = PartyMembership.objects.create(
        party_id=party_pk, member=friend, status=PartyMembershipStatus.INVITED
    )

    services.parties.accept_invite(user_pk=friend.pk, membership_pk=membership.pk)

    assert _members(party_pk) == {
        leader.pk: ParleyMemberState.ACTIVE,
        friend.pk: ParleyMemberState.ACTIVE,
    }


def test_a_member_the_leader_removes_leaves_the_chat(services, leader):
    friends = [UserFactory(age_band=AgeBand.SIXTEEN_PLUS) for _ in range(2)]
    party_pk = services.parties.create(leader_pk=leader.pk, name="")
    token = services.parties.read_invite_token(leader_pk=leader.pk, party_pk=party_pk)
    for friend in friends:
        services.parties.join_via_link(token=token, user_pk=friend.pk)
    removed = PartyMembership.objects.get(party_id=party_pk, member=friends[0])

    services.parties.remove_member(
        leader_pk=leader.pk, party_pk=party_pk, membership_pk=removed.pk
    )

    assert _members(party_pk)[friends[0].pk] == ParleyMemberState.LEFT
    assert _members(party_pk)[friends[1].pk] == ParleyMemberState.ACTIVE


def test_nobody_leaves_or_renames_a_party_chat_but_through_the_party(services, leader):
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    party_pk = services.parties.create(leader_pk=leader.pk, name="Ekipa")
    token = services.parties.read_invite_token(leader_pk=leader.pk, party_pk=party_pk)
    services.parties.join_via_link(token=token, user_pk=friend.pk)
    chat_pk = ParleyConversation.objects.get(party_id=party_pk).pk

    for change in (
        lambda: services.parley_conversations.leave(
            user_id=friend.pk, conversation_id=chat_pk
        ),
        lambda: services.parley_conversations.rename(
            user_id=friend.pk, conversation_id=chat_pk, name="Moja"
        ),
    ):
        with pytest.raises(ParleyConversationError):
            change()

    assert _members(party_pk)[friend.pk] == ParleyMemberState.ACTIVE
    assert services.parley_conversations.list_for(friend.pk)[0].title == "Ekipa"
