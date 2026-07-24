from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Track
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import CapacityHoursDTO, HeatmapDTO, TrackProgressDTO
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
                "active_tab": "overview",
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

    def test_track_progress_denominator_is_active_pool_with_status_pills(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="Test Track", slug="test-track", is_public=True
        )

        def make(status, count):
            for _ in range(count):
                session = SessionFactory(
                    category=proposal_category,
                    presenter=active_user,
                    status=status,
                    participants_limit=5,
                    min_age=0,
                )
                session.tracks.add(track)

        make("accepted", 3)
        make("pending", 3)
        make("rejected", 1)
        make("on_hold", 1)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-overview.html",
            # Denominator is the active pool (pending + accepted = 6), not
            # accepted alone (3); a pill per non-empty status follows.
            contains=[
                "0/6",
                'title="Accepted"',
                'title="Pending"',
                'title="Rejected"',
                'title="On hold"',
            ],
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 3,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 3 + 3 + 1 + 1,
                    "total_sessions": 3 + 0,  # pending + scheduled
                },
                "active_nav": "timetable",
                "heatmap": _empty_heatmap(),
                "track_progress": [
                    TrackProgressDTO(
                        track_pk=track.pk,
                        track_name="Test Track",
                        manager_names=[],
                        accepted_count=3,
                        scheduled_count=0,
                        pending_count=3,
                        on_hold_count=1,
                        rejected_count=1,
                        progress_pct=0,
                    )
                ],
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
                "active_tab": "overview",
            },
        )

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
        first_row = heatmap.rows[0]
        statuses = {cell.status for cell in first_row.cells}
        assert "scheduled" in statuses
        assert time_slot is not None
