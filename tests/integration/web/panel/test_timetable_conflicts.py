"""Integration tests for conflict detection in timetable assignment."""

import json
from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from tests.integration.conftest import AgendaItemFactory, SessionFactory, SpaceFactory


class TestConflictDetectionOnAssign:
    """Conflict detection is called and returned on assignment."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-assign", kwargs={"slug": event.slug})

    def test_assigns_without_conflicts_returns_no_conflict_trigger(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        trigger = json.loads(response.get("HX-Trigger", "{}"))
        assert "timetableConflicts" not in trigger

    def test_space_overlap_conflict_included_in_trigger(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        existing_session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)
        AgendaItemFactory(
            session=existing_session,
            space=space,
            start_time=start_time,
            end_time=end_time,
        )
        new_session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=10,
            min_age=0,
        )

        response = authenticated_client.post(
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
