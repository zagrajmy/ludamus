from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Track
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import (
    TIMETABLE_SLOT_MINUTES,
    TIMETABLE_SNAP_MINUTES,
    TimetableGridDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _empty_grid():
    return TimetableGridDTO(
        spaces=[],
        columns=[],
        groups=[],
        time_labels=[],
        total_minutes=0,
        event_start_iso="",
        slot_minutes=TIMETABLE_SLOT_MINUTES,
        snap_minutes=TIMETABLE_SNAP_MINUTES,
        page=1,
        total_pages=1,
        total_spaces=0,
        available_dates=[],
        selected_date=None,
    )


def _base_context(event):
    return {
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
        "all_tracks": [],
        "managed_track_pks": set(),
        "filter_track_pk": None,
    }


class TestTimetablePageView:
    """Tests for /panel/event/<slug>/timetable/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable", kwargs={"slug": event.slug})

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
        url = reverse("panel:timetable", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_for_sphere_manager_empty_grid(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data={
                **_base_context(event),
                "room_page": 1,
                "grid": _empty_grid(),
                "conflict_session_pks": set(),
                "conflicts_count": 0,
                "categories": [],
                "category_pk": None,
                "max_duration_minutes": None,
                "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
                "slot_violation_session_pks": set(),
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
                "print_scopes": [],
            },
        )
        assert response.context["grid"].spaces == []

    def test_grid_shows_spaces_and_time_labels(
        self, authenticated_client, active_user, sphere, event, space, time_slot
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        grid = response.context["grid"]
        assert len(grid.spaces) == 1
        assert grid.spaces[0].pk == space.pk
        assert len(grid.time_labels) > 0
        assert grid.selected_date is not None
        assert grid.available_dates == [grid.selected_date]
        assert time_slot is not None

    def test_grid_contains_scheduled_session(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        time_slot,
    ):
        sphere.managers.add(active_user)
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        grid = response.context["grid"]
        col = next(c for c in grid.columns if c.space.pk == space.pk)
        assert len(col.sessions) == 1
        assert col.sessions[0].agenda_item.session_title == session.title
        assert time_slot is not None

    def test_filters_by_track(
        self, authenticated_client, active_user, sphere, event, space
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="My Track", slug="my-track", is_public=True
        )
        track.spaces.add(space)
        other_space = SpaceFactory(event=event)

        response = authenticated_client.get(
            self.get_url(event), {"track": str(track.pk)}
        )

        assert response.status_code == HTTPStatus.OK
        grid = response.context["grid"]
        space_pks = [s.pk for s in grid.spaces]
        assert space.pk in space_pks
        assert other_space.pk not in space_pks

    def test_auto_selects_single_managed_track(
        self, authenticated_client, active_user, sphere, event, space
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="My Track", slug="my-track", is_public=True
        )
        track.spaces.add(space)
        track.managers.add(active_user)
        other_space = SpaceFactory(event=event)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["filter_track_pk"] == track.pk
        grid = response.context["grid"]
        space_pks = [s.pk for s in grid.spaces]
        assert other_space.pk not in space_pks

    @pytest.mark.parametrize("room_page", ("0", "-1", "abc", "999"))
    def test_room_page_invalid_values_dont_raise(
        self, authenticated_client, active_user, sphere, event, room_page
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.get_url(event), {"room_page": room_page}
        )

        assert response.status_code == HTTPStatus.OK

    def test_grid_marks_session_outside_preferred_slot(
        self, authenticated_client, active_user, sphere, event, proposal_category, space
    ):
        sphere.managers.add(active_user)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        preferred = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=4),
            end_time=event.start_time + timedelta(hours=6),
        )
        session.time_slots.add(preferred)
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["slot_violation_session_pks"] == {session.pk}
        assert response.context["conflict_session_pks"] == set()
