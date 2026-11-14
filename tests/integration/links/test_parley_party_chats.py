import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.db import connection
from django.urls import reverse
from django.utils.html import escape
from zeal import zeal_ignore

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
    ParleyConversation,
    ParleyConversationMember,
    Party,
    PartyMembership,
)
from ludamus.pacts.parley import ParleyConversationError, ParleyMemberState
from ludamus.pacts.party import PartyMembershipStatus
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


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


@pytest.fixture(name="staff_client")
def _staff_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def _party_of(services, leader, *members):
    party_pk = services.parties.create(leader_pk=leader.pk, name="Ekipa")
    token = services.parties.read_invite_token(leader_pk=leader.pk, party_pk=party_pk)
    for member in members:
        services.parties.join_via_link(token=token, user_pk=member.pk)
    return party_pk


def _change_data(response):
    form = response.context["adminform"].form
    data = {}
    for name, field in form.fields.items():
        value = form.initial.get(name, field.initial)
        if isinstance(value, datetime):
            data[f"{name}_0"] = value.date().isoformat()
            data[f"{name}_1"] = value.time().strftime("%H:%M:%S")
        elif isinstance(value, (list, tuple)):
            data[name] = [str(getattr(item, "pk", item)) for item in value]
        elif value is not None:
            data[name] = value
    return data


def test_staff_deleting_the_third_member_closes_an_adult_and_teen_pair(
    services, leader, staff_client
):
    kid = UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN)
    third = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    party_pk = _party_of(services, leader, kid, third)

    response = staff_client.post(
        reverse("admin:db_main_user_delete", args=[third.pk]), {"post": "yes"}
    )

    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.SUCCESS, f"The user “{third}” was deleted successfully.")],
        url=reverse("admin:db_main_user_changelist"),
    )
    assert _members(party_pk) == {
        leader.pk: ParleyMemberState.LEFT,
        kid.pk: ParleyMemberState.LEFT,
    }


def test_staff_deleting_the_leader_lets_everyone_go_from_the_chat(
    services, leader, staff_client
):
    friends = [UserFactory(age_band=AgeBand.SIXTEEN_PLUS) for _ in range(2)]
    party_pk = _party_of(services, leader, *friends)

    staff_client.post(
        reverse("admin:db_main_user_changelist"),
        {
            "action": "delete_selected",
            helpers.ACTION_CHECKBOX_NAME: [str(leader.pk)],
            "post": "yes",
        },
    )

    assert not Party.objects.filter(pk=party_pk).exists()
    assert set(_members(party_pk).values()) == {ParleyMemberState.LEFT}


def test_staff_changing_a_member_s_age_resyncs_their_party_chat(
    services, leader, staff_client
):
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    party_pk = _party_of(services, leader, friend)
    url = reverse("admin:db_main_user_change", args=[friend.pk])
    # NOTE: the admin's own permission picker loads lazily row by row.
    with zeal_ignore():
        data = _change_data(staff_client.get(url))

    response = staff_client.post(
        url,
        data | {"age_band": AgeBand.THIRTEEN_TO_FIFTEEN.value, "password": "!unusable"},
    )

    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[
            (
                messages.SUCCESS,
                (
                    f'The user “<a href="{url}">{escape(str(friend))}</a>”'
                    " was changed successfully."
                ),
            )
        ],
        url=reverse("admin:db_main_user_changelist"),
    )
    assert set(_members(party_pk).values()) == {ParleyMemberState.LEFT}


def test_a_block_between_the_two_in_a_party_s_chat_stops_it_as_a_direct_message_would(
    services, leader
):
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    party_pk = _party_of(services, leader, friend)

    services.parley_conversations.block(user_id=leader.pk, blocked_id=friend.pk)

    assert [
        chat.can_write for chat in services.parley_conversations.list_for(friend.pk)
    ] == [False]
    third = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    services.parties.join_via_link(
        token=services.parties.read_invite_token(
            leader_pk=leader.pk, party_pk=party_pk
        ),
        user_pk=third.pk,
    )
    assert [
        chat.can_write for chat in services.parley_conversations.list_for(friend.pk)
    ] == [True]
