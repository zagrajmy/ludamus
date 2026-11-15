from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import AgendaItem, Session
from ludamus.links.db.django.users import user_dto
from ludamus.pacts.event import EventDTO, TimeSlotDTO
from ludamus.pacts.sessions import SessionDTO
from tests.integration.utils import assert_response


def _rerendered(event, session, time_slot):
    # The page again, its form carrying the error, and nothing placed.
    return {
        "event": EventDTO.model_validate(event),
        "presenter": user_dto(session.presenter),
        "form": ANY,
        "session": SessionDTO.model_validate(session),
        "time_slots": [TimeSlotDTO.model_validate(time_slot)],
        "field_values": [],
        "preferred_time_slot_ids": [],
        "schedule_blocker": None,
        "taken_space_ids_by_slot": {time_slot.id: []},
    }


def _url(session):
    return reverse(
        "web:chronology:session-accept",
        kwargs={"event_slug": session.event.slug, "session_id": session.pk},
    )


class TestAcceptingWithoutASpace:
    def test_an_event_that_needs_no_space_accepts_into_none(
        self, event, pending_session, manager_client, time_slot
    ):
        event.require_session_space = False
        event.save()

        response = manager_client.post(
            _url(pending_session), data={"time_slot": time_slot.id}
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
        item = Session.objects.get(pk=pending_session.pk).agenda_item
        assert item.space is None
        assert item.start_time == time_slot.start_time

    def test_the_sphere_default_requires_a_space(
        self, event, pending_session, manager_client, time_slot, space
    ):
        # A space exists, so the page asks for one; leaving it blank is no
        # answer where the event requires it.
        assert space.event == event

        response = manager_client.post(
            _url(pending_session), data={"space": "", "time_slot": time_slot.id}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_rerendered(event, pending_session, time_slot),
            template_name="event/accept_proposal.html",
        )
        assert not AgendaItem.objects.filter(session=pending_session).exists()

    def test_an_event_override_wins_over_the_sphere_default(
        self, event, pending_session, manager_client, time_slot, space
    ):
        event.sphere.require_session_space = False
        event.sphere.save()
        event.require_session_space = True
        event.save()
        assert space.event == event

        response = manager_client.post(
            _url(pending_session), data={"space": "", "time_slot": time_slot.id}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_rerendered(event, pending_session, time_slot),
            template_name="event/accept_proposal.html",
        )
        assert not AgendaItem.objects.filter(session=pending_session).exists()

    def test_a_blank_space_is_no_space_where_one_is_optional(
        self, event, pending_session, manager_client, time_slot, space
    ):
        event.require_session_space = False
        event.save()
        assert space.event == event

        response = manager_client.post(
            _url(pending_session), data={"space": "", "time_slot": time_slot.id}
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
        assert Session.objects.get(pk=pending_session.pk).agenda_item.space is None
