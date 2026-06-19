from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    PersonalDataField,
    PersonalDataFieldRequirement,
)
from ludamus.pacts import EventDTO
from tests.integration.conftest import ProposalCategoryFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestPersonalDataFieldCreatePageView:
    """Tests for /panel/event/<slug>/cfp/personal-data/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:personal-data-field-create", kwargs={"slug": event.slug})

    # GET tests

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

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-create.html",
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
                "categories": [],
                "form": ANY,
                "required_category_pks": set(),
                "optional_category_pks": set(),
            },
        )
        assert response.context["current_event"].pk == event.pk

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:personal-data-field-create", kwargs={"slug": "nonexistent"}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(
            url, data={"name": "Email", "question": "What is your email?"}
        )

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_creates_field_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
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

    def test_post_generates_slug_from_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
            self.get_url(event),
            data={"name": "Phone Number", "question": "What is your phone number?"},
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.slug == "phone-number"

    def test_post_generates_unique_slug_on_collision(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        authenticated_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        fields = PersonalDataField.objects.filter(event=event)
        assert fields.count() == 1 + 1  # existing + new
        new_field = fields.exclude(slug="email").first()
        assert new_field.slug.startswith("email-")

    def test_post_error_on_empty_name_rerenders_form(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={})

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-field-create.html",
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
                "categories": [],
                "form": ANY,
                "required_category_pks": set(),
                "optional_category_pks": set(),
            },
        )
        assert not PersonalDataField.objects.filter(event=event).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:personal-data-field-create", kwargs={"slug": "nonexistent"}
        )

        response = authenticated_client.post(
            url, data={"name": "Email", "question": "What is your email?"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_creates_text_field_by_default(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        field = PersonalDataField.objects.get(event=event)
        assert field.field_type == "text"

    def test_post_creates_select_field_with_options(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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

    def test_post_ignores_options_for_text_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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

    def test_post_creates_select_field_with_is_multiple_true(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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

    def test_post_ignores_is_multiple_for_text_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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

    def test_post_ignores_allow_custom_for_text_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(
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

    # Category assignment tests

    def test_get_includes_categories_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategoryFactory(event=event, name="Workshop")
        ProposalCategoryFactory(event=event, name="Talk")

        response = authenticated_client.get(self.get_url(event))

        assert len(response.context["categories"]) == 1 + 1  # Workshop + Talk

    def test_post_with_category_assignments_creates_requirements(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        cat1 = ProposalCategoryFactory(event=event, name="Workshop")
        cat2 = ProposalCategoryFactory(event=event, name="Talk")

        authenticated_client.post(
            self.get_url(event),
            data={
                "name": "Email",
                "question": "What is your email?",
                f"category_{cat1.pk}": "required",
                f"category_{cat2.pk}": "optional",
            },
        )

        field = PersonalDataField.objects.get(event=event)
        reqs = {
            r.category_id: r.is_required
            for r in PersonalDataFieldRequirement.objects.filter(field=field)
        }
        assert reqs == {cat1.pk: True, cat2.pk: False}

    def test_post_without_category_assignments_creates_no_requirements(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategoryFactory(event=event, name="Workshop")

        authenticated_client.post(
            self.get_url(event),
            data={"name": "Email", "question": "What is your email?"},
        )

        field = PersonalDataField.objects.get(event=event)
        assert not PersonalDataFieldRequirement.objects.filter(field=field).exists()

    def test_post_drops_category_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        """A category pk from another event is not linked to the new field."""
        sphere.managers.add(active_user)
        foreign_category = ProposalCategoryFactory(name="Workshop")  # different event

        authenticated_client.post(
            self.get_url(event),
            data={
                "name": "Email",
                "question": "What is your email?",
                f"category_{foreign_category.pk}": "required",
            },
        )

        field = PersonalDataField.objects.get(event=event)
        assert not PersonalDataFieldRequirement.objects.filter(
            field=field, category=foreign_category
        ).exists()
