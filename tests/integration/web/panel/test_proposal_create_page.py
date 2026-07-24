"""Integration tests for /panel/event/<slug>/proposals/create/ page."""

from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.db import DataError
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldRequirement,
    SessionFieldValue,
    TimeSlot,
    Track,
)
from ludamus.links.db.django.repositories.sessions import SessionRepository
from ludamus.pacts import EventDTO, FacilitatorListItemDTO, TimeSlotDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response, checkbox_tag

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _fields_context(event):
    # The create page resolves a category up front so the session fields it
    # renders match the one preselected in the picker.
    return {
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
        "proposal": None,
        "facilitator_error": False,
        "all_facilitators": [],
        "assigned_facilitator_pks": set(),
        "all_tracks": [],
        "assigned_track_pks": set(),
        "all_time_slots": [],
        "assigned_time_slot_pks": set(),
        "facilitator_personal_data": [],
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
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
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

        # Search-first picker: unselected facilitators start hidden.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data=ANY,
            contains=[
                'name="facilitator_ids"',
                f'value="{facilitator.pk}"',
                "Alice",
                'id="facilitator-search"',
                (
                    "facilitator-row flex items-center text-sm py-3 rounded-md"
                    " hover:bg-foreground/5 hidden"
                ),
            ],
        )

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
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "display_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
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
                "facilitators_submitted": "1",
                "title": "Missing Facilitator",
                "display_name": "Test Host",
            },
        )

        # The form itself is valid; the "at least one facilitator" invariant is
        # enforced by the view and surfaced next to the picker.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data=ANY,
            contains=[
                'name="facilitator_ids"',
                "Please select at least one facilitator.",
            ],
        )
        assert not Session.objects.filter(title="Missing Facilitator").exists()

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
                "facilitators_submitted": "1",
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
                "facilitators_submitted": "1",
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

    def test_get_renders_time_slot_checkboxes(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
                "form": ANY,
                "all_time_slots": [TimeSlotDTO.model_validate(slot)],
            },
            contains='name="time_slot_ids"',
        )

    def test_post_creates_session_with_preferred_time_slots(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        authenticated_client.post(
            self.get_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Slotted Session",
                "display_name": "Test Host",
                "time_slots_submitted": "1",
                "time_slot_ids": [slot.pk],
            },
        )

        new_session = Session.objects.get(title="Slotted Session")
        assert list(new_session.time_slots.values_list("pk", flat=True)) == [slot.pk]

    def test_post_ignores_time_slot_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        other_event = EventFactory(sphere=sphere)
        foreign_slot = TimeSlot.objects.create(
            event=other_event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        authenticated_client.post(
            self.get_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Slotted Session",
                "display_name": "Test Host",
                "time_slots_submitted": "1",
                "time_slot_ids": [foreign_slot.pk],
            },
        )

        new_session = Session.objects.get(title="Slotted Session")
        assert not new_session.time_slots.exists()

    def test_post_invalid_keeps_selected_time_slot_checked(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "category_id": category.pk,
                "display_name": "Test Host",
                "time_slots_submitted": "1",
                "time_slot_ids": [slot.pk],
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
                "form": ANY,
                "all_time_slots": [TimeSlotDTO.model_validate(slot)],
                "assigned_time_slot_pks": {slot.pk},
                "facilitator_error": True,
            },
        )
        content = response.content.decode()
        assert "checked" in checkbox_tag(content, "time_slot_ids", slot.pk)

    def test_get_renders_track_checkboxes(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data=ANY,
            contains=[
                'name="tracks_submitted"',
                'name="track_ids"',
                f'value="{track.pk}"',
                "Main Track",
            ],
        )

    def test_post_creates_session_with_tracks(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        authenticated_client.post(
            self.get_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Tracked Session",
                "display_name": "Test Host",
                "tracks_submitted": "1",
                "track_ids": [track.pk],
            },
        )

        new_session = Session.objects.get(title="Tracked Session")
        assert list(new_session.tracks.values_list("pk", flat=True)) == [track.pk]

    def test_post_ignores_track_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        other_event = EventFactory(sphere=sphere)
        foreign_track = Track.objects.create(
            event=other_event, name="Foreign", slug="foreign", is_public=True
        )

        authenticated_client.post(
            self.get_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Tracked Session",
                "display_name": "Test Host",
                "tracks_submitted": "1",
                "track_ids": [foreign_track.pk],
            },
        )

        new_session = Session.objects.get(title="Tracked Session")
        assert not new_session.tracks.exists()

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
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
                "form": ANY,
                "facilitator_error": True,
            },
        )
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
                "facilitators_submitted": "1",
                "facilitator_ids": [foreign.pk],
                "category_id": category.pk,
                "title": "Foreign Facilitator",
                "display_name": "Test Host",
            },
        )

        # The foreign facilitator is filtered out as not event-scoped, leaving
        # zero facilitators — the view blocks creation.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
                "events": [
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
                "form": ANY,
                "facilitator_error": True,
            },
        )
        assert not Session.objects.filter(title="Foreign Facilitator").exists()

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.post(
            self.get_url(event),
            data={"category_id": "", "title": "", "display_name": ""},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            # An empty category_id falls back to the event's first category, so
            # the form still renders that category's fields alongside the error.
            context_data={
                **_base_context(event),
                **_fields_context(event),
                "form": ANY,
                "facilitator_error": True,
            },
        )
        assert response.context["form"].errors

    @pytest.mark.postgres
    def test_post_second_same_title_session_saves(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        slug_max_length = 50
        submissions = 2
        title = "Midnight Heist One-Shot Adventure For New Players"
        data = {
            "facilitators_submitted": "1",
            "facilitator_ids": [facilitator.pk],
            "category_id": category.pk,
            "title": title,
            "display_name": "Test Host",
        }

        for _ in range(submissions):
            authenticated_client.post(self.get_url(event), data=data)

        sessions = Session.objects.filter(title=title)
        assert sessions.count() == submissions
        assert all(len(session.slug) <= slug_max_length for session in sessions)

    def test_post_surfaces_db_error_as_form_error(
        self, authenticated_client, active_user, sphere, event, monkeypatch
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        def _raise(*_args, **_kwargs):
            raise DataError("value too long for type character varying(50)")

        monkeypatch.setattr(SessionRepository, "create", _raise)

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Boom",
                "display_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **_base_context(event),
                **_fields_context(event),
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
            messages=[
                (
                    messages.ERROR,
                    "Couldn't save the session. Please check your input and try again.",
                )
            ],
        )
        assert not Session.objects.filter(title="Boom").exists()


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
            # The component renders without page chrome, so no active_nav.
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
                "field_descriptors": ANY,
                "form": ANY,
                "orphan_values": [],
                "fields_url": self.get_fields_url(event),
            },
            contains='name="session_only-b"',
            not_contains='name="session_only-a"',
        )

    def test_get_renders_checkbox_field_with_allow_custom_without_companion(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="A", slug="a")
        field = SessionField.objects.create(
            event=event,
            name="Streamed",
            question="Stream this session?",
            slug="streamed",
            field_type="checkbox",
            allow_custom=True,
            order=0,
        )
        SessionFieldRequirement.objects.create(
            category=category, field=field, is_required=False, order=0
        )

        response = authenticated_client.get(self.get_url(event))

        html = response.content.decode()
        assert response.status_code == HTTPStatus.OK
        assert 'name="session_streamed"' in html
        assert 'name="session_streamed_custom"' not in html

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
                "field_descriptors": [],
                "form": ANY,
                "orphan_values": [],
                "fields_url": self.get_fields_url(event),
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
                "facilitators_submitted": "1",
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
                "facilitators_submitted": "1",
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
