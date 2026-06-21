import re
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Session,
    SessionField,
    SessionFieldValue,
    Space,
    TimeSlot,
)
from ludamus.pacts import (
    EventDTO,
    SessionDTO,
    SessionFieldValueDTO,
    SpaceDTO,
    TimeSlotDTO,
)
from tests.integration.utils import assert_response


def _has_option(content: str, value: int, label: str) -> bool:
    pattern = rf'<option value="{value}"[^>]*>\s*{re.escape(label)}\s*</option>'
    return re.search(pattern, content) is not None


class TestProposalAcceptPageView:
    URL_NAME = "web:chronology:session-accept"

    def _get_url(self, session_id: int) -> str:
        return reverse(self.URL_NAME, kwargs={"session_id": session_id})

    def test_get_error_proposal_not_found(self, staff_client):
        response = staff_client.get(self._get_url(17))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("web:index"),
        )

    def test_get_error_session_exists(self, event, pending_session, staff_client):
        pending_session.status = "scheduled"
        pending_session.save()
        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "This proposal has already been accepted.")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_get_ok(self, event, pending_session, space, staff_client, time_slot):
        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_get_shows_preferred_time_slots(
        self, event, pending_session, space, staff_client, time_slot
    ):
        pending_session.time_slots.add(time_slot)

        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [],
                "preferred_time_slot_ids": [time_slot.pk],
            },
            template_name="chronology/accept_proposal.html",
        )
        assert "Preferred Time Slots" in response.content.decode()

    @pytest.mark.usefixtures("space")
    def test_get_renders_select_for_multiple_time_slots(
        self, event, pending_session, staff_client, time_slot
    ):
        # A second slot means there's a real choice, so the tessera select
        # renders instead of the single-slot read-only collapse.
        TimeSlot.objects.create(
            event=event,
            start_time=time_slot.end_time,
            end_time=time_slot.end_time + timedelta(hours=2),
        )

        response = staff_client.get(self._get_url(pending_session.id))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "<select" in content
        assert 'name="time_slot"' in content

    @pytest.mark.usefixtures("event", "time_slot")
    def test_get_collapses_single_space_to_static_value(
        self, pending_session, space, staff_client
    ):
        """A lone space is a foregone choice: shown as static text + hidden input."""
        response = staff_client.get(self._get_url(pending_session.id))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        # No dropdown to operate — the value is carried in a hidden input and
        # the lone space is shown as static text (so no space optgroup renders).
        assert f'<input type="hidden" name="space" value="{space.id}"' in content
        assert space.name in content
        assert "<optgroup" not in content

    @pytest.mark.usefixtures("time_slot")
    def test_get_shows_multiple_spaces_in_same_area(
        self, pending_session, venue, area, space, staff_client
    ):
        """Test that multiple spaces in same area are grouped together."""
        # Create a second space in the same area
        second_space = Space.objects.create(
            area=area, name="Second Room", slug="second-room"
        )

        response = staff_client.get(self._get_url(pending_session.id))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        # Verify optgroup with "Venue > Area" label is present
        assert f'<optgroup label="{venue.name} &gt; {area.name}">' in content
        # Verify both spaces are within the optgroup
        assert _has_option(content, space.id, space.name)
        assert _has_option(content, second_space.id, "Second Room")

    def test_get_error_no_space(self, event, pending_session, staff_client):
        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No spaces configured for this event. Please create spaces first.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    @pytest.mark.usefixtures("space")
    def test_get_error_no_time_slot(self, event, pending_session, staff_client):
        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    (
                        "No time slots configured for this event. Please create time "
                        "slots first."
                    ),
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_get_wrong_permissions(self, event, pending_session, authenticated_client):
        response = authenticated_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "You don't have permission to accept proposals for this event.",
                )
            ],
            url=f"/chronology/event/{event.slug}/",
        )

    def test_post_error_proposal_not_found(self, staff_client):
        response = staff_client.post(self._get_url(17))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("web:index"),
        )

    def test_post_error_session_exists(self, event, pending_session, staff_client):
        pending_session.status = "scheduled"
        pending_session.save()
        response = staff_client.post(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "This proposal has already been accepted.")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_post_invalid_form(self, event, pending_session, staff_client, time_slot):
        response = staff_client.post(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_post_ok(
        self, active_user, event, pending_session, space, staff_client, time_slot
    ):
        response = staff_client.post(
            self._get_url(pending_session.id),
            data={"space": space.id, "time_slot": time_slot.id},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        f"Proposal '{pending_session.title}' has been accepted and "
                        "added to the agenda."
                    ),
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        session = Session.objects.get(pk=pending_session.pk)
        assert session.status == "scheduled"
        assert session.display_name == active_user.name
        assert session.agenda_item.space == space
        assert session.agenda_item.session == session
        assert session.agenda_item.session_confirmed
        assert session.agenda_item.start_time == time_slot.start_time
        assert session.agenda_item.end_time == time_slot.end_time

    def test_post_wrong_permissions(
        self, event, pending_session, space, authenticated_client, time_slot
    ):
        response = authenticated_client.post(
            self._get_url(pending_session.id),
            data={"space": space.id, "time_slot": time_slot.id},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "You don't have permission to accept proposals for this event.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_post_invalid_space_id(
        self, event, pending_session, space, staff_client, time_slot
    ):
        response = staff_client.post(
            self._get_url(pending_session.id),
            data={"space": 99999, "time_slot": time_slot.id},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_post_ok_conflict(
        self, staff_user, event, pending_session, space, staff_client, time_slot
    ):
        other_session = Session.objects.create(
            event=event,
            title="Other Session",
            sphere=event.sphere,
            slug="other-session",
            display_name=staff_user.name,
            participants_limit=10,
        )
        AgendaItem.objects.create(
            session=other_session,
            space=space,
            start_time=time_slot.start_time,
            end_time=time_slot.end_time,
        )

        response = staff_client.post(
            self._get_url(pending_session.id),
            data={"space": space.id, "time_slot": time_slot.id},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_get_ok_with_select_field_values(
        self, event, pending_session, space, staff_client, time_slot
    ):
        """Public select field values are shown in context."""
        session_field = SessionField.objects.create(
            event=event,
            name="Game Type",
            question="Game Type",
            slug="game-type",
            field_type="select",
            is_multiple=True,
            is_public=True,
            icon="puzzle-piece",
        )
        SessionFieldValue.objects.create(
            session=pending_session, field=session_field, value=["RPG"]
        )

        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [
                    SessionFieldValueDTO(
                        allow_custom=False,
                        field_icon="puzzle-piece",
                        field_id=session_field.pk,
                        field_name="Game Type",
                        field_question="Game Type",
                        field_slug="game-type",
                        field_type="select",
                        is_public=True,
                        value=["RPG"],
                    )
                ],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_get_ok_with_text_field_in_field_values(
        self, event, pending_session, space, staff_client, time_slot
    ):
        """Text field values appear in field_values context."""
        session_field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system?",
            slug="rpg-system",
            field_type="text",
            is_public=True,
        )
        SessionFieldValue.objects.create(
            session=pending_session, field=session_field, value="D&D 5e"
        )

        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [
                    SessionFieldValueDTO(
                        allow_custom=False,
                        field_icon="",
                        field_id=session_field.pk,
                        field_name="RPG System",
                        field_question="What RPG system?",
                        field_slug="rpg-system",
                        field_type="text",
                        is_public=True,
                        value="D&D 5e",
                    )
                ],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_get_ok_with_boolean_select_field_in_field_values(
        self, event, pending_session, space, staff_client, time_slot
    ):
        """Public select field with a boolean value appears in field_values."""
        session_field = SessionField.objects.create(
            event=event,
            name="Has Minis",
            question="Do you use miniatures?",
            slug="has-minis",
            field_type="select",
            is_public=True,
        )
        SessionFieldValue.objects.create(
            session=pending_session, field=session_field, value=True
        )

        response = staff_client.get(self._get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "spaces": [SpaceDTO.model_validate(space)],
                "time_slots": [TimeSlotDTO.model_validate(time_slot)],
                "field_values": [
                    SessionFieldValueDTO(
                        allow_custom=False,
                        field_icon="",
                        field_id=session_field.pk,
                        field_name="Has Minis",
                        field_question="Do you use miniatures?",
                        field_slug="has-minis",
                        field_type="select",
                        is_public=True,
                        value=True,
                    )
                ],
                "preferred_time_slot_ids": [],
            },
            template_name="chronology/accept_proposal.html",
        )
