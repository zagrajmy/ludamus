from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
)
from ludamus.pacts import EventDTO
from tests.integration.conftest import ProposalCategoryFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.get(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.pk == field.pk
        assert context_field.name == "Email"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "field": context_field,
                "form": ANY,
                "categories": [],
                "required_category_pks": set(),
                "optional_category_pks": set(),
            },
        )
        assert response.context["current_event"].pk == event.pk

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_invalid_field_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = authenticated_client.get(url)

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

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Phone", "question": "What is your phone?"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_updates_field_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(
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

    def test_post_drops_category_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        """A category pk from another event is not linked on edit."""
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        foreign_category = ProposalCategoryFactory(name="Workshop")  # different event

        response = authenticated_client.post(
            self.get_url(event, field),
            data={
                "name": "Email",
                "question": "What is your email?",
                f"category_{foreign_category.pk}": "required",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert not PersonalDataFieldRequirement.objects.filter(
            field=field, category=foreign_category
        ).exists()

    def test_post_updates_slug_on_name_change(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Phone Number", "question": "What is your phone number?"},
        )

        field.refresh_from_db()
        assert field.slug == "phone-number"

    def test_post_generates_unique_slug_on_collision(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Phone", "question": "What is your phone?"},
        )

        field.refresh_from_db()
        assert field.slug.startswith("phone-")

    def test_post_error_on_empty_name_rerenders_form(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(self.get_url(event, field), data={})

        assert response.context["form"].errors
        context_field = response.context["field"]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "field": context_field,
                "form": ANY,
                "categories": [],
                "required_category_pks": set(),
                "optional_category_pks": set(),
            },
        )
        field.refresh_from_db()
        assert field.name == "Email"  # Name unchanged

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = authenticated_client.post(
            url, data={"name": "Phone", "question": "What is your phone?"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_field_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:personal-data-field-edit",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = authenticated_client.post(
            url, data={"name": "Phone", "question": "What is your phone?"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Personal data field not found.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )

    def test_post_updates_options_on_select_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
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

        response = authenticated_client.post(
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

    def test_post_does_not_touch_options_on_text_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        authenticated_client.post(
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

    def test_get_prepopulates_options_for_select_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
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

        response = authenticated_client.get(self.get_url(event, field))

        form = response.context["form"]
        assert form.initial["options"] == "Poland\nGermany"

    def test_get_returns_field_with_is_multiple_attribute(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="What languages do you speak?",
            slug="languages",
            field_type="select",
            is_multiple=True,
        )

        response = authenticated_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.is_multiple is True

    def test_get_returns_field_with_allow_custom_attribute(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country are you from?",
            slug="country",
            field_type="select",
            allow_custom=True,
        )

        response = authenticated_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.allow_custom is True
