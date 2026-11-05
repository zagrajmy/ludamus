"""Facilitator, track and time slot pickers of the proposal form."""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from ludamus.links.db.django.models import (
    Facilitator,
    ProposalCategory,
    Session,
    TimeSlot,
    Track,
)
from ludamus.pacts import EventDTO, TimeSlotDTO, TrackDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import FormErrorsMatcher, assert_response, checkbox_tag
from tests.integration.web.panel.helpers import facilitator_list_item_dto
from tests.integration.web.panel.proposal_form.helpers import (
    assert_created,
    form_context,
    form_url,
    make_session,
    saved_session,
)


class TestBothModes:
    def test_post_ignores_track_from_other_event(
        self, panel_client, sphere, event, form_mode, valid_post
    ):
        foreign_track = Track.objects.create(
            event=EventFactory(sphere=sphere),
            name="Foreign",
            slug="foreign",
            is_public=True,
        )

        panel_client.post(
            form_mode.url,
            data=valid_post | {
                "tracks_submitted": "1",
                "track_ids": [foreign_track.pk],
            },
        )

        assert not saved_session(event).tracks.exists()

    def test_post_ignores_time_slot_from_other_event(
        self, panel_client, sphere, event, form_mode, valid_post
    ):
        foreign_slot = TimeSlot.objects.create(
            event=EventFactory(sphere=sphere),
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        panel_client.post(
            form_mode.url,
            data=valid_post | {
                "time_slots_submitted": "1",
                "time_slot_ids": [foreign_slot.pk],
            },
        )

        assert not saved_session(event).time_slots.exists()

    def test_post_assigns_time_slots(self, panel_client, event, form_mode, valid_post):
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        panel_client.post(
            form_mode.url,
            data=valid_post | {"time_slots_submitted": "1", "time_slot_ids": [slot.pk]},
        )

        assert list(saved_session(event).time_slots.values_list("pk", flat=True)) == [
            slot.pk
        ]


class TestCreate:
    def test_get_renders_facilitator_checkboxes_when_event_has_facilitators(
        self, panel_client, event
    ):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.get(form_url(event))

        # Search-first picker: unselected facilitators start hidden.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
            },
            contains=[
                'name="facilitator_ids"',
                f'value="{facilitator.pk}"',
                "Alice",
                'id="facilitator-search"',
            ],
        )

    def test_get_leaves_deleted_facilitators_out_of_the_picker(
        self, panel_client, event
    ):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        Facilitator.objects.create(
            event=event,
            display_name="Deleted",
            slug="deleted",
            user=None,
            deleted_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        )

        response = panel_client.get(form_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
            },
        )

    def test_post_invalid_keeps_selected_facilitator_checked(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "category_id": category.pk,
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "facilitator_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
                "assigned_facilitator_pks": {facilitator.pk},
            },
        )
        content = response.content.decode()
        assert "checked" in checkbox_tag(content, "facilitator_ids", facilitator.pk)

    def test_post_renders_facilitator_error_with_checkboxes(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "category_id": category.pk,
                "facilitators_submitted": "1",
                "title": "Missing Facilitator",
                "facilitator_name": "Test Host",
            },
        )

        # The form itself is valid; the "at least one facilitator" rule is
        # enforced by the view and surfaced above the form.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
            },
            contains=[
                'name="facilitator_ids"',
                "Please select at least one facilitator.",
            ],
        )
        assert not Session.objects.filter(title="Missing Facilitator").exists()

    def test_post_renders_facilitator_error_when_event_has_no_facilitators(
        self, panel_client, event
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = panel_client.post(
            form_url(event),
            data={
                "category_id": category.pk,
                "facilitators_submitted": "1",
                "title": "Missing Facilitator",
                "facilitator_name": "Test Host",
            },
        )

        # No picker card renders at all here, so the error has to live outside
        # it or the submission fails with no visible feedback.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={**form_context(event)},
            contains=[
                "This event has no facilitators yet.",
                "Please select at least one facilitator.",
            ],
        )
        assert not Session.objects.filter(title="Missing Facilitator").exists()

    def test_post_creates_session_with_facilitator_and_redirects(
        self, panel_client, event
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "My New Session",
                "facilitator_name": "Test Host",
                "description": "A great session",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = assert_created(response, event, title="My New Session")
        assert list(new_session.facilitators.values_list("pk", flat=True)) == [
            facilitator.pk
        ]

    def test_get_renders_time_slot_checkboxes(self, panel_client, event):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        response = panel_client.get(form_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_time_slots": [TimeSlotDTO.model_validate(slot)],
            },
            contains='name="time_slot_ids"',
        )

    def test_post_invalid_keeps_selected_time_slot_checked(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        response = panel_client.post(
            form_url(event),
            data={
                "category_id": category.pk,
                "facilitator_name": "Test Host",
                "time_slots_submitted": "1",
                "time_slot_ids": [slot.pk],
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_time_slots": [TimeSlotDTO.model_validate(slot)],
                "assigned_time_slot_pks": {slot.pk},
            },
        )
        content = response.content.decode()
        assert "checked" in checkbox_tag(content, "time_slot_ids", slot.pk)

    def test_get_renders_track_checkboxes(self, panel_client, event):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        response = panel_client.get(form_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_tracks": [TrackDTO.model_validate(track)],
            },
            contains=[
                'name="tracks_submitted"',
                'name="track_ids"',
                f'value="{track.pk}"',
                "Main Track",
            ],
        )

    def test_post_creates_session_with_tracks(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Tracked Session",
                "facilitator_name": "Test Host",
                "tracks_submitted": "1",
                "track_ids": [track.pk],
            },
        )

        new_session = Session.objects.get(title="Tracked Session")
        assert list(new_session.tracks.values_list("pk", flat=True)) == [track.pk]

    def test_post_without_facilitator_shows_error(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = panel_client.post(
            form_url(event),
            data={
                "category_id": category.pk,
                "title": "No Facilitator",
                "facilitator_name": "Test Host",
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
            context_data={**form_context(event)},
        )
        assert not Session.objects.filter(title="No Facilitator").exists()

    def test_post_ignores_facilitator_from_other_event(
        self, panel_client, sphere, event
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        other_event = EventFactory(
            sphere=sphere, start_time=event.start_time + timedelta(days=1)
        )
        foreign = Facilitator.objects.create(
            event=other_event, display_name="Bob", slug="bob", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [foreign.pk],
                "category_id": category.pk,
                "title": "Foreign Facilitator",
                "facilitator_name": "Test Host",
            },
        )

        # The foreign facilitator is filtered out as not event-scoped, leaving
        # zero facilitators — the view blocks creation.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "events": [
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
            },
        )
        assert not Session.objects.filter(title="Foreign Facilitator").exists()


class TestEdit:
    def test_post_assigns_facilitators(self, panel_client, event):
        session = make_session(event)
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "facilitators_submitted": "1",
                "facilitator_ids": [alice.pk],
            },
        )

        assert list(session.facilitators.values_list("pk", flat=True)) == [alice.pk]

    def test_post_ignores_facilitator_assignment_from_other_event(
        self, panel_client, sphere, event
    ):
        session = make_session(event)
        other_event = EventFactory(sphere=sphere)
        foreign_facilitator = Facilitator.objects.create(
            event=other_event, display_name="Mallory", slug="mallory", user=None
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "facilitators_submitted": "1",
                "facilitator_ids": [foreign_facilitator.pk],
            },
        )

        assert not session.facilitators.exists()

    def test_post_assigns_tracks(self, panel_client, event):
        session = make_session(event)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "tracks_submitted": "1",
                "track_ids": [track.pk],
            },
        )

        assert list(session.tracks.values_list("pk", flat=True)) == [track.pk]

    def test_invalid_post_preserves_submitted_track_selection(
        self, panel_client, event
    ):
        session = make_session(event)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                # Missing title → form invalid, triggers the re-render path.
                "category_id": session.category_id,
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "tracks_submitted": "1",
                "track_ids": [track.pk],
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "form": FormErrorsMatcher(title=["Title is required."]),
                "all_tracks": [TrackDTO.model_validate(track)],
                "assigned_track_pks": {track.pk},
            },
        )
        assert not session.tracks.exists()

    def test_partial_post_without_tracks_marker_preserves_tracks(
        self, panel_client, event
    ):
        session = make_session(event)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        session.tracks.add(track)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert list(session.tracks.values_list("pk", flat=True)) == [track.pk]

    def test_post_clears_time_slots_when_marker_present_and_none_selected(
        self, panel_client, event
    ):
        session = make_session(event)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        session.time_slots.add(slot)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "time_slots_submitted": "1",
            },
        )

        assert not session.time_slots.exists()

    def test_invalid_post_preserves_submitted_time_slot_selection(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = make_session(event)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )

        response = authenticated_client.post(
            form_url(event, session.pk),
            data={
                # Missing title → form invalid, triggers the re-render path.
                "category_id": session.category_id,
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "time_slots_submitted": "1",
                "time_slot_ids": [slot.pk],
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_time_slots": [TimeSlotDTO.model_validate(slot)],
                "assigned_time_slot_pks": {slot.pk},
            },
        )
        assert not session.time_slots.exists()

    def test_partial_post_without_time_slots_marker_preserves_time_slots(
        self, panel_client, event
    ):
        session = make_session(event)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        session.time_slots.add(slot)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert list(session.time_slots.values_list("pk", flat=True)) == [slot.pk]

    def test_partial_post_without_facilitators_marker_preserves_facilitators(
        self, panel_client, event
    ):
        session = make_session(event)
        assigned = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(assigned)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert list(session.facilitators.values_list("pk", flat=True)) == [assigned.pk]
        session.refresh_from_db()
        assert session.title == "Updated title only"

    def test_get_renders_track_and_time_slot_cards(self, panel_client, event):
        session = make_session(event)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        session.tracks.add(track)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        session.time_slots.add(slot)

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_tracks": [TrackDTO.model_validate(track)],
                "assigned_track_pks": {track.pk},
                "all_time_slots": [TimeSlotDTO.model_validate(slot)],
                "assigned_time_slot_pks": {slot.pk},
            },
            contains=[
                'name="tracks_submitted"',
                'name="track_ids"',
                "Main Track",
                'name="time_slots_submitted"',
                'name="time_slot_ids"',
            ],
        )
        html = response.content.decode()
        assert "checked" in checkbox_tag(html, "track_ids", track.pk)
        assert "checked" in checkbox_tag(html, "time_slot_ids", slot.pk)

    def test_get_renders_facilitator_picker_with_assigned_marked(
        self, panel_client, event
    ):
        session = make_session(event)

        assigned = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        unassigned = Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )
        session.facilitators.add(assigned)

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_facilitators": [
                    facilitator_list_item_dto(assigned, session_count=1),
                    facilitator_list_item_dto(unassigned),
                ],
                "assigned_facilitator_pks": {assigned.pk},
            },
            contains=['id="facilitator-search"', "Alice", "Bob"],
        )
        html = response.content.decode()
        assert "checked" in checkbox_tag(html, "facilitator_ids", assigned.pk)
        assert "checked" not in checkbox_tag(html, "facilitator_ids", unassigned.pk)

    def test_post_invalid_keeps_submitted_facilitator_selection(
        self, panel_client, event
    ):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "title": "",
                "facilitator_name": "",
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
                "assigned_facilitator_pks": {facilitator.pk},
            },
        )
        content = response.content.decode()
        assert "checked" in checkbox_tag(content, "facilitator_ids", facilitator.pk)
