"""Integration tests for /panel/event/<slug>/facilitators/create/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    PersonalDataField,
    PersonalDataFieldValue,
)
from ludamus.pacts import EventDTO, PersonalDataFieldDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _field_dto(field):
    return PersonalDataFieldDTO(
        field_type=field.field_type,
        is_multiple=field.is_multiple,
        name=field.name,
        options=[],
        order=field.order,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


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


class TestFacilitatorCreatePageView:
    """Tests for /panel/event/<slug>/facilitators/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-create", kwargs={"slug": event.slug})

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
        url = reverse("panel:facilitator-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={**_base_context(event), "form": ANY, "personal_fields": []},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:facilitator-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={"display_name": "Alice"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_creates_facilitator_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"display_name": "Bob"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator created successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        assert Facilitator.objects.filter(event=event, display_name="Bob").exists()

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"display_name": ""}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={**_base_context(event), "form": ANY, "personal_fields": []},
        )
        assert response.context["form"].errors

    def test_post_creates_facilitator_with_default_accreditation(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(self.get_url(event), data={"display_name": "Bob"})

        facilitator = Facilitator.objects.get(event=event, display_name="Bob")
        assert facilitator.accreditation_type == "none"

    def test_post_creates_facilitator_with_chosen_accreditation(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
            self.get_url(event),
            data={"display_name": "Guest", "accreditation_type": "guest"},
        )

        facilitator = Facilitator.objects.get(event=event, display_name="Guest")
        assert facilitator.accreditation_type == "guest"

    def test_post_shows_accreditation_type_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data={"display_name": "Bob", "accreditation_type": "bogus"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={**_base_context(event), "form": ANY, "personal_fields": []},
        )
        assert response.context["form"].errors["accreditation_type"]
        assert response.context["form"].errors["accreditation_type"][0] in (
            response.content.decode()
        )

    def test_get_renders_personal_data_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "personal_fields": [(_field_dto(field), None)],
            },
            contains='name="personal_vegan"',
        )

    def test_post_saves_personal_data_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            self.get_url(event), data={"display_name": "Bob", "personal_vegan": "true"}
        )

        facilitator = Facilitator.objects.get(event=event, display_name="Bob")
        value = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert value.value is True
