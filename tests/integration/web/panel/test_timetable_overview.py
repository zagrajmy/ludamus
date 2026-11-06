from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.db.django.models import Track
from ludamus.pacts.chronology import (
    CapacityHoursDTO,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
    TrackProgressDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    make_timetable_session,
    panel_context,
    schedule_session,
    timetable_tab_urls,
)

OPEN_HOURS = 4


@pytest.fixture(name="event")
def open_hours_event_fixture(sphere):
    # The shared fixture runs from UTC midnight to a second short of the next
    # one, so its local clock window is a ragged 01:00-02:00. Capacity counts
    # open hours, so pin the event to whole local hours instead.
    start = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)  # 10:00 in Warsaw
    return EventFactory(
        sphere=sphere, start_time=start, end_time=start + timedelta(hours=OPEN_HOURS)
    )


def _heatmap_without_rooms(event):
    # With no rooms every row is cell-less, but the rows themselves come from
    # the event's own day and hours, which it always has.
    day_start = localtime(event.start_time)
    rows = [
        HeatmapRowDTO(time=day_start + timedelta(hours=hour), cells=[])
        for hour in range(OPEN_HOURS)
    ]
    return HeatmapDTO(
        spaces=[], rows=rows, days=[HeatmapDayDTO(date=day_start.date(), rows=rows)]
    )


def _capacity_hours_without_rooms():
    return CapacityHoursDTO(
        room_count=0,
        slot_hours=float(OPEN_HOURS),
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

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-overview", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_overview_template(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-overview.html",
            context_data={
                **panel_context(event, active_nav="timetable"),
                "heatmap": _heatmap_without_rooms(event),
                "track_progress": [],
                "capacity_hours": _capacity_hours_without_rooms(),
                "slug": event.slug,
                "tab_urls": timetable_tab_urls(event),
                "active_tab": "overview",
            },
        )

    def test_heatmap_has_correct_structure(self, panel_client, event):
        SpaceFactory(event=event)

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        heatmap = response.context["heatmap"]
        assert len(heatmap.spaces) == 1
        assert len(heatmap.rows) == OPEN_HOURS
        assert len(heatmap.days) == 1

    def test_track_progress_denominator_is_active_pool_with_status_pills(
        self, panel_client, active_user, event, proposal_category
    ):
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

        response = panel_client.get(self.get_url(event))

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
                **panel_context(
                    event,
                    active_nav="timetable",
                    hosts_count=1,
                    pending_proposals=3,
                    total_proposals=3 + 3 + 1 + 1,
                    total_sessions=3 + 0,
                ),
                "heatmap": _heatmap_without_rooms(event),
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
                "capacity_hours": _capacity_hours_without_rooms(),
                "slug": event.slug,
                "tab_urls": timetable_tab_urls(event),
                "active_tab": "overview",
            },
        )

    def test_capacity_hours_reports_hours_left_to_fill(
        self, panel_client, event, proposal_category
    ):
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        start = event.start_time
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["capacity_hours"] == CapacityHoursDTO(
            room_count=1,
            slot_hours=float(OPEN_HOURS),
            capacity_hours=float(OPEN_HOURS),
            scheduled_hours=1.0,
            hours_to_fill=OPEN_HOURS - 1.0,
            filled_pct=25,
        )

    def test_heatmap_shows_scheduled_cell_status(
        self, panel_client, event, proposal_category
    ):
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        heatmap = response.context["heatmap"]
        first_row = heatmap.rows[0]
        statuses = {cell.status for cell in first_row.cells}
        assert "scheduled" in statuses
