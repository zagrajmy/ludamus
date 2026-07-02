from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import MAX_CONNECTED_USERS, User
from ludamus.pacts.crowd import ConnectedUserDTO, UserType
from tests.integration.utils import assert_response


class TestProfileConnectedUsersPageView:
    URL = reverse("web:crowd:profile-connected-users")

    def test_get_ok(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": ANY,
                "view": ANY,
                "connected_users": [],
                "max_connected_users": MAX_CONNECTED_USERS,
            },
            template_name=["crowd/user/connected.html"],
        )

    def test_get_ok_existing_connected_users(
        self, authenticated_client, connected_user
    ):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": ANY,
                "view": ANY,
                "connected_users": [
                    {
                        "user": ConnectedUserDTO.model_validate(connected_user),
                        "form": ANY,
                    }
                ],
                "max_connected_users": MAX_CONNECTED_USERS,
            },
            template_name=["crowd/user/connected.html"],
        )

    def test_post_ok(self, authenticated_client, faker):
        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user added successfully!")],
            url="/crowd/profile/connected-users/",
        )
        user = User.objects.get(name=data["name"])
        assert user.user_type == UserType.CONNECTED

    def test_post_error_form_invalid(self, authenticated_client):
        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.WARNING, "Please correct the errors below.")],
            context_data={
                "form": ANY,
                "view": ANY,
                "connected_users": [],
                "max_connected_users": MAX_CONNECTED_USERS,
            },
            template_name=["crowd/user/connected.html"],
        )

    def test_post_error_max_connected_users_exceeded(
        self, authenticated_client, active_user, faker
    ):
        connected_users = []
        for i in range(MAX_CONNECTED_USERS):
            unique_name = f"connected_{i}_{faker.random_int()}"
            connected_users.append(
                User.objects.create(
                    username=f"user_{i}_{faker.random_int()}",
                    name=unique_name,
                    slug=f"connected-{i}-{faker.random_int()}",
                    user_type=UserType.CONNECTED,
                    manager=active_user,
                )
            )

        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (messages.ERROR, "You can only have up to 6 connected users."),
                (messages.WARNING, "Please correct the errors below."),
            ],
            context_data={
                "form": ANY,
                "view": ANY,
                "connected_users": [
                    {"user": ConnectedUserDTO.model_validate(user), "form": ANY}
                    for user in connected_users
                ],
                "max_connected_users": MAX_CONNECTED_USERS,
            },
            template_name=["crowd/user/connected.html"],
        )
        connected_count = User.objects.filter(user_type=UserType.CONNECTED).count()
        assert connected_count == MAX_CONNECTED_USERS
