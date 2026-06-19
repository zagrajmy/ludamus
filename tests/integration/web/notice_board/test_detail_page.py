from http import HTTPStatus

from django.urls import reverse

from ludamus.adapters.db.django.models import EncounterRSVP
from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.gravatar import gravatar_url
from ludamus.mills import google_calendar_url, outlook_calendar_url, render_markdown
from ludamus.pacts import EncounterDTO
from tests.integration.conftest import (
    EncounterFactory,
    EncounterRSVPFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404

RSVP_COUNT = 2


def _creator_info(creator):
    return UserInfo(
        avatar_url=gravatar_url(creator.email),
        discord_username=creator.discord_username,
        full_name=creator.full_name,
        name=creator.name,
        pk=creator.pk,
        slug=creator.slug,
        username=creator.username,
    )


def _detail_context(
    encounter, *, is_creator=False, user_has_rsvpd=False, attendees=None, rsvp_count=0
):
    encounter_dto = EncounterDTO.model_validate(encounter)
    share_url = "http://testserver" + reverse(
        "web:notice-board:encounter-detail", kwargs={"share_code": encounter.share_code}
    )
    spots = encounter.max_participants - rsvp_count
    return {
        "encounter": encounter_dto,
        "creator": _creator_info(encounter.creator),
        "attendees": attendees if attendees is not None else [],
        "rsvp_count": rsvp_count,
        "is_full": (
            encounter.max_participants > 0 and rsvp_count >= encounter.max_participants
        ),
        "spots_remaining": max(0, spots) if encounter.max_participants > 0 else None,
        "is_creator": is_creator,
        "description_html": (
            render_markdown(encounter.description) if encounter.description else ""
        ),
        "share_url": share_url,
        "user_has_rsvpd": user_has_rsvpd,
        "google_calendar_url": google_calendar_url(encounter_dto, share_url),
        "outlook_calendar_url": outlook_calendar_url(encounter_dto, share_url),
    }


class TestEncounterDetailPageView:
    def test_ok_anonymous(self, client, encounter):
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(encounter),
            template_name="notice_board/detail.html",
        )

    def test_ok_authenticated(self, authenticated_client, encounter):
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(encounter),
            template_name="notice_board/detail.html",
        )

    def test_creator_flag(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(encounter, is_creator=True),
            template_name="notice_board/detail.html",
        )

    def test_not_found(self, client):
        url = reverse(
            "web:notice-board:encounter-detail", kwargs={"share_code": "XXXXXX"}
        )

        response = client.get(url)

        assert_response_404(response)

    def test_spots_remaining(self, client, encounter_with_rsvps):
        encounter = encounter_with_rsvps
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        rsvps = EncounterRSVP.objects.filter(encounter=encounter).order_by(
            "creation_time"
        )
        attendees = [
            UserInfo(
                avatar_url=gravatar_url(r.user.email),
                discord_username=r.user.discord_username,
                full_name=r.user.full_name,
                name=r.user.name,
                pk=r.user.pk,
                slug=r.user.slug,
                username=r.user.username,
            )
            for r in rsvps
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(
                encounter, rsvp_count=RSVP_COUNT, attendees=attendees
            ),
            template_name="notice_board/detail.html",
        )

    def test_description_markdown(self, client, sphere):
        encounter = EncounterFactory(sphere=sphere, description="**bold** and *italic*")
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(encounter),
            template_name="notice_board/detail.html",
        )

    def test_og_meta(self, client, encounter):
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(encounter),
            template_name="notice_board/detail.html",
        )
        content = response.content.decode()
        assert encounter.title in content

    def test_full_encounter_shows_no_spots_left(self, client, sphere):
        encounter = EncounterFactory(sphere=sphere, max_participants=2)
        EncounterRSVPFactory(encounter=encounter)
        EncounterRSVPFactory(encounter=encounter)
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert "No spots left" in response.content.decode()

    def test_authenticated_rsvpd_user_sees_signed_up_state(
        self, authenticated_client, active_user, sphere
    ):
        encounter = EncounterFactory(sphere=sphere, max_participants=6)
        EncounterRSVPFactory(encounter=encounter, user=active_user)
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = authenticated_client.get(url)

        assert response.status_code == HTTPStatus.OK
        html = response.content.decode()
        assert "You&#x27;re signed up!" in html or "You're signed up!" in html
        assert "Cancel signup" in html
        cancel_url = reverse(
            "web:notice-board:encounter-cancel-rsvp",
            kwargs={"share_code": encounter.share_code},
        )
        assert cancel_url in html

    def test_attendees_with_user_rsvps(self, client, sphere):
        rsvp_user = UserFactory(
            username="rsvpuser", email="rsvp@example.com", name="RSVP User"
        )
        encounter = EncounterFactory(sphere=sphere, max_participants=6)
        EncounterRSVPFactory(encounter=encounter, user=rsvp_user)
        url = reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        attendees = [
            UserInfo(
                avatar_url=gravatar_url(rsvp_user.email),
                discord_username=rsvp_user.discord_username,
                full_name=rsvp_user.full_name,
                name=rsvp_user.name,
                pk=rsvp_user.pk,
                slug=rsvp_user.slug,
                username=rsvp_user.username,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_detail_context(encounter, rsvp_count=1, attendees=attendees),
            template_name="notice_board/detail.html",
        )
