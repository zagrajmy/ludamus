from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    MAX_CONNECTED_USERS,
    Party,
    PartyMembership,
    User,
)
from ludamus.pacts.crowd import UserType
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

PARTIES_URL = reverse("web:crowd:profile-parties")


class TestProfileConnectedUsersPageView:
    URL = reverse("web:crowd:profile-connected-users")

    def test_get_redirects_to_parties(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=PARTIES_URL)

    def test_post_ok(self, authenticated_client, active_user, faker):
        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user added successfully!")],
            url=PARTIES_URL,
        )
        user = User.objects.get(name=data["name"])
        assert user.user_type == UserType.CONNECTED
        membership = PartyMembership.objects.get(member=user)
        assert membership.party.leader_id == active_user.pk

    def test_post_error_form_invalid(self, authenticated_client):
        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.WARNING, "Please correct the errors below.")],
            context_data={
                "form": ANY,
                "view": ANY,
                "parties": [],
                "invites": [],
                "companions_count": 0,
                "max_connected_users": MAX_CONNECTED_USERS,
                "can_add_companion": True,
                "create_companion_form": ANY,
                "invite_form": ANY,
                "party_form": ANY,
            },
            template_name=["crowd/user/parties.html"],
        )

    def test_post_error_max_connected_users_exceeded(
        self, authenticated_client, active_user, faker
    ):
        for i in range(MAX_CONNECTED_USERS):
            UserFactory(
                username=f"user_{i}_{faker.random_int()}",
                name=f"connected_{i}_{faker.random_int()}",
                slug=f"connected-{i}-{faker.random_int()}",
                user_type=UserType.CONNECTED,
                manager=active_user,
            )

        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(self.URL, data=data)

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == ["crowd/user/parties.html"]
        assert response.context_data["can_add_companion"] is False
        assert response.context_data["companions_count"] == MAX_CONNECTED_USERS
        connected_count = User.objects.filter(user_type=UserType.CONNECTED).count()
        assert connected_count == MAX_CONNECTED_USERS
        response_messages = [
            (message.level, message.message)
            for message in list(response.context["messages"])
        ]
        assert response_messages == [
            (messages.ERROR, "You can only have up to 6 connected users."),
            (messages.WARNING, "Please correct the errors below."),
        ]

    def test_companion_join_the_leaders_existing_default_party(
        self, authenticated_client, active_user, connected_user, faker
    ):
        default_party = Party.objects.get(
            leader=active_user, memberships__member=connected_user
        )
        data = {"name": faker.name(), "user_type": UserType.CONNECTED}

        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user added successfully!")],
            url=PARTIES_URL,
        )
        user = User.objects.get(name=data["name"])
        assert PartyMembership.objects.get(member=user).party_id == default_party.pk
