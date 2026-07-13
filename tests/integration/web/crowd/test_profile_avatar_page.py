from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import User
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import UserDTO
from tests.integration.utils import assert_response


class TestProfileAvatarPageView:
    URL = reverse("web:crowd:profile-avatar")

    def test_get_ok(self, authenticated_client, active_user):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "user": UserDTO.model_validate(active_user),
                "gravatar_url": gravatar_url(active_user.email),
                "has_auth0_avatar": False,
                "profile_active_tab": "avatar",
            },
            template_name="crowd/user/avatar.html",
        )

    def test_get_shows_both_avatars_when_auth0_exists(
        self, authenticated_client, active_user
    ):
        active_user.avatar_url = "https://example.com/auth0-avatar.png"
        active_user.save()

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "user": UserDTO.model_validate(active_user),
                "gravatar_url": gravatar_url(active_user.email),
                "has_auth0_avatar": True,
                "profile_active_tab": "avatar",
            },
            template_name="crowd/user/avatar.html",
        )

    def test_get_shows_only_gravatar_when_no_auth0(
        self, authenticated_client, active_user
    ):
        active_user.avatar_url = ""
        active_user.save()

        response = authenticated_client.get(self.URL)

        assert response.status_code == HTTPStatus.OK
        assert response.context["has_auth0_avatar"] is False

    def test_get_renders_empty_circle_without_email(
        self, authenticated_client, active_user
    ):
        active_user.email = ""
        active_user.save()

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            not_contains='src="None"',
            context_data={
                "user": UserDTO.model_validate(active_user),
                "gravatar_url": gravatar_url(""),
                "has_auth0_avatar": False,
                "profile_active_tab": "avatar",
            },
            template_name="crowd/user/avatar.html",
        )

    def test_get_disables_gravatar_option_without_email(
        self, authenticated_client, active_user
    ):
        active_user.email = ""
        active_user.avatar_url = "https://example.com/auth0-avatar.png"
        active_user.save()

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            contains="disabled",
            not_contains="Based on your email address.",
            context_data={
                "user": UserDTO.model_validate(active_user),
                "gravatar_url": gravatar_url(""),
                "has_auth0_avatar": True,
                "profile_active_tab": "avatar",
            },
            template_name="crowd/user/avatar.html",
        )

    def test_post_select_gravatar(self, authenticated_client, active_user):
        response = authenticated_client.post(self.URL, data={"use_gravatar": "true"})

        assert_response(response, HTTPStatus.FOUND, url=self.URL)
        user = User.objects.get(id=active_user.id)
        assert user.use_gravatar is True

    def test_post_select_auth0_avatar(self, authenticated_client, active_user):
        active_user.use_gravatar = True
        active_user.save()

        response = authenticated_client.post(self.URL, data={"use_gravatar": "false"})

        assert_response(response, HTTPStatus.FOUND, url=self.URL)
        user = User.objects.get(id=active_user.id)
        assert user.use_gravatar is False

    def test_unauthenticated_redirects(self, client):
        response = client.get(self.URL)

        assert response.status_code == HTTPStatus.FOUND
