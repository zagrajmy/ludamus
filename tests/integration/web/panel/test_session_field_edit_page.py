from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
)
from ludamus.pacts import EventDTO
from tests.integration.conftest import ProposalCategoryFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestSessionFieldEditPageView:
    """Tests for /panel/event/<slug>/cfp/session-fields/<field_slug>/edit/ page."""

    @staticmethod
    def get_url(event, field):
        return reverse(
            "panel:session-field-edit",
            kwargs={"slug": event.slug, "field_slug": field.slug},
        )

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        url = self.get_url(event, field)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
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
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.pk == field.pk
        assert context_field.name == "Genre"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/session-field-edit.html",
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
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        url = reverse(
            "panel:session-field-edit",
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
            "panel:session-field-edit",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session field not found.")],
            url=f"/panel/event/{event.slug}/cfp/session-fields/",
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        url = self.get_url(event, field)

        response = client.post(
            url, data={"name": "Difficulty", "question": "What difficulty level?"}
        )

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Difficulty", "question": "What difficulty level?"},
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
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.post(
            self.get_url(event, field),
            data={"name": "RPG System", "question": "What RPG system will you use?"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/session-fields/",
        )
        field.refresh_from_db()
        assert field.name == "RPG System"

    def test_post_drops_category_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        """A category pk from another event is not linked on edit."""
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        foreign_category = ProposalCategoryFactory(name="Workshop")  # different event

        response = authenticated_client.post(
            self.get_url(event, field),
            data={
                "name": "Genre",
                "question": "What genre?",
                f"category_{foreign_category.pk}": "required",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/session-fields/",
        )
        assert not SessionFieldRequirement.objects.filter(
            field=field, category=foreign_category
        ).exists()

    def test_post_updates_slug_on_name_change(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        authenticated_client.post(
            self.get_url(event, field),
            data={"name": "RPG System", "question": "What RPG system will you use?"},
        )

        field.refresh_from_db()
        assert field.slug == "rpg-system"

    def test_post_generates_unique_slug_on_collision(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Difficulty", "question": "What difficulty level?"},
        )

        field.refresh_from_db()
        assert field.slug.startswith("difficulty-")

    def test_post_error_on_empty_name_rerenders_form(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.post(self.get_url(event, field), data={})

        assert response.context["form"].errors
        context_field = response.context["field"]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/session-field-edit.html",
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
        assert field.name == "Genre"  # Name unchanged

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        url = reverse(
            "panel:session-field-edit",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = authenticated_client.post(
            url, data={"name": "Difficulty", "question": "What difficulty level?"}
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
            "panel:session-field-edit",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = authenticated_client.post(
            url, data={"name": "Difficulty", "question": "What difficulty level?"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session field not found.")],
            url=f"/panel/event/{event.slug}/cfp/session-fields/",
        )

    def test_post_updates_options_on_select_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="What genre?",
            slug="genre",
            field_type="select",
        )
        SessionFieldOption.objects.create(
            field=field, label="Fantasy", value="Fantasy", order=0
        )
        SessionFieldOption.objects.create(
            field=field, label="Sci-Fi", value="Sci-Fi", order=1
        )

        response = authenticated_client.post(
            self.get_url(event, field),
            data={
                "name": "Genre",
                "question": "What genre?",
                "options": "Horror\nMystery\nComedy",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session field updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/session-fields/",
        )
        labels = list(
            SessionFieldOption.objects.filter(field=field)
            .order_by("order")
            .values_list("label", flat=True)
        )
        assert labels == ["Horror", "Mystery", "Comedy"]

    def test_post_does_not_touch_options_on_text_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event, name="Notes", question="Any notes?", slug="notes"
        )

        authenticated_client.post(
            self.get_url(event, field),
            data={"name": "Notes", "question": "Any notes?", "options": "ignored"},
        )

        field.refresh_from_db()
        assert field.name == "Notes"
        assert not SessionFieldOption.objects.filter(field=field).exists()

    def test_get_prepopulates_options_for_select_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="What genre?",
            slug="genre",
            field_type="select",
        )
        SessionFieldOption.objects.create(
            field=field, label="Fantasy", value="Fantasy", order=0
        )
        SessionFieldOption.objects.create(
            field=field, label="Sci-Fi", value="Sci-Fi", order=1
        )

        response = authenticated_client.get(self.get_url(event, field))

        form = response.context["form"]
        assert form.initial["options"] == "Fantasy\nSci-Fi"

    def test_get_returns_field_with_is_multiple_attribute(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = SessionField.objects.create(
            event=event,
            name="Tags",
            question="What tags apply?",
            slug="tags",
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
        field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="What genre?",
            slug="genre",
            field_type="select",
            allow_custom=True,
        )

        response = authenticated_client.get(self.get_url(event, field))

        context_field = response.context["field"]
        assert context_field.allow_custom is True
