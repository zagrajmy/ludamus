import re
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils.text import slugify
from django.utils.timezone import localtime

from ludamus.links.db.django.models import (
    AgendaItem,
    Session,
    SessionField,
    SessionFieldValue,
    Space,
)
from ludamus.pacts import EventDTO, SessionDTO, SessionFieldValueDTO
from ludamus.pacts.availability import AvailabilityDTO, DayPart
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import SessionAvailabilityFactory
from tests.integration.utils import assert_response

POSTED_START = "%Y-%m-%dT%H:%M"


def _wall_clock(event):
    # What a `datetime-local` input posts: the event's opening as a local wall
    # clock, with no offset for the browser to send.
    return localtime(event.start_time)


def _open_event_at(event, *, hour: int):
    # Pin the event's opening to a local wall-clock hour, so a part window can
    # sit either side of it. Returns the opening as local time.
    opening = localtime(event.start_time).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    event.start_time = opening
    event.end_time = opening + timedelta(hours=12)
    event.save(update_fields=["start_time", "end_time"])
    return opening


def _has_option(content: str, value: int, label: str) -> bool:
    pattern = rf'<option value="{value}"[^>]*>\s*{re.escape(label)}\s*</option>'
    return re.search(pattern, content) is not None


class TestProposalAcceptPageView:
    URL_NAME = "web:chronology:session-accept"

    def _get_url(self, session_id: int, event_slug: str) -> str:
        return reverse(
            self.URL_NAME, kwargs={"event_slug": event_slug, "session_id": session_id}
        )

    def test_get_error_proposal_not_found(self, manager_client, event):
        response = manager_client.get(self._get_url(17, event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("web:index"),
        )

    def test_get_error_session_exists(self, event, pending_session, manager_client):
        pending_session.status = "accepted"
        pending_session.save()
        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "This proposal has already been accepted.")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    @pytest.mark.usefixtures("space")
    def test_get_ok(self, event, pending_session, manager_client):
        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("space")
    def test_get_shows_the_times_the_facilitator_offered(
        self, event, pending_session, manager_client
    ):
        # The reviewer picks a start time; the parts of days the author said
        # they could run in come along so that choice is not made blind.
        day = localtime(event.start_time).date()
        SessionAvailabilityFactory(
            session=pending_session, day=day, part=DayPart.EVENING
        )

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [AvailabilityDTO(day=day, part=DayPart.EVENING)],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("space")
    def test_get_opens_the_start_time_on_the_first_offered_part(
        self, event, pending_session, manager_client
    ):
        # The reviewer should be confirming a time, not typing one: the field
        # opens where the earliest offered part opens.
        opening = _open_event_at(event, hour=10)
        SessionAvailabilityFactory(
            session=pending_session, day=opening.date(), part=DayPart.AFTERNOON
        )

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["form"].fields[
            "start_time"
        ].initial == opening.replace(hour=12)

    @pytest.mark.usefixtures("space")
    def test_get_never_opens_the_start_time_before_the_event_does(
        self, event, pending_session, manager_client
    ):
        # A morning offer on the opening day starts at 06:00, hours before the
        # doors open; the field is clamped to the opening rather than proposing
        # a placement the event cannot hold.
        opening = _open_event_at(event, hour=10)
        SessionAvailabilityFactory(
            session=pending_session, day=opening.date(), part=DayPart.MORNING
        )

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["form"].fields["start_time"].initial == opening

    @pytest.mark.usefixtures("space")
    def test_get_renders_host_avatar(self, pending_session, manager_client):
        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert response.status_code == HTTPStatus.OK
        # The host's avatar renders for the presenter: with no avatar image the
        # tessera component shows the initials placeholder (first two letters).
        initials = pending_session.presenter.full_name[:2].upper()
        assert f">{initials}</span>" in response.content.decode()

    @pytest.mark.usefixtures("space")
    def test_get_renders_proposal_detail_rows(self, pending_session, manager_client):
        pending_session.description = "A haunted manor one-shot."
        pending_session.save()

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "A haunted manor one-shot." in content

    @pytest.mark.usefixtures("space")
    def test_get_without_presenter_still_renders(
        self, event, pending_session, manager_client
    ):
        pending_session.presenter = None
        pending_session.save()

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": None,
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("event")
    def test_get_carries_a_single_space_and_names_it(
        self, pending_session, space, manager_client
    ):
        """A lone space is carried, never asked for — and still named.

        Without the name the decision card would offer "Accept and add to
        agenda" for a room the page never mentions.
        """
        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert f'<input type="hidden" name="space" value="{space.id}"' in content
        assert "<optgroup" not in content
        assert space.name in content

    def test_get_groups_leaf_spaces_under_their_parent(
        self, event, pending_session, manager_client
    ):
        # Leaves sharing a parent node are grouped under that node's path; the
        # non-leaf parent itself is never bookable.
        parent = Space.objects.create(event=event, name="Main Hall", slug="main-hall")
        first = Space.objects.create(
            event=event, parent=parent, name="Room A", slug="room-a"
        )
        second = Space.objects.create(
            event=event, parent=parent, name="Room B", slug="room-b"
        )

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert '<optgroup label="Main Hall">' in content
        assert _has_option(content, first.id, "Room A")
        assert _has_option(content, second.id, "Room B")
        assert not _has_option(content, parent.id, "Main Hall")

    def test_get_ok_without_spaces(self, event, pending_session, manager_client):
        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": "spaces",
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("space")
    def test_get_ok_for_a_proposal_without_a_category(
        self, event, pending_session, manager_client
    ):
        # Regression: the page's reads joined through Session.category, which is
        # nullable, so a category-less proposal 500'd instead of rendering.
        pending_session.category = None
        pending_session.save()

        response = manager_client.get(self._get_url(pending_session.id, event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("space")
    def test_get_ok_when_the_proposal_sets_length_and_minimum_age(
        self, event, pending_session, manager_client
    ):
        # The details grid only draws the length and minimum-age tiles when the
        # proposal carries them, and the default fixture leaves both empty. How
        # they read is e2e's business; that they reach the page is this test's.
        pending_session.duration = "PT1H30M"
        pending_session.min_age = 16
        pending_session.save()

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_get_wrong_permissions(self, event, pending_session, authenticated_client):
        response = authenticated_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
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
            url=f"/event/{event.slug}/",
        )

    def test_get_wrong_permissions_for_non_manager_staff(
        self, event, pending_session, staff_client
    ):
        response = staff_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
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
            url=f"/event/{event.slug}/",
        )

    def test_post_error_proposal_not_found(self, manager_client, event):
        response = manager_client.post(self._get_url(17, event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("web:index"),
        )

    def test_post_error_session_exists(self, event, pending_session, manager_client):
        pending_session.status = "accepted"
        pending_session.save()
        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "This proposal has already been accepted.")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    @pytest.mark.usefixtures("space")
    def test_post_invalid_form(self, event, pending_session, manager_client):
        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_post_ok(self, active_user, event, pending_session, space, manager_client):
        start = _wall_clock(event)

        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug),
            data={"space": space.id, "start_time": start.strftime(POSTED_START)},
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
        assert session.status == "accepted"
        assert session.facilitator_name == active_user.name
        assert session.agenda_item.space == space
        assert session.agenda_item.session == session
        assert session.agenda_item.session_confirmed
        assert session.agenda_item.start_time == start
        # The end follows from the proposal's own length, nothing the form asks.
        assert session.agenda_item.end_time == start + timedelta(hours=1)

    def test_post_preserves_unique_slug(
        self, event, pending_session, space, manager_client, manager_user
    ):
        # Regression: accepting a proposal must not regenerate the slug, which
        # dropped the uniqueness suffix and collided with an existing session.
        base_slug = slugify(pending_session.title)
        pending_session.slug = f"{base_slug}-4"
        pending_session.save()
        Session.objects.create(
            title=pending_session.title,
            event=event,
            slug=base_slug,
            facilitator_name=manager_user.name,
            participants_limit=10,
        )

        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug),
            data={
                "space": space.id,
                "start_time": _wall_clock(event).strftime(POSTED_START),
            },
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
        assert session.status == "accepted"
        assert session.slug == f"{base_slug}-4"

    def test_post_wrong_permissions(
        self, event, pending_session, space, authenticated_client
    ):
        response = authenticated_client.post(
            self._get_url(pending_session.id, pending_session.event.slug),
            data={
                "space": space.id,
                "start_time": _wall_clock(event).strftime(POSTED_START),
            },
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

    @pytest.mark.usefixtures("space")
    def test_post_invalid_space_id(self, event, pending_session, manager_client):
        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug),
            data={
                "space": 99999,
                "start_time": _wall_clock(event).strftime(POSTED_START),
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_post_ok_conflict(
        self, manager_user, event, pending_session, space, manager_client
    ):
        other_session = Session.objects.create(
            event=event,
            title="Other Session",
            slug="other-session",
            facilitator_name=manager_user.name,
            participants_limit=10,
        )
        AgendaItem.objects.create(
            session=other_session,
            space=space,
            start_time=_wall_clock(event),
            end_time=_wall_clock(event) + timedelta(hours=1),
        )

        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug),
            data={
                "space": space.id,
                "start_time": _wall_clock(event).strftime(POSTED_START),
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    def test_post_before_publication_is_refused_on_the_start_time(
        self, event, pending_session, space, manager_client
    ):
        event_dates = (event.start_time, event.end_time)
        start = localtime(event.publication_time) - timedelta(hours=2)

        response = manager_client.post(
            self._get_url(pending_session.id, pending_session.event.slug),
            data={"space": space.id, "start_time": start.strftime(POSTED_START)},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
                "field_values": [],
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )
        assert response.context["form"].errors == {
            "start_time": [
                (
                    "This is before the event is published. "
                    "Move the publication time in the event settings first."
                )
            ]
        }
        event.refresh_from_db()
        assert (event.start_time, event.end_time) == event_dates
        assert Session.objects.get(pk=pending_session.pk).status == "pending"
        assert not AgendaItem.objects.filter(session=pending_session).exists()

    @pytest.mark.usefixtures("space")
    def test_get_ok_with_select_field_values(
        self, event, pending_session, manager_client
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

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
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
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("space")
    def test_get_ok_with_text_field_in_field_values(
        self, event, pending_session, manager_client
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

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
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
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )

    @pytest.mark.usefixtures("space")
    def test_get_ok_with_boolean_select_field_in_field_values(
        self, event, pending_session, manager_client
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

        response = manager_client.get(
            self._get_url(pending_session.id, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "presenter": UserDTO.model_validate(pending_session.presenter),
                "form": ANY,
                "session": SessionDTO.model_validate(pending_session),
                "availability": [],
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
                "schedule_blocker": None,
            },
            template_name="chronology/accept_proposal.html",
        )
