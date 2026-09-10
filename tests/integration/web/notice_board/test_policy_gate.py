from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Encounter
from tests.integration.conftest import EncounterFactory
from tests.integration.utils import assert_response, assert_response_404


@pytest.fixture(name="encounter")
def encounter_fixture(sphere, active_user):
    return EncounterFactory(
        sphere=sphere,
        creator=active_user,
        start_time=datetime.now(UTC) + timedelta(days=3),
    )


@pytest.fixture
def encounters_off(sphere):
    sphere.encounters_policy = "none"
    sphere.save()


@pytest.mark.usefixtures("encounters_off")
class TestEncounterViewsWithEncountersOff:
    def test_create_404(self, authenticated_client):
        response = authenticated_client.get(reverse("web:notice-board:create"))

        assert_response_404(response)

    def test_edit_404(self, authenticated_client, encounter):
        response = authenticated_client.get(
            reverse("web:notice-board:edit", kwargs={"pk": encounter.pk})
        )

        assert_response_404(response)

    def test_delete_404(self, authenticated_client, encounter):
        response = authenticated_client.post(
            reverse("web:notice-board:delete", kwargs={"pk": encounter.pk})
        )

        assert_response_404(response)
        assert Encounter.objects.filter(pk=encounter.pk).exists()

    @pytest.mark.parametrize(
        "url_name",
        ("encounter-detail", "encounter-qr", "encounter-ics"),
        ids=("detail", "qr", "ics"),
    )
    def test_share_code_pages_404(self, client, encounter, url_name):
        response = client.get(
            reverse(
                f"web:notice-board:{url_name}",
                kwargs={"share_code": encounter.share_code},
            )
        )

        assert_response_404(response)

    @pytest.mark.parametrize(
        "url_name",
        ("encounter-rsvp", "encounter-cancel-rsvp"),
        ids=("rsvp", "cancel-rsvp"),
    )
    def test_rsvp_actions_404(self, authenticated_client, encounter, url_name):
        response = authenticated_client.post(
            reverse(
                f"web:notice-board:{url_name}",
                kwargs={"share_code": encounter.share_code},
            )
        )

        assert_response_404(response)
        assert encounter.rsvps.count() == 0


@pytest.fixture
def managers_only(sphere):
    sphere.encounters_policy = "managers"
    sphere.save()


@pytest.mark.usefixtures("managers_only")
class TestEncounterFormWithManagersOnlyPolicy:
    def test_create_404_for_a_regular_user(self, authenticated_client):
        response = authenticated_client.get(reverse("web:notice-board:create"))

        assert_response_404(response)

    def test_create_ok_for_a_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(reverse("web:notice-board:create"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )

    def test_share_code_page_stays_served(self, client, encounter):
        response = client.get(
            reverse(
                "web:notice-board:encounter-qr",
                kwargs={"share_code": encounter.share_code},
            )
        )

        assert_response(response, HTTPStatus.OK)
