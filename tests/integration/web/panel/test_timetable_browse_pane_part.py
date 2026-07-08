from datetime import date
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.pacts import EventDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimetableBrowsePanePartView:
    """Tests for /panel/event/<slug>/timetable/parts/browse-pane/ partial."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-browse-pane-part", kwargs={"slug": event.slug})

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
        url = reverse(
            "panel:timetable-browse-pane-part", kwargs={"slug": "nonexistent"}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_returns_partial_with_filter_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.get_url(event),
            {
                "category": "7",
                "max_duration": "30",
                "search": "abc",
                "date": "2026-09-04",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-browse-pane.html",
            context_data={
                "filter_track_pk": None,
                "category_pk": 7,
                "max_duration_minutes": 30,
                "search": "abc",
                "selected_date": date(2026, 9, 4),
                "slug": event.slug,
                "current_event": EventDTO.model_validate(event),
            },
        )
