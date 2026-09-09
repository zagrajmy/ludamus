from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

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
def encounters_disabled(sphere):
    sphere.enabled_pages = ["events"]
    sphere.save()


@pytest.mark.usefixtures("encounters_disabled")
class TestEncounterViewsWithPageDisabled:
    @pytest.mark.parametrize("url_name", ("index", "create"), ids=("index", "create"))
    def test_get_pages_404(self, authenticated_client, url_name):
        response = authenticated_client.get(reverse(f"web:notice-board:{url_name}"))

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
        encounter.refresh_from_db()

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
def timeline_only(sphere):
    sphere.enabled_pages = ["timeline"]
    sphere.default_page = "timeline"
    sphere.save()


@pytest.mark.usefixtures("timeline_only")
class TestEncounterContentWithTimelineOnly:
    """The timeline feeds public encounters, so their content stays served.

    Only the encounters index itself is the disabled page.
    """

    def test_index_404(self, authenticated_client):
        response = authenticated_client.get(reverse("web:notice-board:index"))

        assert_response_404(response)

    def test_create_ok(self, authenticated_client):
        response = authenticated_client.get(reverse("web:notice-board:create"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )

    def test_share_code_page_ok(self, client, encounter):
        response = client.get(
            reverse(
                "web:notice-board:encounter-qr",
                kwargs={"share_code": encounter.share_code},
            )
        )

        assert_response(response, HTTPStatus.OK)
