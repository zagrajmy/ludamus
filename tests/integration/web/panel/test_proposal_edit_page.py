"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/edit/ page."""

from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Facilitator,
    HostPersonalData,
    Notification,
    PersonalDataField,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
    TimeSlot,
    Track,
)
from ludamus.pacts import EventDTO, SessionDTO
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    EventFactory,
    SpaceFactory,
    UserFactory,
    VenueFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_session(event, **kwargs):
    category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
    defaults = {
        "event": event,
        "category": category,
        "presenter": None,
        "display_name": "Test Host",
        "title": "Test Session",
        "slug": "test-session",
        "participants_limit": 5,
        "status": "pending",
        "description": "A description",
        "requirements": "Some requirements",
        "needs": "Some needs",
        "contact_email": "host@example.com",
        "min_age": 0,
    }
    defaults.update(kwargs)
    return Session.objects.create(**defaults)


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
    }


class TestProposalEditPageView:
    """Tests for /panel/event/<slug>/proposals/<proposal_id>/edit/ page."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-edit",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        session = _make_session(event)
        url = self.get_url(event, session.pk)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        session = _make_session(event)

        response = authenticated_client.get(self.get_url(event, session.pk))

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
            "panel:proposal-edit", kwargs={"slug": "nonexistent", "proposal_id": 1}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_redirects_when_proposal_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, 99999))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_get_redirects_when_proposal_belongs_to_different_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        session = _make_session(other_event)
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-edit.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "form": ANY,
                "all_facilitators": [],
                "assigned_facilitator_pks": set(),
                "session_fields": [],
                "all_tracks": [],
                "assigned_track_pks": set(),
                "all_time_slots": [],
                "assigned_time_slot_pks": set(),
                "facilitator_personal_data": [],
            },
        )

    def test_get_does_not_render_legacy_requirements_needs_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-edit.html",
            context_data=ANY,
            not_contains=[
                'name="requirements"',
                'name="needs"',
                "Some requirements",
                "Some needs",
            ],
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        session = _make_session(event)
        url = self.get_url(event, session.pk)

        response = client.post(url, data={"title": "New Title", "display_name": "Host"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        session = _make_session(event)

        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={"title": "New Title", "display_name": "Host"},
        )

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
        url = reverse(
            "panel:proposal-edit", kwargs={"slug": "nonexistent", "proposal_id": 1}
        )

        response = authenticated_client.post(url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_redirects_when_proposal_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event, 99999), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        session = _make_session(other_event)

        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={"title": "Updated", "display_name": "Host"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_post_updates_session_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        new_limit = 10
        new_min_age = 18
        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "display_name": "New Host",
                "description": "Updated description",
                "contact_email": "",
                "participants_limit": new_limit,
                "min_age": new_min_age,
                "duration": "2h",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.title == "Updated Title"
        assert session.display_name == "New Host"
        assert session.description == "Updated description"
        assert session.participants_limit == new_limit
        assert session.min_age == new_min_age
        assert session.duration == "2h"

    def test_post_reassigns_category(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        new_category = ProposalCategory.objects.create(
            event=event, name="Board games", slug="board-games"
        )

        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": new_category.pk,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.category_id == new_category.pk

    def test_post_ignores_category_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        original_category_id = session.category_id
        other_event = EventFactory(sphere=sphere)
        foreign_category = ProposalCategory.objects.create(
            event=other_event, name="Foreign", slug="foreign"
        )

        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": foreign_category.pk,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-edit.html",
            context_data=ANY,
        )
        assert response.context["form"].errors
        session.refresh_from_db()
        assert session.category_id == original_category_id

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_raising_capacity_promotes_waiter(
        self, authenticated_client, active_user, sphere, event, waiter
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, participants_limit=1)
        space = SpaceFactory(area=AreaFactory(venue=VenueFactory(event=event)))
        AgendaItemFactory(session=session, space=space)
        filler = UserFactory(username="filler", email="filler@example.com")
        SessionParticipation.objects.create(
            session=session, user=filler, status=SessionParticipationStatus.CONFIRMED
        )
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        raised_limit = 2
        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "display_name": "Host",
                "description": "d",
                "contact_email": "",
                "participants_limit": raised_limit,
                "min_age": 0,
                "duration": "2h",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.participants_limit == raised_limit
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()

    def test_post_uploads_cover_image(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        image = SimpleUploadedFile("cover.png", PNG_BYTES, content_type="image/png")

        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "display_name": "New Host",
                "cover_image": image,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.cover_image
        assert session.cover_image_url.startswith("/media/sessions/")

    def test_post_clears_cover_image(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        session.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        session.save()
        storage = session.cover_image.storage
        old_name = session.cover_image.name

        response = authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "display_name": "New Host",
                "cover_image-clear": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert not session.cover_image
        assert not storage.exists(old_name)

    def test_post_assigns_facilitators(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "facilitators_submitted": "1",
                "facilitator_ids": [alice.pk],
            },
        )

        assert list(session.facilitators.values_list("pk", flat=True)) == [alice.pk]

    def test_post_assigns_tracks(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "tracks_submitted": "1",
                "track_ids": [track.pk],
            },
        )

        assert list(session.tracks.values_list("pk", flat=True)) == [track.pk]

    def test_post_ignores_track_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        other_event = EventFactory(sphere=sphere)
        foreign_track = Track.objects.create(
            event=other_event, name="Foreign", slug="foreign", is_public=True
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "tracks_submitted": "1",
                "track_ids": [foreign_track.pk],
            },
        )

        assert not session.tracks.exists()

    def test_partial_post_without_tracks_marker_preserves_tracks(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        session.tracks.add(track)

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert list(session.tracks.values_list("pk", flat=True)) == [track.pk]

    def test_post_assigns_time_slots(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "time_slots_submitted": "1",
                "time_slot_ids": [slot.pk],
            },
        )

        assert list(session.time_slots.values_list("pk", flat=True)) == [slot.pk]

    def test_post_ignores_time_slot_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        other_event = EventFactory(sphere=sphere)
        foreign_slot = TimeSlot.objects.create(
            event=other_event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "time_slots_submitted": "1",
                "time_slot_ids": [foreign_slot.pk],
            },
        )

        assert not session.time_slots.exists()

    def test_post_clears_time_slots_when_marker_present_and_none_selected(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        session.time_slots.add(slot)

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "time_slots_submitted": "1",
            },
        )

        assert not session.time_slots.exists()

    def test_partial_post_without_time_slots_marker_preserves_time_slots(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        session.time_slots.add(slot)

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert list(session.time_slots.values_list("pk", flat=True)) == [slot.pk]

    def test_get_renders_facilitator_personal_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        PersonalDataField.objects.create(
            event=event,
            name="Nickname",
            question="Your nickname?",
            slug="nick",
            field_type="text",
            order=0,
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-edit.html",
            context_data=ANY,
            contains=["Alice", f'name="facilitator_{facilitator.pk}_personal_nick"'],
        )

    def test_post_saves_facilitator_personal_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_vegan": "true",
            },
        )

        hpd = HostPersonalData.objects.get(facilitator=facilitator, field=field)
        assert hpd.value is True

    def test_post_ignores_personal_data_for_facilitator_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        other_event = EventFactory(sphere=sphere)
        foreign_facilitator = Facilitator.objects.create(
            event=other_event, display_name="Bob", slug="bob", user=None
        )
        PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "display_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [foreign_facilitator.pk],
                f"facilitator_{foreign_facilitator.pk}_personal_vegan": "true",
            },
        )

        assert not HostPersonalData.objects.filter(
            facilitator=foreign_facilitator
        ).exists()

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        response = authenticated_client.post(
            self.get_url(event, session.pk), data={"title": "", "display_name": ""}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-edit.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "form": ANY,
                "all_facilitators": [],
                "assigned_facilitator_pks": set(),
                "session_fields": [],
                "all_tracks": [],
                "assigned_track_pks": set(),
                "all_time_slots": [],
                "assigned_time_slot_pks": set(),
                "facilitator_personal_data": [],
            },
        )
        assert response.context["form"].errors

    def test_post_saves_checkbox_session_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="18+",
            question="Is this session 18+?",
            slug="adult",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_fields_submitted": "1",
                "session_field_adult": "true",
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value is True

    def test_post_saves_multiple_session_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="Genres",
            question="Which genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
            order=0,
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_fields_submitted": "1",
                "session_field_genres": ["horror", "comedy"],
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == ["horror", "comedy"]

    def test_post_saves_allow_custom_session_field_from_custom_input(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="text",
            allow_custom=True,
            order=0,
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_fields_submitted": "1",
                "session_field_system": "",
                "session_field_system_custom": "Homebrew",
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == "Homebrew"

    def test_get_renders_all_session_field_types(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        genres = SessionField.objects.create(
            event=event,
            name="Genres",
            question="Which genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
            help_text="Pick all that apply",
            order=0,
        )
        SessionFieldOption.objects.create(
            field=genres, label="Horror", value="horror", order=0
        )
        SessionFieldOption.objects.create(
            field=genres, label="Comedy", value="comedy", order=1
        )

        system = SessionField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="select",
            allow_custom=True,
            order=1,
        )
        SessionFieldOption.objects.create(
            field=system, label="D&D", value="dnd", order=0
        )

        adult = SessionField.objects.create(
            event=event,
            name="18+",
            question="Adult content?",
            slug="adult",
            field_type="checkbox",
            order=2,
        )

        notes = SessionField.objects.create(
            event=event,
            name="Notes",
            question="Anything else?",
            slug="notes",
            field_type="text",
            allow_custom=True,
            max_length=99,
            help_text="Free text",
            order=3,
        )

        SessionFieldValue.objects.create(
            session=session, field=genres, value=["horror"]
        )
        SessionFieldValue.objects.create(session=session, field=system, value="dnd")
        SessionFieldValue.objects.create(session=session, field=adult, value=True)
        SessionFieldValue.objects.create(
            session=session, field=notes, value="Bring dice"
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        html = response.content.decode()
        assert 'name="session_field_genres"' in html
        assert "Pick all that apply" in html
        assert 'name="session_field_system"' in html
        assert 'name="session_field_system_custom"' in html
        assert 'name="session_field_adult"' in html
        assert 'name="session_field_notes"' in html
        assert 'maxlength="99"' in html
        assert 'name="session_field_notes_custom"' in html

    def test_partial_post_without_session_fields_marker_preserves_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="text",
            order=0,
        )
        SessionFieldValue.objects.create(
            session=session, field=field, value="Pathfinder"
        )

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == "Pathfinder"
        session.refresh_from_db()
        assert session.title == "Updated title only"

    def test_partial_post_without_facilitators_marker_preserves_facilitators(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        assigned = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(assigned)

        authenticated_client.post(
            self.get_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "display_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert list(session.facilitators.values_list("pk", flat=True)) == [assigned.pk]
        session.refresh_from_db()
        assert session.title == "Updated title only"

    def test_get_renders_facilitator_picker_with_assigned_marked(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        assigned = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        unassigned = Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )
        session.facilitators.add(assigned)

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        html = response.content.decode()
        assert 'id="facilitator-search"' in html
        assert f'value="{assigned.pk}"' in html
        assert f'value="{unassigned.pk}"' in html
        assert "Alice" in html
        assert "Bob" in html
        assigned_row = html[
            html.index(f'value="{assigned.pk}"') : html.index(f'value="{assigned.pk}"')
            + 200
        ]
        assert "checked" in assigned_row
        unassigned_row = html[
            html.index(f'value="{unassigned.pk}"') : html.index(
                f'value="{unassigned.pk}"'
            )
            + 200
        ]
        assert "checked" not in unassigned_row
