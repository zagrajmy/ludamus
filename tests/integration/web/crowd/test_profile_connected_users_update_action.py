from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import MAX_CONNECTED_USERS, User
from ludamus.pacts.crowd import UserDTO, UserType
from tests.integration.utils import assert_response


class TestProfileConnectedUserUpdateActionView:
    URL_NAME = "web:crowd:profile-connected-users-update"

    def _get_url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_post_ok(self, authenticated_client, connected_user, faker):
        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(
            self._get_url(connected_user.slug), data=data
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user updated successfully!")],
            url=reverse("web:crowd:profile-connected-users"),
        )
        user = User.objects.get(pk=connected_user.pk)
        assert user.name == data["name"]
        assert user.user_type == data["user_type"]

    def test_post_error_form_invalid(self, authenticated_client, connected_user):
        response = authenticated_client.post(self._get_url(connected_user.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.WARNING, "Please correct the errors below.")],
            context_data={
                "object": UserDTO.model_validate(connected_user),
                "user": UserDTO.model_validate(connected_user),
                "form": ANY,
                "view": ANY,
                "max_connected_users": MAX_CONNECTED_USERS,
                "connected_users": [
                    {"user": UserDTO.model_validate(connected_user), "form": ANY}
                ],
            },
            template_name=["crowd/user/connected.html"],
        )
