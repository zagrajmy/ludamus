from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import PersonalDataField
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_login_required,
    assert_response,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


class TestPersonalDataFieldCreatePageView:
    """Tests for /panel/event/<slug>/cfp/personal-data/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:personal-data-field-create", kwargs={"slug": event.slug})

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-create.html",
            context_data={**panel_context(event, active_nav="cfp"), "form": ANY},
        )
        assert response.context["current_event"].pk == event.pk

    def test_get_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse(
            "panel:personal-data-field-create", kwargs={"slug": "nonexistent"}
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(
            url, data={"name": "Email", "question": "What is your email?"}
        )

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        assert_not_a_manager(response)

    def test_post_creates_field_for_sphere_manager(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert PersonalDataField.objects.filter(event=event, name="Email").exists()

    def test_post_generates_slug_from_name(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={"name": "Phone Number", "question": "What is your phone number?"},
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.slug == "phone-number"

    def test_post_generates_unique_slug_on_collision(self, panel_client, event):
        PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        panel_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        fields = PersonalDataField.objects.filter(event=event)
        assert fields.count() == 1 + 1  # existing + new
        new_field = fields.exclude(slug="email").first()
        assert new_field.slug.startswith("email-")

    def test_post_error_on_empty_name_rerenders_form(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={})

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-create.html",
            context_data={**panel_context(event, active_nav="cfp"), "form": ANY},
        )
        assert not PersonalDataField.objects.filter(event=event).exists()

    def test_post_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse(
            "panel:personal-data-field-create", kwargs={"slug": "nonexistent"}
        )

        response = panel_client.post(
            url, data={"name": "Email", "question": "What is your email?"}
        )

        assert_event_not_found(response)

    def test_post_creates_text_field_by_default(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "text"

    def test_post_creates_select_field_with_options(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Country",
                "question": "What country are you from?",
                "field_type": "select",
                "options": "Poland\nGermany\nFrance",
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "select"
        options = list(field.options.all())
        assert len(options) == 1 + 1 + 1  # Poland + Germany + France
        assert options[0].label == "Poland"
        assert options[0].value == "Poland"
        assert options[1].label == "Germany"
        assert options[2].label == "France"

    def test_post_ignores_options_for_text_field(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Email",
                "question": "What is your email?",
                "field_type": "text",
                "options": "Option1\nOption2",
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "text"
        assert field.options.count() == 0

    def test_post_creates_field_with_is_multiple_false_by_default(
        self, panel_client, event
    ):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Country",
                "question": "What country are you from?",
                "field_type": "select",
                "options": "Poland\nGermany",
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.is_multiple is False

    def test_post_creates_select_field_with_is_multiple_true(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Languages",
                "question": "What languages do you speak?",
                "field_type": "select",
                "options": "English\nPolish\nGerman",
                "is_multiple": True,
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "select"
        assert field.is_multiple is True

    def test_post_ignores_is_multiple_for_text_field(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Email",
                "question": "What is your email?",
                "field_type": "text",
                "is_multiple": True,
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "text"
        assert field.is_multiple is False

    def test_post_creates_field_with_allow_custom_false_by_default(
        self, panel_client, event
    ):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Country",
                "question": "What country are you from?",
                "field_type": "select",
                "options": "Poland\nGermany",
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.allow_custom is False

    def test_post_creates_select_field_with_allow_custom_true(
        self, panel_client, event
    ):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Country",
                "question": "What country are you from?",
                "field_type": "select",
                "options": "Poland\nGermany",
                "allow_custom": True,
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "select"
        assert field.allow_custom is True

    def test_post_ignores_allow_custom_for_text_field(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Email",
                "question": "What is your email?",
                "field_type": "text",
                "allow_custom": True,
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "text"
        assert field.allow_custom is False

    # Required and order tests

    def test_post_creates_optional_field_by_default(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.is_required is False
        assert field.order == 0

    def test_post_saves_required_flag_and_order(self, panel_client, event):
        panel_client.post(
            self.get_url(event),
            data={
                "name": "Email",
                "question": "What is your email?",
                "is_required": True,
                "order": 3,
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.is_required is True
        assert field.order == 1 + 1 + 1

    def test_post_rejects_required_checkbox(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event),
            data={
                "name": "Consent",
                "question": "Do you agree?",
                "field_type": "checkbox",
                "is_required": True,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-create.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "form": FormErrorsMatcher(
                    is_required=["A checkbox cannot be required."]
                ),
            },
        )
        assert not PersonalDataField.objects.filter(event=event).exists()
