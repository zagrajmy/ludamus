"""Integration tests for the facilitator detail page."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Facilitator, PersonalDataField
from ludamus.pacts import EventDTO, FacilitatorDTO, PersonalDataFieldDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_facilitator(event, **kwargs):
    defaults = {"display_name": "Alice", "slug": "alice", "user": None}
    defaults.update(kwargs)
    return Facilitator.objects.create(event=event, **defaults)


def _make_personal_data_field(event, **kwargs):
    defaults = {
        "name": "Dietary requirements",
        "question": "Any dietary requirements?",
        "slug": "dietary",
        "field_type": "text",
        "order": 0,
    }
    defaults.update(kwargs)
    return PersonalDataField.objects.create(event=event, **defaults)


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "facilitators",
    }


class TestFacilitatorDetailPageView:
    """Tests for /panel/event/<slug>/facilitators/<facilitator_slug>/ page."""

    @staticmethod
    def get_url(event, facilitator_slug="alice"):
        return reverse(
            "panel:facilitator-detail",
            kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:facilitator-detail",
            kwargs={"slug": "nonexistent", "facilitator_slug": "alice"},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_redirects_when_facilitator_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, "nonexistent"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_get_ok_with_no_personal_data_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
            },
        )

    def test_get_shows_accreditation_type(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, accreditation_type="honorary")

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        html = response.content.decode()
        assert "Accreditation type" in html
        assert "Honorary" in html

    def test_get_shows_personal_data_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        field = _make_personal_data_field(event)

        response = authenticated_client.get(self.get_url(event))

        field_dto = PersonalDataFieldDTO(
            pk=field.pk,
            name=field.name,
            question=field.question,
            slug=field.slug,
            field_type=field.field_type,
            order=field.order,
            options=[],
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "accreditation_type_display": "None",
                "personal_data_items": [(field_dto, None)],
                "has_personal_data": False,
            },
        )
