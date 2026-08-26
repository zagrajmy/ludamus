from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.gates.web.django.notice_board.views import SAMPLE_COUNT
from ludamus.pacts import EncounterDTO, EncounterIndexItem
from tests.integration.conftest import (
    PNG_BYTES,
    EncounterFactory,
    EncounterRSVPFactory,
    UserFactory,
)
from tests.integration.utils import assert_response


class TestEncountersIndexPageView:
    URL = reverse("web:notice-board:index")

    def test_anonymous_sees_landing_page(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"sample_encounters": ANY, "view": ANY},
            template_name=["notice_board/landing.html"],
        )
        assert len(response.context_data["sample_encounters"]) == SAMPLE_COUNT

    def test_anonymous_with_public_encounters_sees_index(self, client, sphere):
        creator = UserFactory(username="pub_organizer", name="Pub Organizer")
        encounter = EncounterFactory(
            creator=creator,
            sphere=sphere,
            is_public=True,
            start_time=datetime.now(UTC) + timedelta(days=3),
        )

        response = client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [],
                "past_encounters": [],
                "public_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=0,
                        is_mine=False,
                        organizer_name="Pub Organizer",
                    )
                ],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_public_encounter_by_other_user_listed_for_authenticated(
        self, authenticated_client, sphere
    ):
        creator = UserFactory(username="pub_organizer", name="Pub Organizer")
        encounter = EncounterFactory(
            creator=creator,
            sphere=sphere,
            is_public=True,
            start_time=datetime.now(UTC) + timedelta(days=3),
        )

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [],
                "past_encounters": [],
                "public_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=0,
                        is_mine=False,
                        organizer_name="Pub Organizer",
                    )
                ],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_own_public_encounter_not_duplicated_in_public_section(
        self, authenticated_client, active_user, sphere
    ):
        encounter = EncounterFactory(
            creator=active_user,
            sphere=sphere,
            is_public=True,
            start_time=datetime.now(UTC) + timedelta(days=3),
        )

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=0,
                        is_mine=True,
                        organizer_name="",
                    )
                ],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_upcoming_encounter_with_header_image(
        self, authenticated_client, active_user, sphere
    ):
        encounter = EncounterFactory(
            creator=active_user,
            sphere=sphere,
            header_image=SimpleUploadedFile(
                "header.png", PNG_BYTES, content_type="image/png"
            ),
            start_time=datetime.now(UTC) + timedelta(days=3),
        )

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=0,
                        is_mine=True,
                        organizer_name="",
                    )
                ],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_upcoming_encounter_without_participant_limit(
        self, authenticated_client, active_user, sphere
    ):
        encounter = EncounterFactory(
            creator=active_user,
            sphere=sphere,
            max_participants=0,
            start_time=datetime.now(UTC) + timedelta(days=3),
        )

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=0,
                        is_mine=True,
                        organizer_name="",
                    )
                ],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_ok_empty(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_upcoming_rsvpd_encounter_shows_organizer_name(
        self, authenticated_client, active_user, sphere
    ):
        other_user = UserFactory(username="organizer", name="Other Organizer")
        encounter = EncounterFactory(
            creator=other_user,
            sphere=sphere,
            start_time=datetime.now(UTC) + timedelta(days=3),
        )
        EncounterRSVPFactory(encounter=encounter, user=active_user)

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=1,
                        is_mine=False,
                        organizer_name="Other Organizer",
                    )
                ],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_upcoming_rsvpd_encounter_with_inactive_creator(
        self, authenticated_client, active_user, sphere
    ):
        inactive_user = UserFactory(username="deleted_user", user_type="deleted")
        encounter = EncounterFactory(
            creator=inactive_user,
            sphere=sphere,
            start_time=datetime.now(UTC) + timedelta(days=3),
        )
        EncounterRSVPFactory(encounter=encounter, user=active_user)

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=1,
                        is_mine=False,
                        organizer_name="",
                    )
                ],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_past_encounter_by_other_user_not_joined_is_hidden(
        self, authenticated_client, sphere
    ):
        other_user = UserFactory(username="past_organizer", name="Past Organizer")
        EncounterFactory(
            creator=other_user,
            sphere=sphere,
            start_time=datetime.now(UTC) - timedelta(days=3),
        )

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [],
                "past_encounters": [],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_past_encounter_rsvpd_shows_organizer_name(
        self, authenticated_client, active_user, sphere
    ):
        other_user = UserFactory(username="past_organizer", name="Past Organizer")
        encounter = EncounterFactory(
            creator=other_user,
            sphere=sphere,
            start_time=datetime.now(UTC) - timedelta(days=3),
        )
        EncounterRSVPFactory(encounter=encounter, user=active_user)

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [],
                "past_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=1,
                        is_mine=False,
                        organizer_name="Past Organizer",
                    )
                ],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )

    def test_past_encounter_created_by_user_is_shown(
        self, authenticated_client, active_user, sphere
    ):
        encounter = EncounterFactory(
            creator=active_user,
            sphere=sphere,
            start_time=datetime.now(UTC) - timedelta(days=3),
        )

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming_encounters": [],
                "past_encounters": [
                    EncounterIndexItem(
                        encounter=EncounterDTO.model_validate(encounter),
                        rsvp_count=0,
                        is_mine=True,
                        organizer_name="",
                    )
                ],
                "public_encounters": [],
                "view": ANY,
            },
            template_name=["notice_board/index.html"],
        )
