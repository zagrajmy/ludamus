from datetime import date
from http import HTTPStatus

from django.urls import reverse

from ludamus.pacts import EventDTO
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
)


class TestTimetableBrowsePanePartView:
    """Tests for /panel/event/<slug>/timetable/parts/browse-pane/ partial."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-browse-pane-part", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse(
            "panel:timetable-browse-pane-part", kwargs={"slug": "nonexistent"}
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_partial_with_filter_context(self, panel_client, event):
        response = panel_client.get(
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
                "date_selection": date(2026, 9, 4),
                "slug": event.slug,
                "current_event": EventDTO.model_validate(event),
            },
        )
