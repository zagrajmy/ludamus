import json
from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import AgendaItem
from tests.integration.conftest import TimeSlotFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import make_timetable_session


def _assign(panel_client, event, session, *, offset=timedelta(0)):
    start = event.start_time + offset
    return panel_client.post(
        reverse("panel:timetable-assign", kwargs={"slug": event.slug}),
        {
            "session_pk": session.pk,
            "space_pk": "",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=1)).isoformat(),
        },
    )


class TestPlacingASessionWithoutASpace:
    def test_an_event_that_requires_a_space_refuses_it(
        self, panel_client, event, proposal_category
    ):
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        session = make_timetable_session(proposal_category, status="accepted")

        response = _assign(panel_client, event, session)

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            contains="This event places every session in a space.",
        )
        assert not AgendaItem.objects.filter(session=session).exists()

    def test_an_event_that_needs_none_places_it_without_one(
        self, panel_client, event, proposal_category
    ):
        event.require_session_space = False
        event.save()
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        session = make_timetable_session(proposal_category, status="accepted")

        response = _assign(panel_client, event, session)

        assert_response(
            response,
            HTTPStatus.NO_CONTENT,
            headers={"HX-Trigger": json.dumps({"timetableChanged": {}})},
        )
        assert AgendaItem.objects.get(session=session).space is None

    def test_sessions_without_a_space_share_no_room_to_clash_over(
        self, panel_client, event, proposal_category
    ):
        event.require_session_space = False
        event.save()
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        first = make_timetable_session(proposal_category, status="accepted")
        second = make_timetable_session(proposal_category, status="accepted")
        _assign(panel_client, event, first)

        response = _assign(panel_client, event, second, offset=timedelta(minutes=30))

        # No timetableConflicts in the trigger: same time, no shared room.
        assert_response(
            response,
            HTTPStatus.NO_CONTENT,
            headers={"HX-Trigger": json.dumps({"timetableChanged": {}})},
        )
