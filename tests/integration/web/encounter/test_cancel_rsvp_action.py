from http import HTTPStatus

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.models import EncounterRSVP
from tests.integration.conftest import EncounterRSVPFactory
from tests.integration.utils import assert_response, assert_response_404


class TestEncounterCancelRSVPActionView:
    def _url(self, share_code):
        return reverse(
            "web:notice-board:encounter-cancel-rsvp", kwargs={"share_code": share_code}
        )

    def test_login_required(self, client, encounter):
        url = self._url(encounter.share_code)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_requires_post(self, authenticated_client, encounter):
        response = authenticated_client.get(self._url(encounter.share_code))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_ok(self, authenticated_client, encounter, user):
        EncounterRSVPFactory(encounter=encounter, user=user)

        response = authenticated_client.post(self._url(encounter.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=(
                (constants.SUCCESS, "You have been removed from this encounter."),
            ),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert not EncounterRSVP.objects.filter(encounter=encounter, user=user).exists()

    def test_not_found(self, authenticated_client):
        response = authenticated_client.post(self._url("XXXXXX"))

        assert_response_404(response)
