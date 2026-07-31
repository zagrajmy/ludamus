from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from tests.integration.conftest import AgendaItemFactory, SpaceFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    make_timetable_session,
    panel_context,
)


class TestTimetableLogPageView:
    """Tests for /panel/event/<slug>/timetable/log/ activity log page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-log", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-log", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_log_template(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-log.html",
            context_data={
                **panel_context(event, active_nav="timetable"),
                "logs": [],
                "revertible_pks": set(),
                "spaces": [],
                "space_pk": None,
                "slug": event.slug,
                "tab_urls": {
                    "timetable": reverse(
                        "panel:timetable", kwargs={"slug": event.slug}
                    ),
                    "log": reverse("panel:timetable-log", kwargs={"slug": event.slug}),
                    "overview": reverse(
                        "panel:timetable-overview", kwargs={"slug": event.slug}
                    ),
                    "problems": reverse(
                        "panel:timetable-problems", kwargs={"slug": event.slug}
                    ),
                },
                "active_tab": "log",
            },
        )

    def test_empty_log_when_no_changes(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["logs"] == []

    def test_assign_creates_log_entry(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, status="accepted")
        start = event.start_time
        end = start + timedelta(hours=1)

        authenticated_client.post(
            reverse("panel:timetable-assign", kwargs={"slug": event.slug}),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        logs = response.context["logs"]
        assert len(logs) == 1
        assert logs[0].action == "assign"
        assert logs[0].session_title == session.title
        assert logs[0].new_space_name == space.name

    def test_unassign_creates_log_entry(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, status="accepted")
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        authenticated_client.post(
            reverse("panel:timetable-unassign", kwargs={"slug": event.slug}),
            data={"session_pk": session.pk},
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        logs = response.context["logs"]
        assert len(logs) == 1
        assert logs[0].action == "unassign"
        assert logs[0].old_space_name == space.name

    def test_space_filter_returns_only_matching_logs(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space_a = SpaceFactory(event=event)
        space_b = SpaceFactory(event=event)
        session_a = make_timetable_session(proposal_category, status="accepted")
        session_b = make_timetable_session(proposal_category, status="accepted")
        start = event.start_time
        end = start + timedelta(hours=1)

        for session, space in ((session_a, space_a), (session_b, space_b)):
            authenticated_client.post(
                reverse("panel:timetable-assign", kwargs={"slug": event.slug}),
                data={
                    "session_pk": session.pk,
                    "space_pk": space.pk,
                    "start_time": start.isoformat(),
                    "end_time": end.isoformat(),
                },
            )

        response = authenticated_client.get(
            self.get_url(event), data={"space": space_a.pk}
        )

        assert response.status_code == HTTPStatus.OK
        logs = response.context["logs"]
        assert len(logs) == 1
        assert logs[0].new_space_name == space_a.name
