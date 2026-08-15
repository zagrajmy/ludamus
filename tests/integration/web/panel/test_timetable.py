import math
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.db.django.models import Facilitator, Space, Track
from ludamus.pacts import EventDTO, ProposalCategoryDTO, TrackDTO
from ludamus.pacts.chronology import MultiselectOptionDTO, SpaceGroupDTO
from ludamus.pacts.legacy import SpaceDTO
from ludamus.specs.timetable import TIMETABLE_ROOM_PAGE_SIZE
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import (
    assert_login_required,
    assert_response,
    assert_response_404,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    empty_grid,
    grid_with,
    panel_context,
    schedule_outside_preferred_slot,
    schedule_session,
    session_position,
    timetable_tab_urls,
)

# The `event` fixture starts at UTC midnight and Warsaw is a whole-hour offset,
# so a slot starting with the event puts the grid's first time label — and its
# day — on the hour.
SLOT_MINUTES = 120
HOUR_MINUTES = 60


def _base_context(event, **stats):
    return {
        **panel_context(event, active_nav="timetable", **stats),
        "all_tracks": [],
        "managed_track_pks": set(),
        "filter_track_pk": None,
    }


def _flat_space_options(event):
    # The picker offers the event's rooms in the repository's order. Every
    # page test but the picker's own builds a flat room list, so the default
    # expectation restates that order rather than the tree walk.
    return [
        MultiselectOptionDTO(value=space.pk, label=space.name)
        for space in Space.objects.filter(event=event).order_by("order", "name")
    ]


def _grid_under(room, *, parent):
    # An event with no time slots renders no days, so the grid is its room
    # columns and nothing else -- and a nested room's header cell names the
    # parent it hangs under, which `grid_with` only spells for top-level rooms.
    return empty_grid().model_copy(
        update={
            "spaces": [SpaceDTO.model_validate(room)],
            "groups": [
                SpaceGroupDTO(parent_pk=parent.pk, parent_name=parent.name, span=1)
            ],
            "total_spaces": 1,
        }
    )


def _print_url(event, **params):
    base = reverse("web:chronology:event-print", kwargs={"slug": event.slug})
    return f"{base}?{urlencode(params)}" if params else base


def _scheduled_stats(count):
    return {"rooms_count": 1, "scheduled_sessions": count, "total_sessions": count}


def _day_start(event):
    return localtime(event.start_time)


def _page_context(event, *, stats=None, **overrides):
    return {
        **_base_context(event, **(stats or {})),
        "room_page": 1,
        "grid": empty_grid(),
        "conflicts": [],
        "conflicts_count": 0,
        "categories": [],
        "category_pk": None,
        "max_duration_minutes": None,
        "search": "",
        "space_options": _flat_space_options(event),
        "filter_space_pks": set(),
        "facilitator_options": [],
        "filter_facilitator_pks": set(),
        "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
        "date_selection": "all",
        "slug": event.slug,
        "tab_urls": timetable_tab_urls(event),
        "active_tab": "timetable",
        "print_url": _print_url(event),
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

    def test_search_query_param_reaches_the_context(self, panel_client, event):
        response = panel_client.get(self.get_url(event), {"search": " dragons "})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(event, search="dragons"),
        )

    def test_print_link_carries_track_and_day_filters(
        self, authenticated_client, active_user, sphere, event, space, time_slot
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        day = time_slot.start_time.date()

        response = authenticated_client.get(
            self.get_url(event), {"track": track.pk, "date": day.isoformat()}
        )

        base = reverse("web:chronology:event-print", kwargs={"slug": event.slug})
        expected_print_url = (
            f"{base}?material=track-timetable&track=main-track"
            f"&start={day.isoformat()}T00%3A00&hours=24"
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": 1},
                all_tracks=[TrackDTO.model_validate(track)],
                filter_track_pk=track.pk,
                # The track has no rooms, so filtering by it empties the grid
                # while the day still sets its span.
                grid=grid_with(
                    spaces=[],
                    day_start=_day_start(event),
                    total_minutes=SLOT_MINUTES,
                    date_selection=day,
                ),
                date_selection=day,
                print_url=expected_print_url,
            ),
        )

    def test_grid_shows_spaces_and_time_labels(
        self, panel_client, event, space, time_slot
    ):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": 1},
                grid=grid_with(
                    spaces=[space],
                    day_start=_day_start(event),
                    total_minutes=SLOT_MINUTES,
                ),
            ),
        )
        assert time_slot is not None

    def test_grid_contains_scheduled_session(
        self, panel_client, event, session, space, time_slot
    ):
        item = schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats=_scheduled_stats(1),
                grid=grid_with(
                    spaces=[space],
                    day_start=_day_start(event),
                    total_minutes=SLOT_MINUTES,
                    sessions_by_space={
                        space.pk: [
                            session_position(
                                item, start_minutes=0, duration_minutes=HOUR_MINUTES
                            )
                        ]
                    },
                ),
            ),
        )
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
            context_data=_page_context(
                event,
                stats={"rooms_count": 1},
                grid=grid_with(
                    spaces=[space],
                    day_start=_day_start(event),
                    extra_days=1,
                    total_minutes=SLOT_MINUTES,
                ),
            ),
        )
        assert second_slot.start_time.date() == time_slot.start_time.date() + timedelta(
            days=1
        )

    def test_grid_declares_one_track_per_room_per_day(
        self, panel_client, event, time_slot
    ):
        room_count = 3
        day_count = 2
        # Named so the repository's (order, name) ordering fixes which room
        # lands in which column.
        rooms = [
            SpaceFactory(event=event, name=f"Room {index:02d}")
            for index in range(room_count)
        ]
        TimeSlotFactory(
            event=event,
            start_time=time_slot.start_time + timedelta(days=1),
            end_time=time_slot.end_time + timedelta(days=1),
        )

        response = panel_client.get(self.get_url(event), {"date": "all"})

        # Header and body are laid out from `total_columns` and the per-day
        # room count alone, so the grid DTO is the whole contract here.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": room_count},
                grid=grid_with(
                    spaces=rooms,
                    day_start=_day_start(event),
                    extra_days=day_count - 1,
                    total_minutes=SLOT_MINUTES,
                ),
            ),
        )

    def test_single_schedule_day_offers_no_choice_of_day(
        self, panel_client, event, time_slot
    ):
        response = panel_client.get(self.get_url(event))

        # One available date is what hides the day selector; the e2e run
        # asserts the control is gone.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                grid=grid_with(
                    spaces=[], day_start=_day_start(event), total_minutes=SLOT_MINUTES
                ),
            ),
        )
        assert time_slot is not None

    def test_grid_session_is_draggable_with_placement_data(
        self, panel_client, event, session, space, time_slot
    ):
        item = schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats=_scheduled_stats(1),
                grid=grid_with(
                    spaces=[space],
                    day_start=_day_start(event),
                    total_minutes=SLOT_MINUTES,
                    sessions_by_space={
                        space.pk: [
                            session_position(
                                item, start_minutes=0, duration_minutes=HOUR_MINUTES
                            )
                        ]
                    },
                ),
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
        item = AgendaItemFactory(
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
                event,
                stats=_scheduled_stats(1),
                grid=grid_with(
                    spaces=[space],
                    day_start=_day_start(event),
                    total_minutes=SLOT_MINUTES,
                    sessions_by_space={
                        space.pk: [
                            session_position(
                                item, start_minutes=0, duration_minutes=HOUR_MINUTES
                            )
                        ]
                    },
                ),
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
                grid=grid_with(spaces=[space]),
                # The track filter is carried into the print link.
                print_url=_print_url(
                    event, material="track-timetable", track=track.slug
                ),
                all_tracks=[TrackDTO.model_validate(track)],
                filter_track_pk=track.pk,
            ),
        )
        assert other_space is not None

    def test_track_from_another_event_is_not_found(self, panel_client, sphere, event):
        # Panel access proves this organizer manages `event`, not the pk in the
        # query string. Rendering unfiltered would read as a working filter.
        other_track = Track.objects.create(
            event=EventFactory(sphere=sphere),
            name="Other",
            slug="other-track",
            is_public=True,
        )

        response = panel_client.get(self.get_url(event), {"track": str(other_track.pk)})

        assert_response_404(response)

    def test_filters_by_space_branch(
        self, authenticated_client, active_user, sphere, event, space
    ):
        sphere.managers.add(active_user)
        # Named so the picker's order is the tree's, not a generated name's.
        space.name = "Aula"
        space.save()
        floor = SpaceFactory(event=event, name="Floor 2")
        room = SpaceFactory(event=event, name="Room 201", parent=floor)

        response = authenticated_client.get(
            self.get_url(event), {"space": str(floor.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                grid=_grid_under(room, parent=floor),
                space_options=[
                    MultiselectOptionDTO(value=space.pk, label="Aula", depth=0),
                    MultiselectOptionDTO(value=floor.pk, label="Floor 2", depth=0),
                    MultiselectOptionDTO(value=room.pk, label="Room 201", depth=1),
                ],
                filter_space_pks={floor.pk},
                stats={"rooms_count": 1 + 2},  # the fixture space, floor, room
            ),
        )
        assert [s.pk for s in response.context_data["grid"].spaces] == [room.pk]

    def test_space_from_another_event_narrows_to_nothing(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ours = SpaceFactory(event=event, name="Ours")
        other_event = EventFactory(sphere=sphere)
        foreign_space = SpaceFactory(event=other_event, name="Theirs")

        response = authenticated_client.get(
            self.get_url(event), {"space": str(foreign_space.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                # The sphere's events come back newest first.
                events=[
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
                space_options=[
                    MultiselectOptionDTO(value=ours.pk, label="Ours", depth=0)
                ],
                filter_space_pks={foreign_space.pk},
                stats={"rooms_count": 1},  # the foreign one belongs elsewhere
            ),
        )

    def test_space_options_carry_the_whole_tree_with_depth(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        building = SpaceFactory(event=event, name="Building A")
        room = SpaceFactory(event=event, name="Room 1", parent=building)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                grid=_grid_under(room, parent=building),
                space_options=[
                    MultiselectOptionDTO(
                        value=building.pk, label="Building A", depth=0
                    ),
                    MultiselectOptionDTO(value=room.pk, label="Room 1", depth=1),
                ],
                stats={"rooms_count": 1 + 1},  # the building and its room
            ),
        )

    def test_filters_the_grid_by_facilitator(
        self, authenticated_client, active_user, sphere, event, session, space
    ):
        sphere.managers.add(active_user)
        # On the hour, so the slot's own window is the grid's time axis.
        start = event.start_time.replace(minute=0, second=0, microsecond=0)
        TimeSlotFactory(
            event=event, start_time=start, end_time=start + timedelta(hours=2)
        )
        hers = AgendaItemFactory(
            session=session,
            space=space,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )
        other = SessionFactory(category=session.category, event=event)
        AgendaItemFactory(
            session=other,
            space=space,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=2),
        )
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(alice)

        response = authenticated_client.get(
            self.get_url(event), {"facilitator": str(alice.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                grid=grid_with(
                    spaces=[space],
                    day_start=localtime(start),
                    total_minutes=2 * HOUR_MINUTES,
                    sessions_by_space={
                        space.pk: [
                            session_position(
                                hers, start_minutes=0, duration_minutes=HOUR_MINUTES
                            )
                        ]
                    },
                ),
                space_options=[
                    MultiselectOptionDTO(value=space.pk, label=space.name, depth=0)
                ],
                filter_facilitator_pks={alice.pk},
                facilitator_options=[
                    # No columns configured for the event, so the picker falls
                    # back to every built-in one under the name.
                    MultiselectOptionDTO(
                        value=alice.pk,
                        label="Alice",
                        meta="Linked User: None · Sessions: 1 · Accreditation: None",
                    )
                ],
                stats={
                    "rooms_count": 1,
                    "scheduled_sessions": 1 + 1,  # hers and the other one
                    "total_sessions": 1 + 1,
                },
            ),
        )

    def test_facilitator_from_another_event_empties_the_grid(
        self, authenticated_client, active_user, sphere, event, session, space
    ):
        sphere.managers.add(active_user)
        start = event.start_time.replace(minute=0, second=0, microsecond=0)
        TimeSlotFactory(
            event=event, start_time=start, end_time=start + timedelta(hours=2)
        )
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )
        other_event = EventFactory(sphere=sphere)
        foreign = Facilitator.objects.create(
            event=other_event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.get(
            self.get_url(event), {"facilitator": str(foreign.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                # Her session is scheduled, but a foreign pk matches nobody
                # here, so the room's column comes back empty.
                grid=grid_with(
                    spaces=[space],
                    day_start=localtime(start),
                    total_minutes=2 * HOUR_MINUTES,
                ),
                # The sphere's events come back newest first.
                events=[
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
                space_options=[
                    MultiselectOptionDTO(value=space.pk, label=space.name, depth=0)
                ],
                filter_facilitator_pks={foreign.pk},
                stats={"rooms_count": 1, "scheduled_sessions": 1, "total_sessions": 1},
            ),
        )

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
                grid=grid_with(spaces=[space]),
                print_url=_print_url(
                    event, material="track-timetable", track=track.slug
                ),
                all_tracks=[TrackDTO.model_validate(track)],
                filter_track_pk=track.pk,
                managed_track_pks={track.pk},
            ),
        )
        assert other_space is not None

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
        # Named so the repository's (order, name) ordering — and therefore
        # which rooms land on page 2 — is unambiguous.
        rooms = [
            SpaceFactory(event=event, name=f"Room {index:02d}")
            for index in range(room_count)
        ]
        page_start = (middle_page - 1) * TIMETABLE_ROOM_PAGE_SIZE

        response = panel_client.get(self.get_url(event), {"room_page": middle_page})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable.html",
            context_data=_page_context(
                event,
                stats={"rooms_count": room_count},
                grid=grid_with(
                    spaces=rooms[page_start : page_start + TIMETABLE_ROOM_PAGE_SIZE],
                    day_start=_day_start(event),
                    total_minutes=SLOT_MINUTES,
                    page=middle_page,
                    total_pages=expected_pages,
                    total_spaces=room_count,
                ),
                room_page=middle_page,
            ),
        )
        assert time_slot is not None

    def test_grid_marks_session_outside_preferred_slot(
        self, panel_client, event, proposal_category, space, time_slot
    ):
        # `time_slot` opens the grid at the event start; without it the window
        # only covers the preferred slot and the violating block falls off it.
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
                grid=grid_with(
                    spaces=[space],
                    day_start=_day_start(event),
                    total_minutes=6 * HOUR_MINUTES,
                    sessions_by_space={
                        space.pk: [
                            session_position(
                                session.agenda_item,
                                start_minutes=0,
                                duration_minutes=HOUR_MINUTES,
                                state="slot_violation",
                            )
                        ]
                    },
                ),
                categories=[ProposalCategoryDTO.model_validate(proposal_category)],
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
            context_data=_page_context(event),
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
            context_data=_page_context(event),
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
            context_data=_page_context(event),
            contains="06 Aug - 08 Aug 2026",
        )
