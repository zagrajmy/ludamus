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
from ludamus.pacts import FieldAnswer, OrganizerFieldDTO
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


def _field_dto(field):
    return OrganizerFieldDTO(
        field_type=field.field_type,
        is_multiple=field.is_multiple,
        name=field.name,
        options=[],
        order=field.order,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


class TestFacilitatorCreatePageView:
    """Tests for /panel/event/<slug>/facilitators/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-create", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:facilitator-create", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "field_descriptors": [],
            },
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={})

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={})

        assert_not_a_manager(response)

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:facilitator-create", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url, data={"display_name": "Alice"})

        assert_event_not_found(response)

    def test_post_creates_facilitator_and_redirects(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={"display_name": "Bob"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator created successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        assert Facilitator.objects.filter(event=event, display_name="Bob").exists()

    def test_post_creates_a_multi_session_facilitator(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event), data={"display_name": "Guild", "multi_session": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator created successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        assert Facilitator.objects.get(event=event, display_name="Guild").multi_session

    def test_post_shows_errors_on_invalid_data(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={"display_name": ""})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "field_descriptors": [],
            },
        )
        assert response.context["form"].errors

    def test_post_creates_facilitator_with_default_accreditation(
        self, panel_client, event
    ):
        panel_client.post(self.get_url(event), data={"display_name": "Bob"})

        facilitator = Facilitator.objects.get(event=event, display_name="Bob")
        assert facilitator.accreditation_type == "none"

    def test_post_assigns_the_creator_as_organizer_when_checked(
        self, panel_client, active_user, event
    ):
        response = panel_client.post(
            self.get_url(event), data={"display_name": "Bob", "assign_me": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator created successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        facilitator = Facilitator.objects.get(event=event, display_name="Bob")
        assert facilitator.organizer_id == active_user.pk

    def test_post_leaves_facilitator_unassigned_when_unchecked(
        self, panel_client, event
    ):
        response = panel_client.post(self.get_url(event), data={"display_name": "Bob"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator created successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        facilitator = Facilitator.objects.get(event=event, display_name="Bob")
        assert facilitator.organizer_id is None

    def test_post_creates_facilitator_with_chosen_accreditation(
        self, panel_client, event
    ):
        panel_client.post(
            self.get_url(event),
            data={"display_name": "Guest", "accreditation_type": "guest"},
        )

        facilitator = Facilitator.objects.get(event=event, display_name="Guest")
        assert facilitator.accreditation_type == "guest"

    def test_post_shows_accreditation_type_error(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event),
            data={"display_name": "Bob", "accreditation_type": "bogus"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "field_descriptors": [],
            },
        )
        assert response.context["form"].errors["accreditation_type"]
        assert response.context["form"].errors["accreditation_type"][0] in (
            response.content.decode()
        )

    def test_get_renders_personal_data_fields(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-create.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "field_descriptors": [
                    {
                        "field": _field_dto(field),
                        "name_prefix": "personal",
                        "answer": FieldAnswer(),
                    }
                ],
            },
        )

    def test_post_saves_personal_data_field_values(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        panel_client.post(
            self.get_url(event), data={"display_name": "Bob", "personal_vegan": "true"}
        )

        facilitator = Facilitator.objects.get(event=event, display_name="Bob")
        value = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert value.value is True
