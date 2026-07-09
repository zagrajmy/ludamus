from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Track
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import CapacityHoursDTO, HeatmapDTO
from tests.integration.conftest import AgendaItemFactory, SessionFactory, SpaceFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _empty_heatmap():
    return HeatmapDTO(spaces=[], rows=[], days=[])


def _empty_capacity_hours():
    return CapacityHoursDTO(
        room_count=0,
        slot_hours=0.0,
        capacity_hours=0.0,
        scheduled_hours=0.0,
        hours_to_fill=0.0,
        filled_pct=0,
    )


class TestTimetableOverviewPageView:
    """Tests for /panel/event/<slug>/timetable/overview/ overview page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-overview", kwargs={"slug": event.slug})

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
        url = reverse("panel:timetable-overview", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_returns_overview_template(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-overview.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "timetable",
                "heatmap": _empty_heatmap(),
                "track_progress": [],
                "capacity_hours": _empty_capacity_hours(),
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
            },
        )

    def test_heatmap_has_correct_structure(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        SpaceFactory(event=event)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        heatmap = response.context["heatmap"]
        assert len(heatmap.spaces) == 1
        assert len(heatmap.rows) > 0
        assert len(heatmap.days) == 1
        assert time_slot is not None

    def test_track_progress_shows_tracks(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="Test Track", slug="test-track", is_public=True
        )
        space = SpaceFactory(event=event)
        track.spaces.add(space)
        session = SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        session.tracks.add(track)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        progress = response.context["track_progress"]
        assert len(progress) == 1
        assert progress[0].track_name == "Test Track"
        assert progress[0].accepted_count == 1
        assert progress[0].scheduled_count == 0
        assert progress[0].unassigned_count == 1
        assert "(1 unassigned)" in response.content.decode()

    def test_capacity_hours_reports_hours_left_to_fill(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        proposal_category,
        time_slot,
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        # 1 room * 2h slot = 2h capacity; 1h scheduled => 1h left, 50% filled.
        assert response.context["capacity_hours"] == CapacityHoursDTO(
            room_count=1,
            slot_hours=2.0,
            capacity_hours=2.0,
            scheduled_hours=1.0,
            hours_to_fill=1.0,
            filled_pct=50,
        )
        assert time_slot is not None

    def test_heatmap_shows_scheduled_cell_status(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        proposal_category,
        time_slot,
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        heatmap = response.context["heatmap"]
        # First row's cell for our space should be 'scheduled'
        first_row = heatmap.rows[0]
        statuses = {cell.status for cell in first_row.cells}
        assert "scheduled" in statuses
        assert time_slot is not None
