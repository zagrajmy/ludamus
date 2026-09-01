"""Encounters belonging to another sphere are invisible to this sphere's routes.

Share codes and pks are globally unique, so without a sphere filter a route
served under sphere A could read or modify sphere B's encounter — and slip past
sphere B's encounters page being disabled.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse

from tests.integration.conftest import EncounterFactory, SphereFactory, UserFactory
from tests.integration.utils import assert_response_404


@pytest.fixture(name="foreign_encounter")
def foreign_encounter_fixture(active_user):
    return EncounterFactory(
        sphere=SphereFactory(),
        creator=active_user,
        start_time=datetime.now(UTC) + timedelta(days=3),
    )


class TestForeignSphereEncounter:
    @pytest.mark.parametrize(
        "url_name",
        ("encounter-detail", "encounter-qr", "encounter-ics"),
        ids=("detail", "qr", "ics"),
    )
    @pytest.mark.usefixtures("sphere")
    def test_share_code_pages_404(self, client, foreign_encounter, url_name):
        response = client.get(
            reverse(
                f"web:notice-board:{url_name}",
                kwargs={"share_code": foreign_encounter.share_code},
            )
        )

        assert_response_404(response)

    @pytest.mark.usefixtures("sphere")
    def test_rsvp_404_without_signing_anyone_up(
        self, authenticated_client, foreign_encounter
    ):
        response = authenticated_client.post(
            reverse(
                "web:notice-board:encounter-rsvp",
                kwargs={"share_code": foreign_encounter.share_code},
            )
        )

        assert_response_404(response)
        assert foreign_encounter.rsvps.count() == 0

    @pytest.mark.usefixtures("sphere")
    def test_cancel_rsvp_404_leaves_the_signup_alone(
        self, authenticated_client, active_user, foreign_encounter
    ):
        foreign_encounter.rsvps.create(user=active_user, ip_address="10.0.0.1")

        response = authenticated_client.post(
            reverse(
                "web:notice-board:encounter-cancel-rsvp",
                kwargs={"share_code": foreign_encounter.share_code},
            )
        )

        assert_response_404(response)
        assert foreign_encounter.rsvps.count() == 1

    @pytest.mark.usefixtures("sphere")
    def test_edit_404_for_the_owner(self, authenticated_client, foreign_encounter):
        response = authenticated_client.get(
            reverse("web:notice-board:edit", kwargs={"pk": foreign_encounter.pk})
        )

        assert_response_404(response)

    @pytest.mark.usefixtures("sphere")
    def test_delete_404_without_deleting(self, authenticated_client, foreign_encounter):
        response = authenticated_client.post(
            reverse("web:notice-board:delete", kwargs={"pk": foreign_encounter.pk})
        )

        assert_response_404(response)
        foreign_encounter.refresh_from_db()

    def test_public_feed_lists_only_this_sphere(self, client, sphere):
        creator = UserFactory(username="pub_organizer", name="Pub Organizer")
        start_time = datetime.now(UTC) + timedelta(days=3)
        mine = EncounterFactory(
            sphere=sphere, creator=creator, is_public=True, start_time=start_time
        )
        EncounterFactory(
            sphere=SphereFactory(),
            creator=creator,
            is_public=True,
            start_time=start_time,
        )

        response = client.get(reverse("web:notice-board:index"))

        assert [
            item.encounter.pk for item in response.context_data["public_encounters"]
        ] == [mine.pk]
