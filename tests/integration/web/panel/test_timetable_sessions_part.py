from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.pacts import UNSCHEDULED_LIST_LIMIT
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimetableSessionListPartView:
    """Tests for /panel/event/<slug>/timetable/parts/sessions/ partial."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-sessions-part", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

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
        url = reverse("panel:timetable-sessions-part", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_returns_partial_template(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-session-list.html",
            context_data={
                "sessions": [],
                "has_more": False,
                "limit": UNSCHEDULED_LIST_LIMIT,
                "categories": [],
                "search": "",
                "category_pk": None,
                "max_duration_minutes": None,
                "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
                "filter_track_pk": None,
                "slug": event.slug,
            },
        )

    def test_lists_unscheduled_accepted_sessions(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert session.pk in session_pks

    def test_excludes_rejected_sessions(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        pending = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        rejected = SessionFactory(
            category=proposal_category,
            status="rejected",
            participants_limit=10,
            min_age=0,
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert pending.pk in session_pks
        assert rejected.pk not in session_pks

    def test_excludes_scheduled_sessions(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert session.pk not in session_pks

    def test_search_filters_by_title(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        matching = SessionFactory(
            category=proposal_category,
            status="pending",
            title="HTMX Magic Workshop",
            participants_limit=10,
            min_age=0,
        )
        other = SessionFactory(
            category=proposal_category,
            status="pending",
            title="Board Games Evening",
            participants_limit=10,
            min_age=0,
        )

        response = authenticated_client.get(self.get_url(event), {"search": "magic"})

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert matching.pk in session_pks
        assert other.pk not in session_pks

    def test_category_filter(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        other_category = ProposalCategoryFactory(event=event)
        matching = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        other = SessionFactory(
            category=other_category, status="pending", participants_limit=10, min_age=0
        )

        response = authenticated_client.get(
            self.get_url(event), {"category": str(proposal_category.pk)}
        )

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert matching.pk in session_pks
        assert other.pk not in session_pks

    @pytest.mark.parametrize("max_duration", ("abc", "-1", "0", ""))
    def test_invalid_max_duration_param_does_not_raise(
        self, authenticated_client, active_user, sphere, event, max_duration
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.get_url(event), {"max_duration": max_duration}
        )

        assert response.status_code == HTTPStatus.OK

    def test_caps_results_at_limit_and_flags_has_more(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        for index in range(UNSCHEDULED_LIST_LIMIT + 1):
            SessionFactory(
                category=proposal_category,
                status="pending",
                title=f"Session {index:03d}",
                participants_limit=10,
                min_age=0,
            )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert len(response.context["sessions"]) == UNSCHEDULED_LIST_LIMIT
        assert response.context["has_more"] is True
        assert response.context["limit"] == UNSCHEDULED_LIST_LIMIT
