from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    make_timetable_session,
    schedule_session,
)


class TestTimetableRevertView:
    """Tests for /panel/event/<slug>/timetable/do/revert/ revert endpoint."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-revert", kwargs={"slug": event.slug})

    @staticmethod
    def get_log_url(event):
        return reverse("panel:timetable-log", kwargs={"slug": event.slug})

    @staticmethod
    def get_assign_url(event):
        return reverse("panel:timetable-assign", kwargs={"slug": event.slug})

    @staticmethod
    def get_unassign_url(event):
        return reverse("panel:timetable-unassign", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={"log_pk": 1})

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={"log_pk": 1})

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-revert", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url, data={"log_pk": 1})

        assert_event_not_found(response)

    def test_missing_log_pk_returns_422(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_invalid_log_pk_returns_422(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={"log_pk": 99999})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_returns_422_for_log_from_another_event(self, panel_client, sphere, event):
        other_event = EventFactory(sphere=sphere)
        TimeSlotFactory(
            event=other_event,
            start_time=other_event.start_time,
            end_time=other_event.end_time,
        )
        other_space = SpaceFactory(event=other_event)
        other_session = SessionFactory(
            category=ProposalCategoryFactory(event=other_event),
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        start = other_event.start_time
        end = start + timedelta(hours=1)
        # Assign within the other event to create a log entry there.
        panel_client.post(
            self.get_assign_url(other_event),
            data={
                "session_pk": other_session.pk,
                "space_pk": other_space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        log_response = panel_client.get(self.get_log_url(other_event))
        assign_log = log_response.context["logs"][0]
        assert assign_log.action == "assign"

        # Attempt to revert the other event's log via the current event.
        response = panel_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_session.refresh_from_db()
        assert other_session.status == "accepted"

    def test_revert_assign_unschedules_session(
        self, panel_client, event, proposal_category
    ):
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, status="accepted")
        start = event.start_time
        end = start + timedelta(hours=1)

        # Assign the session
        panel_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )

        # Get the assign log entry pk
        log_response = panel_client.get(self.get_log_url(event))
        assign_log = log_response.context["logs"][0]
        assert assign_log.action == "assign"

        # Revert
        response = panel_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert_response(response, HTTPStatus.FOUND, url=self.get_log_url(event))

        # After revert: log shows REVERT entry, session should be unscheduled
        log_response = panel_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        # Most recent is REVERT
        assert logs[0].action == "revert"

    def test_revert_unassign_reschedules_session(
        self, panel_client, event, proposal_category
    ):
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, status="accepted")
        schedule_session(session=session, space=space, start=event.start_time)

        # Unassign the session (creates log)
        panel_client.post(self.get_unassign_url(event), data={"session_pk": session.pk})

        # Get the unassign log entry pk
        log_response = panel_client.get(self.get_log_url(event))
        unassign_log = log_response.context["logs"][0]
        assert unassign_log.action == "unassign"

        # Revert the unassign
        response = panel_client.post(
            self.get_url(event), data={"log_pk": unassign_log.pk}
        )

        assert_response(response, HTTPStatus.FOUND, url=self.get_log_url(event))

        # After revert: log shows REVERT entry
        log_response = panel_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        assert logs[0].action == "revert"

    def test_revert_non_latest_change_returns_422(
        self, panel_client, event, proposal_category
    ):
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, status="accepted")
        start = event.start_time
        end = start + timedelta(hours=1)
        panel_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        # The assign log is now superseded by an unassign on the same session.
        panel_client.post(self.get_unassign_url(event), data={"session_pk": session.pk})
        logs = panel_client.get(self.get_log_url(event)).context["logs"]
        assign_log = next(log for log in logs if log.action == "assign")

        response = panel_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        session.refresh_from_db()
        assert session.status == "accepted"

    def test_log_page_marks_only_latest_change_revertible(
        self, panel_client, event, proposal_category
    ):
        TimeSlotFactory(
            event=event, start_time=event.start_time, end_time=event.end_time
        )
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, status="accepted")
        start = event.start_time
        end = start + timedelta(hours=1)
        panel_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        panel_client.post(self.get_unassign_url(event), data={"session_pk": session.pk})

        log_response = panel_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        revertible_pks = log_response.context["revertible_pks"]
        assign_log = next(log for log in logs if log.action == "assign")
        unassign_log = next(log for log in logs if log.action == "unassign")

        assert unassign_log.pk in revertible_pks
        assert assign_log.pk not in revertible_pks
