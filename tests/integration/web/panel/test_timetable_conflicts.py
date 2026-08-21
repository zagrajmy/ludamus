"""Integration tests for conflict detection in timetable assignment."""

import json
from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from tests.integration.conftest import AgendaItemFactory, SpaceFactory, TimeSlotFactory
from tests.integration.web.panel.helpers import assign_payload, make_timetable_session


class TestConflictDetectionOnAssign:
    """Conflict detection is called and returned on assignment."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-assign", kwargs={"slug": event.slug})

    def test_assigns_without_conflicts_returns_no_conflict_trigger(
        self, panel_client, event, proposal_category
    ):
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        space = SpaceFactory(event=event)
        session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = panel_client.post(
            self.get_url(event),
            assign_payload(
                session=session, space=space, start=start_time, end=end_time
            ),
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        trigger = json.loads(response.get("HX-Trigger", "{}"))
        assert "timetableConflicts" not in trigger

    def test_space_overlap_conflict_included_in_trigger(
        self, panel_client, event, proposal_category
    ):
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        space = SpaceFactory(event=event)
        existing_session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)
        AgendaItemFactory(
            session=existing_session,
            space=space,
            start_time=start_time,
            end_time=end_time,
        )
        new_session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )

        response = panel_client.post(
            self.get_url(event),
            {
                "session_pk": new_session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        trigger = json.loads(response.get("HX-Trigger", "{}"))
        assert "timetableConflicts" in trigger
        conflict_types = [c["type"] for c in trigger["timetableConflicts"]["conflicts"]]
        assert "space_overlap" in conflict_types
