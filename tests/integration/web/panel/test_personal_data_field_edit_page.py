from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import PersonalDataField, PersonalDataFieldOption
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


class TestPersonalDataFieldEditPageView:
    """Tests for /panel/event/<slug>/cfp/personal-data/<field_slug>/edit/ page."""

    @staticmethod
    def get_url(event, field):
        return reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": event.slug, "field_slug": field.slug},
        )

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = self.get_url(event, field)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.get(self.get_url(event, field))

        assert_not_a_manager(response)

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = panel_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.pk == field.pk
        assert context_field.name == "Email"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-edit.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "field": context_field,
                "form": ANY,
            },
        )
        assert response.context["current_event"].pk == event.pk

    def test_get_redirects_on_invalid_event_slug(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_redirects_on_invalid_field_slug(self, panel_client, event):
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = panel_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Personal data field not found.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = self.get_url(event, field)

        response = client.post(
            url, data={"name": "Phone", "question": "What is your phone?"}
        )

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Phone", "question": "What is your phone?"},
        )

        assert_not_a_manager(response)

    def test_post_updates_field_name(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={"name": "Phone Number", "question": "What is your phone number?"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        field.refresh_from_db()
        assert field.name == "Phone Number"

    def test_get_prepopulates_required_flag_and_order(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="What is your email?",
            slug="email",
            is_required=True,
            order=4,
        )

        response = panel_client.get(self.get_url(event, field))

        form = response.context["form"]
        assert form.initial["is_required"] is True
        assert form.initial["order"] == 1 + 1 + 1 + 1

    def test_post_saves_required_flag_and_order(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={
                "name": "Email",
                "question": "What is your email?",
                "is_required": "on",
                "order": 2,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        field.refresh_from_db()
        assert field.is_required is True
        assert field.order == 1 + 1

    def test_post_clears_required_flag_when_unchecked(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="What is your email?",
            slug="email",
            is_required=True,
        )

        panel_client.post(
            self.get_url(event, field),
            data={"name": "Email", "question": "What is your email?"},
        )

        field.refresh_from_db()
        assert field.is_required is False

    def test_post_rejects_required_on_checkbox_field(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Consent",
            question="Do you agree?",
            slug="consent",
            field_type="checkbox",
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={"name": "Consent", "question": "Do you agree?", "is_required": "on"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-edit.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "field": response.context["field"],
                "form": FormErrorsMatcher(
                    is_required=["A checkbox cannot be required."],
                    __all__=["A checkbox cannot be required."],
                ),
            },
        )
        field.refresh_from_db()
        assert field.is_required is False

    def test_post_updates_slug_on_name_change(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        panel_client.post(
            self.get_url(event, field),
            data={"name": "Phone Number", "question": "What is your phone number?"},
        )

        field.refresh_from_db()
        assert field.slug == "phone-number"

    def test_post_generates_unique_slug_on_collision(self, panel_client, event):
        PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        panel_client.post(
            self.get_url(event, field),
            data={"name": "Phone", "question": "What is your phone?"},
        )

        field.refresh_from_db()
        assert field.slug.startswith("phone-")

    def test_post_error_on_empty_name_rerenders_form(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = panel_client.post(self.get_url(event, field), data={})

        assert response.context["form"].errors
        context_field = response.context["field"]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-edit.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "field": context_field,
                "form": ANY,
            },
        )
        field.refresh_from_db()
        assert field.name == "Email"  # Name unchanged

    def test_post_redirects_on_invalid_event_slug(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = panel_client.post(
            url, data={"name": "Phone", "question": "What is your phone?"}
        )

        assert_event_not_found(response)

    def test_post_redirects_on_invalid_field_slug(self, panel_client, event):
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = panel_client.post(
            url, data={"name": "Phone", "question": "What is your phone?"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Personal data field not found.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )

    def test_post_updates_options_on_select_field(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country?",
            slug="country",
            field_type="select",
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Poland", value="Poland", order=0
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Germany", value="Germany", order=1
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={
                "name": "Country",
                "question": "What country?",
                "options": "France\nSpain\nItaly",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        labels = list(
            PersonalDataFieldOption.objects.filter(field=field)
            .order_by("order")
            .values_list("label", flat=True)
        )
        assert labels == ["France", "Spain", "Italy"]

    def test_post_does_not_touch_options_on_text_field(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        panel_client.post(
            self.get_url(event, field),
            data={
                "name": "Email",
                "question": "What is your email?",
                "options": "ignored",
            },
        )

        field.refresh_from_db()
        assert field.name == "Email"
        assert not PersonalDataFieldOption.objects.filter(field=field).exists()

    def test_get_prepopulates_options_for_select_field(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country?",
            slug="country",
            field_type="select",
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Poland", value="Poland", order=0
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Germany", value="Germany", order=1
        )

        response = panel_client.get(self.get_url(event, field))

        form = response.context["form"]
        assert form.initial["options"] == "Poland\nGermany"

    def test_get_prepopulates_multi_and_custom_toggles_for_select_field(
        self, panel_client, event
    ):
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country?",
            slug="country",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
        )

        response = panel_client.get(self.get_url(event, field))

        form = response.context["form"]
        assert form.initial["is_multiple"] is True
        assert form.initial["allow_custom"] is True

    def test_post_enables_multiple_selection_on_select_field(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country?",
            slug="country",
            field_type="select",
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={
                "name": "Country",
                "question": "What country?",
                "options": "Poland\nGermany",
                "is_multiple": "on",
                "allow_custom": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        field.refresh_from_db()
        assert field.is_multiple is True
        assert field.allow_custom is True

    def test_post_disables_multiple_selection_when_unchecked(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country?",
            slug="country",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={
                "name": "Country",
                "question": "What country?",
                "options": "Poland\nGermany",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        field.refresh_from_db()
        assert field.is_multiple is False
        assert field.allow_custom is False

    def test_post_ignores_multi_toggle_on_text_field(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = panel_client.post(
            self.get_url(event, field),
            data={
                "name": "Email",
                "question": "What is your email?",
                "is_multiple": "on",
                "allow_custom": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        field.refresh_from_db()
        assert field.is_multiple is False
        assert field.allow_custom is False

    def test_get_returns_field_with_is_multiple_attribute(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="What languages do you speak?",
            slug="languages",
            field_type="select",
            is_multiple=True,
        )

        response = panel_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.is_multiple is True

    def test_get_returns_field_with_allow_custom_attribute(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country are you from?",
            slug="country",
            field_type="select",
            allow_custom=True,
        )

        response = panel_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.allow_custom is True
