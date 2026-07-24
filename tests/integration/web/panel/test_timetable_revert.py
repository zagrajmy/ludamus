from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={"log_pk": 1})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-revert", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={"log_pk": 1})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_missing_log_pk_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_invalid_log_pk_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": 99999}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_returns_422_for_log_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
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
        authenticated_client.post(
            self.get_assign_url(other_event),
            data={
                "session_pk": other_session.pk,
                "space_pk": other_space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        log_response = authenticated_client.get(self.get_log_url(other_event))
        assign_log = log_response.context["logs"][0]
        assert assign_log.action == "assign"

        # Attempt to revert the other event's log via the current event.
        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        other_session.refresh_from_db()
        assert other_session.status == "accepted"

    def test_revert_assign_unschedules_session(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)

        # Assign the session
        authenticated_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )

        # Get the assign log entry pk
        log_response = authenticated_client.get(self.get_log_url(event))
        assign_log = log_response.context["logs"][0]
        assert assign_log.action == "assign"

        # Revert
        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert response.status_code == HTTPStatus.FOUND

        # After revert: log shows REVERT entry, session should be unscheduled
        log_response = authenticated_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        # Most recent is REVERT
        assert logs[0].action == "revert"

    def test_revert_unassign_reschedules_session(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        # Unassign the session (creates log)
        authenticated_client.post(
            self.get_unassign_url(event), data={"session_pk": session.pk}
        )

        # Get the unassign log entry pk
        log_response = authenticated_client.get(self.get_log_url(event))
        unassign_log = log_response.context["logs"][0]
        assert unassign_log.action == "unassign"

        # Revert the unassign
        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": unassign_log.pk}
        )

        assert response.status_code == HTTPStatus.FOUND

        # After revert: log shows REVERT entry
        log_response = authenticated_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        assert logs[0].action == "revert"

    def test_revert_non_latest_change_returns_422(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        authenticated_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        # The assign log is now superseded by an unassign on the same session.
        authenticated_client.post(
            self.get_unassign_url(event), data={"session_pk": session.pk}
        )
        logs = authenticated_client.get(self.get_log_url(event)).context["logs"]
        assign_log = next(log for log in logs if log.action == "assign")

        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        session.refresh_from_db()
        assert session.status == "accepted"

    def test_log_page_marks_only_latest_change_revertible(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        authenticated_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        authenticated_client.post(
            self.get_unassign_url(event), data={"session_pk": session.pk}
        )

        log_response = authenticated_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        revertible_pks = log_response.context["revertible_pks"]
        assign_log = next(log for log in logs if log.action == "assign")
        unassign_log = next(log for log in logs if log.action == "unassign")

        assert unassign_log.pk in revertible_pks
        assert assign_log.pk not in revertible_pks
