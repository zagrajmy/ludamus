from http import HTTPStatus

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.models import Encounter
from tests.integration.conftest import EncounterFactory
from tests.integration.utils import assert_response, assert_response_404


class TestEncounterDeleteActionView:
    def _url(self, pk):
        return reverse("web:notice-board:delete", kwargs={"pk": pk})

    def test_login_required(self, client, encounter):
        response = client.post(self._url(encounter.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/crowd/login-required/?next=/encounters/{encounter.pk}/do/delete",
        )

    def test_requires_post(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)

        response = authenticated_client.get(self._url(encounter.pk))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_ok(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)

        response = authenticated_client.post(self._url(encounter.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Encounter deleted."),),
            url=reverse("web:notice-board:index"),
        )
        assert not Encounter.objects.filter(pk=encounter.pk).exists()

    def test_not_creator(self, authenticated_client, encounter):
        response = authenticated_client.post(self._url(encounter.pk))

        assert_response_404(response)
        assert Encounter.objects.filter(pk=encounter.pk).exists()

    def test_not_found(self, authenticated_client):
        response = authenticated_client.post(self._url(99999))

        assert_response_404(response)
