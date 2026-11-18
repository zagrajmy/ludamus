from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.models import ParleyConversation, ParleyConversationMember
from ludamus.pacts.encounter import RSVPOutcome
from ludamus.pacts.parley import ParleyConversationError, ParleyMemberState
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import EncounterFactory, UserFactory
from tests.integration.utils import assert_response


def _members(encounter_pk):
    chat = ParleyConversation.objects.get(encounter_id=encounter_pk)
    return dict(
        ParleyConversationMember.objects.filter(conversation=chat).values_list(
            "user_id", "state"
        )
    )


def _sign_up(services, encounter, user, *, ip_address):
    return services.encounters.rsvp(
        share_code=encounter.share_code,
        sphere_id=encounter.sphere_id,
        user_id=user.pk,
        ip_address=ip_address,
    )


@pytest.fixture(name="services")
def _services():
    return Services()


@pytest.fixture(name="encounter")
def _encounter():
    return EncounterFactory(
        title="Sesja Blades", creator=UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    )


def test_an_encounter_chat_follows_its_signups_and_outlives_the_encounter(
    services, encounter
):
    creator = encounter.creator
    player = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    kid = UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN)
    assert not ParleyConversation.objects.filter(encounter_id=encounter.pk).exists()

    for number, user in enumerate((player, kid)):
        outcome = _sign_up(services, encounter, user, ip_address=f"10.0.0.{number}")
        assert outcome is RSVPOutcome.CREATED

    assert _members(encounter.pk) == {
        creator.pk: ParleyMemberState.ACTIVE,
        player.pk: ParleyMemberState.ACTIVE,
        kid.pk: ParleyMemberState.ACTIVE,
    }
    [chat] = services.parley_conversations.list_for(kid.pk)
    assert (chat.kind, chat.title, chat.name) == (
        "encounter",
        "Sesja Blades",
        "Sesja Blades",
    )

    services.encounters.cancel_rsvp(
        share_code=encounter.share_code, sphere_id=encounter.sphere_id, user_id=kid.pk
    )
    assert _members(encounter.pk)[kid.pk] == ParleyMemberState.LEFT
    assert services.parley_conversations.list_for(kid.pk) == []

    services.encounters.delete_owned(
        pk=encounter.pk, sphere_id=encounter.sphere_id, user_id=creator.pk
    )
    assert ParleyConversation.objects.filter(encounter_id=encounter.pk).exists()
    assert set(_members(encounter.pk).values()) == {ParleyMemberState.LEFT}


def test_nobody_leaves_or_renames_an_encounter_chat_but_through_the_signup(
    services, encounter
):
    player = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    _sign_up(services, encounter, player, ip_address="10.0.1.1")
    chat_pk = ParleyConversation.objects.get(encounter_id=encounter.pk).pk

    for change in (
        lambda: services.parley_conversations.leave(
            user_id=player.pk, conversation_id=chat_pk
        ),
        lambda: services.parley_conversations.rename(
            user_id=player.pk, conversation_id=chat_pk, name="Moja"
        ),
    ):
        with pytest.raises(ParleyConversationError):
            change()

    assert _members(encounter.pk)[player.pk] == ParleyMemberState.ACTIVE


def test_an_adult_and_a_teen_alone_get_no_encounter_chat(services, encounter):
    kid = UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN)

    _sign_up(services, encounter, kid, ip_address="10.0.2.1")

    assert not ParleyConversation.objects.filter(encounter_id=encounter.pk).exists()


def test_a_sphere_with_chat_off_has_no_encounter_chats_until_it_turns_chat_on(
    services, encounter
):
    sphere = encounter.sphere
    sphere.parley_enabled = False
    sphere.save()
    player = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)

    _sign_up(services, encounter, player, ip_address="10.0.3.1")
    assert not ParleyConversation.objects.filter(encounter_id=encounter.pk).exists()

    services.sphere_panel.patch_settings(sphere.pk, changes={"parley_enabled": True})
    assert set(_members(encounter.pk).values()) == {ParleyMemberState.ACTIVE}

    services.sphere_panel.patch_settings(sphere.pk, changes={"parley_enabled": False})
    assert set(_members(encounter.pk).values()) == {ParleyMemberState.LEFT}


@pytest.fixture(name="staff_client")
def _staff_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def test_staff_deleting_a_player_lets_them_go_from_the_encounter_chat(
    services, encounter, staff_client
):
    players = [UserFactory(age_band=AgeBand.SIXTEEN_PLUS) for _ in range(2)]
    for number, player in enumerate(players):
        _sign_up(services, encounter, player, ip_address=f"10.0.4.{number}")

    response = staff_client.post(
        reverse("admin:db_main_user_delete", args=[players[0].pk]), {"post": "yes"}
    )

    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[
            (messages.SUCCESS, f"The user “{players[0]}” was deleted successfully.")
        ],
        url=reverse("admin:db_main_user_changelist"),
    )
    assert _members(encounter.pk) == {
        encounter.creator_id: ParleyMemberState.ACTIVE,
        players[1].pk: ParleyMemberState.ACTIVE,
    }


def test_the_encounter_page_opens_its_chat_for_members_alone(services, encounter):
    player = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    stranger = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    _sign_up(services, encounter, player, ip_address="10.0.5.1")
    chat_pk = ParleyConversation.objects.get(encounter_id=encounter.pk).pk

    def chat_id_for(user):
        return services.encounters.build_detail(
            share_code=encounter.share_code,
            sphere_id=encounter.sphere_id,
            current_user_id=user.pk,
            page_url="https://example.com/",
        ).chat_id

    assert [chat_id_for(user) for user in (encounter.creator, player, stranger)] == [
        chat_pk,
        chat_pk,
        None,
    ]
