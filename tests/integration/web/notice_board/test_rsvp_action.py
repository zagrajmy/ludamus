from http import HTTPStatus

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.models import EncounterRSVP
from tests.integration.conftest import EncounterFactory, EncounterRSVPFactory
from tests.integration.utils import assert_response, assert_response_404


class TestEncounterRSVPActionView:
    def _url(self, share_code):
        return reverse(
            "web:notice-board:encounter-rsvp", kwargs={"share_code": share_code}
        )

    def test_requires_post(self, authenticated_client, encounter):
        response = authenticated_client.get(self._url(encounter.share_code))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_login_required(self, client, encounter):
        response = client.post(self._url(encounter.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/crowd/login-required/?next=/encounters/{encounter.share_code}/do/rsvp",
        )
        assert not EncounterRSVP.objects.filter(encounter=encounter).exists()

    def test_authenticated(self, authenticated_client, encounter, user):
        response = authenticated_client.post(self._url(encounter.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "You have signed up!"),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert EncounterRSVP.objects.filter(encounter=encounter, user=user).exists()

    def test_authenticated_duplicate(self, authenticated_client, encounter, user):
        EncounterRSVPFactory(encounter=encounter, user=user)

        response = authenticated_client.post(self._url(encounter.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.WARNING, "You have already signed up."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        rsvp_count = EncounterRSVP.objects.filter(
            encounter=encounter, user=user
        ).count()
        assert rsvp_count == 1

    def test_full_encounter(self, authenticated_client, sphere, user):
        encounter = EncounterFactory(sphere=sphere, max_participants=1)
        EncounterRSVPFactory(encounter=encounter)

        response = authenticated_client.post(self._url(encounter.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, "This encounter is full."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert not EncounterRSVP.objects.filter(encounter=encounter, user=user).exists()

    def test_rsvp_with_x_forwarded_for(self, authenticated_client, encounter, user):
        response = authenticated_client.post(
            self._url(encounter.share_code), HTTP_X_FORWARDED_FOR="203.0.113.50"
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "You have signed up!"),),
            url=f"/e/{encounter.share_code}/",
        )
        rsvp = EncounterRSVP.objects.get(user=user)
        assert rsvp.ip_address == "203.0.113.50"

    def test_ip_throttle(self, authenticated_client, encounter):
        EncounterRSVPFactory(encounter=encounter, ip_address="10.0.0.1")

        response = authenticated_client.post(
            self._url(encounter.share_code), REMOTE_ADDR="10.0.0.1"
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=(
                (constants.ERROR, "Please wait a moment before signing up again."),
            ),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )

    def test_ip_throttle_uses_rightmost_x_forwarded_for(
        self, authenticated_client, encounter
    ):
        authenticated_client.post(
            self._url(encounter.share_code),
            HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.50",
            follow=True,
        )

        response = authenticated_client.post(
            self._url(encounter.share_code),
            HTTP_X_FORWARDED_FOR="5.6.7.8, 203.0.113.50",
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=(
                (constants.ERROR, "Please wait a moment before signing up again."),
            ),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )

    def test_not_found(self, authenticated_client):
        response = authenticated_client.post(
            reverse("web:notice-board:encounter-rsvp", kwargs={"share_code": "XXXXXX"})
        )

        assert_response_404(response)
