from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import User
from ludamus.pacts.crowd import UserType
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
            url=reverse("web:crowd:profile-parties"),
        )
        user = User.objects.get(pk=connected_user.pk)
        assert user.name == data["name"]
        assert user.user_type == data["user_type"]

    def test_post_error_form_invalid(self, authenticated_client, connected_user):
        response = authenticated_client.post(self._get_url(connected_user.slug))

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == ["crowd/user/parties.html"]
        # The bound (invalid) form is re-rendered inline on the companion's row.
        row_by_slug = {
            row["companion"].slug: row for row in response.context_data["companions"]
        }
        bound_form = row_by_slug[connected_user.slug]["form"]
        assert bound_form is not None
        assert bound_form.errors
        # The row renders in edit mode so the validation errors are visible.
        assert row_by_slug[connected_user.slug]["editing"] is True
        response_messages = [
            (message.level, message.message)
            for message in list(response.context["messages"])
        ]
        assert response_messages == [
            (messages.WARNING, "Please correct the errors below.")
        ]
