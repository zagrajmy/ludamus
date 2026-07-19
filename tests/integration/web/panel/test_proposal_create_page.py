"""Integration tests for /panel/event/<slug>/proposals/create/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldRequirement,
    SessionFieldValue,
)
from ludamus.pacts import EventDTO, FacilitatorListItemDTO, ProposalCategoryDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response, checkbox_tag

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _fields_context(event, category):
    # The create page resolves a category up front so the session fields it
    # renders match the one preselected in the picker.
    return {
        "category": ProposalCategoryDTO.model_validate(category),
        "field_descriptors": [],
        "orphan_values": [],
        "fields_url": reverse(
            "panel:proposal-create-fields", kwargs={"slug": event.slug}
        ),
    }


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
        "active_nav": "proposals",
        "all_facilitators": [],
        "assigned_facilitator_pks": set(),
    }


class TestProposalCreatePageView:
    """Tests for /panel/event/<slug>/proposals/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:proposal-create", kwargs={"slug": event.slug})

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

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:proposal-create", kwargs={"slug": "nonexistent"})

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
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={
                **_base_context(event),
                **_fields_context(event, category),
                "form": ANY,
            },
        )

    def test_get_renders_facilitator_checkboxes_when_event_has_facilitators(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert 'name="facilitator_ids"' in content
        assert f'value="{facilitator.pk}"' in content
        assert "Alice" in content
        # Search-first picker: unselected facilitators start hidden.
        assert 'id="facilitator-search"' in content
        assert "facilitator-row flex items-center text-sm hidden" in content

    def test_post_invalid_keeps_selected_facilitator_checked(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "category_id": category.pk,
                "facilitator_ids": [facilitator.pk],
                "display_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={
                **_base_context(event),
                **_fields_context(event, category),
                "form": ANY,
                "all_facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=facilitator.pk,
                        session_count=0,
                        slug="alice",
                        user_id=None,
                    )
                ],
                "assigned_facilitator_pks": {facilitator.pk},
            },
        )
        content = response.content.decode()
        assert "checked" in checkbox_tag(content, "facilitator_ids", facilitator.pk)

    def test_post_renders_facilitator_error_with_checkboxes(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "category_id": category.pk,
                "title": "Missing Facilitator",
                "display_name": "Test Host",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"].errors
        content = response.content.decode()
        assert 'name="facilitator_ids"' in content
        assert response.context["form"]["facilitator_ids"].errors[0] in content

    # POST tests

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
        url = reverse("panel:proposal-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_creates_session_with_unique_slug_on_collision(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=None,
            display_name="Host",
            title="Existing Session",
            slug="my-new-session",
            participants_limit=0,
            status="pending",
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "My New Session",
                "display_name": "Test Host",
                "description": "",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = Session.objects.get(title="My New Session", status="pending")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert new_session.slug != "my-new-session"

    def test_post_creates_session_with_facilitator_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "My New Session",
                "display_name": "Test Host",
                "description": "A great session",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = Session.objects.get(title="My New Session", status="pending")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert list(new_session.facilitators.values_list("pk", flat=True)) == [
            facilitator.pk
        ]

    def test_post_without_facilitator_shows_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "category_id": category.pk,
                "title": "No Facilitator",
                "display_name": "Test Host",
                "description": "A great session",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={
                **_base_context(event),
                **_fields_context(event, category),
                "form": ANY,
            },
        )
        assert response.context["form"].errors
        assert not Session.objects.filter(title="No Facilitator").exists()

    def test_post_ignores_facilitator_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        other_event = EventFactory(sphere=sphere)
        foreign = Facilitator.objects.create(
            event=other_event, display_name="Bob", slug="bob", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [foreign.pk],
                "category_id": category.pk,
                "title": "Foreign Facilitator",
                "display_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={
                **_base_context(event),
                **_fields_context(event, category),
                "events": [
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
                "form": ANY,
            },
        )
        assert response.context["form"].errors
        assert not Session.objects.filter(title="Foreign Facilitator").exists()

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.post(
            self.get_url(event),
            data={"category_id": "", "title": "", "display_name": ""},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            # An empty category_id falls back to the event's first category, so
            # the form still renders that category's fields alongside the error.
            context_data={
                **_base_context(event),
                **_fields_context(event, category),
                "form": ANY,
            },
        )
        assert response.context["form"].errors


class TestProposalCreateCategoryFields:
    """The create form renders and saves the fields its category configures."""

    @staticmethod
    def get_url(event):
        return reverse("panel:proposal-create", kwargs={"slug": event.slug})

    @staticmethod
    def get_fields_url(event):
        return reverse("panel:proposal-create-fields", kwargs={"slug": event.slug})

    @staticmethod
    def _category_with_field(event, *, name, slug, field_slug, is_required=False):
        category = ProposalCategory.objects.create(event=event, name=name, slug=slug)
        field = SessionField.objects.create(
            event=event,
            name=field_slug.title(),
            question=f"Question for {field_slug}?",
            slug=field_slug,
            field_type="text",
            order=0,
        )
        SessionFieldRequirement.objects.create(
            category=category, field=field, is_required=is_required, order=0
        )
        return category, field

    def test_get_renders_only_the_resolved_categorys_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        self._category_with_field(event, name="A", slug="a", field_slug="only-a")
        self._category_with_field(event, name="B", slug="b", field_slug="only-b")

        response = authenticated_client.get(self.get_url(event))

        # Category A is the event's first category, so only its field renders.
        html = response.content.decode()
        assert 'name="session_only-a"' in html
        assert 'name="session_only-b"' not in html
        # The picker must be wired to swap the fields block on change.
        assert f'hx-get="{self.get_fields_url(event)}"' in html
        assert 'hx-target="#proposal-session-fields"' in html
        assert 'id="proposal-session-fields"' in html

    def test_get_fields_component_follows_the_requested_category(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        self._category_with_field(event, name="A", slug="a", field_slug="only-a")
        category_b, _field = self._category_with_field(
            event, name="B", slug="b", field_slug="only-b"
        )

        response = authenticated_client.get(
            self.get_fields_url(event), data={"category_id": category_b.pk}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/proposal-session-fields.html",
            # field_descriptors carry BoundFields, which don't compare usefully.
            context_data={
                "field_descriptors": ANY,
                "form": ANY,
                "category": ProposalCategoryDTO.model_validate(category_b),
                "orphan_values": [],
            },
            contains='name="session_only-b"',
            not_contains='name="session_only-a"',
        )

    def test_get_fields_component_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:proposal-create-fields", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_fields_component_renders_empty_when_event_has_no_categories(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_fields_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/proposal-session-fields.html",
            context_data={
                "field_descriptors": [],
                "form": ANY,
                "category": None,
                "orphan_values": [],
            },
        )

    def test_post_saves_the_categorys_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category, field = self._category_with_field(
            event, name="RPG", slug="rpg", field_slug="system"
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Saved Fields",
                "display_name": "Test Host",
                "session_system": "Pathfinder",
            },
        )

        session = Session.objects.get(title="Saved Fields")
        value = SessionFieldValue.objects.get(session=session, field=field)
        assert value.value == "Pathfinder"

    def test_post_rejects_missing_required_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category, _field = self._category_with_field(
            event, name="RPG", slug="rpg", field_slug="system", is_required=True
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Missing Required",
                "display_name": "Test Host",
                "session_system": "",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert "session_system" in response.context["form"].errors
        assert not Session.objects.filter(title="Missing Required").exists()

    def test_get_offers_the_categorys_durations_as_choices(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(
            event=event, name="RPG", slug="rpg", durations=["PT1H", "PT2H"]
        )

        response = authenticated_client.get(self.get_url(event))

        duration = response.context["form"].fields["duration"]
        assert duration.choices == [("", "---"), ("PT1H", "1h"), ("PT2H", "2h")]
        assert 'value="PT1H"' in response.content.decode()

    def test_get_keeps_free_text_duration_without_configured_durations(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.get(self.get_url(event))

        duration = response.context["form"].fields["duration"]
        assert not hasattr(duration, "choices")
        assert 'name="duration"' in response.content.decode()
