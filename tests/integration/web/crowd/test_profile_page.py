from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import User
from ludamus.pacts.crowd import UserDTO, UserType
from tests.integration.utils import assert_response


class TestProfilePageView:
    URL = reverse("web:crowd:profile")

    def test_get_ok(self, authenticated_client, active_user):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "object": UserDTO.model_validate(active_user),
                "user": UserDTO.model_validate(active_user),
                "form": ANY,
                "view": ANY,
                "confirmed_participations_count": 0,
                "profile_active_tab": "profile",
            },
            template_name=["crowd/user/edit.html"],
        )

    def test_post_ok(self, authenticated_client, active_user, faker):
        data = {
            "name": faker.name(),
            "email": faker.email(),
            "user_type": UserType.ACTIVE,
        }
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Profile updated successfully!")],
            url="/",
        )
        user = User.objects.get(id=active_user.id)
        assert user.name == data["name"]
        assert user.email == data["email"]

    def test_post_updates_discord_username(
        self, authenticated_client, active_user, faker
    ):
        data = {
            "name": faker.name(),
            "email": faker.email(),
            "user_type": UserType.ACTIVE,
            "discord_username": "testuser#1234",
        }
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Profile updated successfully!")],
            url="/",
        )
        user = User.objects.get(id=active_user.id)
        assert user.discord_username == "testuser#1234"

    def test_post_error_form_invalid(self, active_user, authenticated_client):
        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.WARNING, "Please correct the errors below.")],
            context_data={
                "object": UserDTO.model_validate(active_user),
                "user": UserDTO.model_validate(active_user),
                "form": ANY,
                "view": ANY,
                "confirmed_participations_count": 0,
                "profile_active_tab": "profile",
            },
            template_name=["crowd/user/edit.html"],
        )

    def test_post_error_duplicate_email(
        self, authenticated_client, active_user, staff_user, faker
    ):
        data = {
            "name": faker.name(),
            "email": staff_user.email,
            "user_type": UserType.ACTIVE,
        }
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.WARNING, "Please correct the errors below.")],
            context_data={
                "object": UserDTO.model_validate(active_user),
                "user": UserDTO.model_validate(active_user),
                "form": ANY,
                "view": ANY,
                "confirmed_participations_count": 0,
                "profile_active_tab": "profile",
            },
            template_name=["crowd/user/edit.html"],
        )

        assert "email" in response.context["form"].errors
        assert (
            "This email address is already in use"
            in response.context["form"].errors["email"][0]
        )

    def test_post_ok_same_email(self, authenticated_client, active_user, faker):
        existing_email = faker.email()
        active_user.email = existing_email
        active_user.save()

        data = {
            "name": faker.name(),
            "email": existing_email,
            "user_type": UserType.ACTIVE,
        }
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Profile updated successfully!")],
            url="/",
        )
        user = User.objects.get(id=active_user.id)
        assert user.email == existing_email
