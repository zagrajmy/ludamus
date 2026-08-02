import math
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Track
from ludamus.pacts.venues import PrintScopeOptionDTO
from ludamus.specs.timetable import TIMETABLE_ROOM_PAGE_SIZE
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    empty_grid,
    panel_context,
    schedule_outside_preferred_slot,
    schedule_session,
    timetable_tab_urls,
)


def _base_context(event, **stats):
    return {
        **panel_context(event, active_nav="timetable", **stats),
        "all_tracks": [],
        "managed_track_pks": set(),
        "filter_track_pk": None,
    }


def _scopes(*spaces):
    return [PrintScopeOptionDTO(pk=space.pk, name=space.name) for space in spaces]


def _scheduled_stats(count):
    return {"rooms_count": 1, "scheduled_sessions": count, "total_sessions": count}


# The grid is a deep DTO whose spaces carry DB timestamps and whose time labels
# come from the event's timezone, so rebuilding it here would mean restating the
# view's own scheduling maths. Tests that care about it pass grid=ANY and assert
# the parts they exercise on the next lines; every other key is pinned exactly.
def _page_context(event, *, stats=None, **overrides):
    return {
        **_base_context(event, **(stats or {})),
        "room_page": 1,
        "grid": empty_grid(),
        "conflicts": [],
        "conflict_session_pks": set(),
        "conflicts_count": 0,
        "categories": [],
        "category_pk": None,
        "max_duration_minutes": None,
        "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
        "slot_violation_session_pks": set(),
        "date_selection": "all",
        "slug": event.slug,
        "tab_urls": timetable_tab_urls(event),
        "active_tab": "timetable",
        "print_scopes": [],
        **overrides,
    }


class TestTimetablePageView:
    """Tests for /panel/event/<slug>/timetable/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_ok_for_sphere_manager_empty_grid(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(event),
        )
        assert response.context["grid"].spaces == []

    def test_grid_shows_spaces_and_time_labels(
        self, panel_client, event, space, time_slot
    ):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event, stats={"rooms_count": 1}, grid=ANY, print_scopes=_scopes(space)
            ),
        )
        grid = response.context["grid"]
        assert len(grid.spaces) == 1
        assert grid.spaces[0].pk == space.pk
        assert len(grid.time_labels) > 0
        assert grid.date_selection == "all"
        assert grid.available_dates == [grid.days[0].date]
        assert time_slot is not None

    def test_grid_contains_scheduled_session(
        self, panel_client, event, session, space, time_slot
    ):
        schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event, stats=_scheduled_stats(1), grid=ANY, print_scopes=_scopes(space)
            ),
        )
        grid = response.context["grid"]
        col = next(c for c in grid.days[0].columns if c.space.pk == space.pk)
        assert len(col.sessions) == 1
        assert col.sessions[0].agenda_item.session_title == session.title
        assert time_slot is not None

    def test_all_days_render_side_by_side_with_canonical_url_state(
        self, panel_client, event, space, time_slot
    ):
        second_slot = TimeSlotFactory(
            event=event,
            start_time=time_slot.start_time + timedelta(days=1),
            end_time=time_slot.end_time + timedelta(days=1),
        )

        response = panel_client.get(self.get_url(event), {"date": "all"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=response.context_data,
            contains=['id="timetable-date"', '<option value="all"', "date=all"],
        )
        context = response.context
        grid = context["grid"]
        assert [day.date for day in grid.days] == [
            time_slot.start_time.date(),
            second_slot.start_time.date(),
        ]
        assert grid.date_selection == "all"
        assert context["date_selection"] == "all"
        content = response.content.decode()
        expected_day_count = 2
        assert content.count('class="timetable-calendar ') == 1
        assert content.count('class="timetable-day-grid ') == expected_day_count
        assert content.count('class="timetable-time-axis ') == 1
        assert content.count("Time</div>") == 1
        assert [column.space.pk for column in grid.days[0].columns] == [space.pk]

    def test_grid_declares_one_track_per_room_per_day(
        self, panel_client, event, space, time_slot
    ):
        room_count = 3
        day_count = 2
        for _ in range(room_count - 1):
            SpaceFactory(event=event)
        TimeSlotFactory(
            event=event,
            start_time=time_slot.start_time + timedelta(days=1),
            end_time=time_slot.end_time + timedelta(days=1),
        )

        response = panel_client.get(self.get_url(event), {"date": "all"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=response.context_data,
            # Header and body are laid out from these two numbers alone.
            contains=["--total-columns: 6", "--columns-per-day: 3"],
        )
        grid = response.context["grid"]
        assert len(grid.spaces) == room_count
        assert len(grid.days) == day_count
        assert grid.total_columns == room_count * day_count
        content = response.content.decode()
        assert content.count('class="timetable-room-cell ') == room_count * day_count
        assert space.pk in {column.space.pk for column in grid.days[0].columns}

    def test_single_schedule_day_hides_day_selector(
        self, panel_client, event, time_slot
    ):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=response.context_data,
            not_contains='id="timetable-date"',
        )
        assert time_slot is not None

    def test_grid_session_is_draggable_with_placement_data(
        self, panel_client, event, session, space, time_slot
    ):
        schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event, stats=_scheduled_stats(1), grid=ANY, print_scopes=_scopes(space)
            ),
        )
        content = response.content.decode()
        assert 'draggable="true"' in content
        assert f'data-session-pk="{session.pk}"' in content
        assert 'data-confirmed="false"' in content
        assert 'title="Confirmed"' not in content
        assert time_slot is not None

    def test_grid_marks_confirmed_session(
        self, panel_client, event, session, space, time_slot
    ):
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=start,
            end_time=end,
            session_confirmed=True,
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event, stats=_scheduled_stats(1), grid=ANY, print_scopes=_scopes(space)
            ),
        )
        content = response.content.decode()
        assert 'data-confirmed="true"' in content
        assert 'title="Confirmed"' in content
        assert time_slot is not None

    def test_filters_by_track(self, panel_client, event, space):
        track = Track.objects.create(
            event=event, name="My Track", slug="my-track", is_public=True
        )
        track.spaces.add(space)
        other_space = SpaceFactory(event=event)

        response = panel_client.get(self.get_url(event), {"track": str(track.pk)})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": 2},
                grid=ANY,
                print_scopes=ANY,
                all_tracks=ANY,
                filter_track_pk=track.pk,
            ),
        )
        grid = response.context["grid"]
        space_pks = [s.pk for s in grid.spaces]
        assert space.pk in space_pks
        assert other_space.pk not in space_pks

    def test_auto_selects_single_managed_track(
        self, panel_client, active_user, event, space
    ):
        track = Track.objects.create(
            event=event, name="My Track", slug="my-track", is_public=True
        )
        track.spaces.add(space)
        track.managers.add(active_user)
        other_space = SpaceFactory(event=event)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": 2},
                grid=ANY,
                print_scopes=ANY,
                all_tracks=ANY,
                filter_track_pk=track.pk,
                managed_track_pks={track.pk},
            ),
        )
        grid = response.context["grid"]
        space_pks = [s.pk for s in grid.spaces]
        assert other_space.pk not in space_pks

    # Only a non-numeric room_page falls back to 1; a numeric out-of-range one
    # reaches the context as given, while grid.page stays clamped.
    @pytest.mark.parametrize(
        ("room_page", "echoed_page"), (("0", 0), ("-1", -1), ("abc", 1), ("999", 999))
    )
    def test_room_page_invalid_values_dont_raise(
        self, panel_client, event, room_page, echoed_page
    ):
        response = panel_client.get(self.get_url(event), {"room_page": room_page})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(event, room_page=echoed_page),
        )
        assert response.context["grid"].page == 1

    def test_room_pagination_renders_prev_and_next_on_middle_page(
        self, panel_client, event, time_slot
    ):
        room_count = 2 * TIMETABLE_ROOM_PAGE_SIZE + 1
        expected_pages = math.ceil(room_count / TIMETABLE_ROOM_PAGE_SIZE)
        middle_page = 2
        for _ in range(room_count):
            SpaceFactory(event=event)

        response = panel_client.get(self.get_url(event), {"room_page": middle_page})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": room_count},
                grid=ANY,
                print_scopes=ANY,
                room_page=middle_page,
            ),
        )
        grid = response.context["grid"]
        assert grid.page == middle_page
        assert grid.total_pages == expected_pages
        assert time_slot is not None

    def test_grid_marks_session_outside_preferred_slot(
        self, panel_client, event, proposal_category, space
    ):
        session = schedule_outside_preferred_slot(
            event=event, category=proposal_category, space=space
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={
                    "hosts_count": 1,
                    "pending_proposals": 1,
                    "rooms_count": 1,
                    "scheduled_sessions": 1,
                    "total_proposals": 1,
                    "total_sessions": 2,
                },
                grid=ANY,
                print_scopes=_scopes(space),
                categories=ANY,
                slot_violation_session_pks={session.pk},
            ),
        )


class TestPanelBaseHeader:
    """Tests for the shared panel/base.html sidebar and header."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable", kwargs={"slug": event.slug})

    def test_schedule_nav_label_renders_in_english(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=ANY,
            contains='<span class="sidebar-label">Schedule</span>',
            not_contains="Harmonogram",
        )

    def test_single_day_event_shows_one_date(self, panel_client, sphere):
        event = EventFactory(
            sphere=sphere,
            slug="one-day",
            start_time=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 6, 18, 0, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=ANY,
            contains="06 Aug 2026",
            not_contains="06 Aug - 06 Aug",
        )

    def test_multi_day_event_shows_date_range(self, panel_client, sphere):
        event = EventFactory(
            sphere=sphere,
            slug="multi-day",
            start_time=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=ANY,
            contains="06 Aug - 08 Aug 2026",
        )
