from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import User
from tests.integration.utils import assert_response


class TestProfileConnectedUserDeleteActionView:
    URL_NAME = "web:crowd:profile-connected-users-delete"

    def _get_url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_post_ok(self, authenticated_client, connected_user):
        response = authenticated_client.post(self._get_url(connected_user.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user deleted successfully.")],
            url=reverse("web:crowd:profile-parties"),
        )

        assert not User.objects.filter(pk=connected_user.pk).exists()
