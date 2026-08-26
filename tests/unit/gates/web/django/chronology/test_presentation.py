from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from ludamus.gates.web.django.chronology.event_presentation import (
    CloudPill,
    DisplayFieldRow,
    SessionData,
    build_display_field_row,
    flatten_cloud_overflow,
)
from ludamus.gates.web.django.chronology.schedule import (
    RoomLanes,
    RoomLaneTile,
    build_room_lanes,
    build_schedule_days,
    group_sessions_by_state,
)
from ludamus.pacts import NO_LOCATION, AgendaItemDTO
from ludamus.pacts.legacy import SessionFieldValueDTO

_HOUR_SECONDS = 3600
_REPEATED_HOUR = 2
_REPEATED_HOUR_COUNT = 2


def _positioned_room_tiles(lanes: RoomLanes) -> list[tuple[int, RoomLaneTile]]:
    return [
        (row_index, tile)
        for row_index, row in enumerate(lanes.rows, start=1)
        for tile in row.starting_tiles
    ]


def _room_tiles(lanes: RoomLanes) -> list[RoomLaneTile]:
    return [tile for _, tile in _positioned_room_tiles(lanes)]


def _make_session_data(
    effective_participants_limit: int = 10, enrolled_count: int = 0, **overrides
) -> SessionData:
    defaults = {
        "agenda_item": MagicMock(),
        "is_enrollment_available": True,
        "presenter": MagicMock(),
        "session": MagicMock(),
        "is_full": enrolled_count >= effective_participants_limit,
        "effective_participants_limit": effective_participants_limit,
        "enrolled_count": enrolled_count,
        "session_participations": [],
        "loc": MagicMock(),
    }
    return SessionData(**(defaults | overrides))


class TestSessionDataSpotsLeft:
    def test_no_enrollments(self):
        data = _make_session_data(effective_participants_limit=10, enrolled_count=0)

        assert data.spots_left == data.effective_participants_limit

    def test_some_enrollments(self):
        data = _make_session_data(effective_participants_limit=10, enrolled_count=3)

        assert (
            data.spots_left == data.effective_participants_limit - data.enrolled_count
        )

    def test_full(self):
        data = _make_session_data(effective_participants_limit=10, enrolled_count=10)

        assert data.spots_left == 0

    def test_over_limit_clamps_to_zero(self):
        data = _make_session_data(effective_participants_limit=5, enrolled_count=7)

        assert data.spots_left == 0

    def test_zero_limit_has_no_spots(self):
        data = _make_session_data(effective_participants_limit=0, enrolled_count=5)

        assert data.spots_left == 0


class TestSessionDataTakesEnrollment:
    @pytest.mark.parametrize(("limit", "expected"), ((0, False), (1, True), (30, True)))
    def test_reads_the_sessions_own_limit(self, limit, expected):
        session = MagicMock()
        session.participants_limit = limit
        data = _make_session_data(session=session)

        assert data.takes_enrollment is expected

    def test_ignores_a_window_zeroed_effective_limit(self):
        session = MagicMock()
        session.participants_limit = 30
        data = _make_session_data(effective_participants_limit=0, session=session)

        assert data.takes_enrollment is True


def _availability_data(limit: int = 30, **overrides) -> SessionData:
    session = MagicMock()
    session.participants_limit = limit
    return _make_session_data(session=session, **overrides)


class TestSessionDataAvailability:
    def test_an_ended_session_wins_over_every_other_term(self):
        data = _availability_data(
            is_ended=True, should_show_as_inactive=True, is_full=True
        )

        assert data.availability == "ended"

    def test_a_session_shut_by_its_end_time_is_in_progress(self):
        data = _availability_data(should_show_as_inactive=True, is_full=True)

        assert data.availability == "in-progress"

    def test_a_session_without_enrollment_leaves_before_the_window_is_asked(self):
        data = _availability_data(limit=0, is_enrollment_available=False, is_full=True)

        assert data.availability == "no-enrollment"

    def test_a_shut_window_is_unavailable(self):
        data = _availability_data(is_enrollment_available=False)

        assert data.availability == "unavailable"

    def test_capacity_and_free_seats_come_last(self):
        assert _availability_data(is_full=True).availability == "full"
        assert _availability_data(is_full=False).availability == "available"


class TestSessionDataSpotsScarce:
    @pytest.mark.parametrize(
        ("limit", "enrolled", "expected"),
        (
            (10, 0, False),
            (10, 5, False),
            (10, 7, False),
            (10, 8, False),
            (10, 9, True),
            (10, 10, True),
            (5, 4, False),
            (5, 5, True),
            (1, 1, True),
            (1, 0, False),
        ),
    )
    def test_threshold(self, limit, enrolled, expected):
        data = _make_session_data(
            effective_participants_limit=limit, enrolled_count=enrolled
        )

        assert data.spots_scarce is expected

    def test_zero_limit_is_not_scarce(self):
        data = _make_session_data(effective_participants_limit=0, enrolled_count=0)

        assert data.spots_scarce is False


class TestSessionDataWaitingCount:
    def test_default_is_zero(self):
        data = _make_session_data()

        assert data.waiting_count == 0

    def test_explicit_value(self):
        waiting = 3
        data = _make_session_data(waiting_count=waiting)

        assert data.waiting_count == waiting


def _loc(**overrides):
    return {**NO_LOCATION, **overrides}


class TestSessionDataLocationLabel:
    def test_returns_full_tree_path(self):
        data = _make_session_data(loc=_loc(path="Hotel Mariot > Sala A > Stół 1"))

        assert data.location_label == "Hotel Mariot > Sala A > Stół 1"

    def test_empty_path_returns_empty(self):
        data = _make_session_data(loc=_loc())

        assert not data.location_label


class TestSessionDataFilterCategories:
    def test_empty_without_tracks_or_category(self):
        data = _make_session_data()

        assert not data.filter_categories

    def test_track_names_become_track_pairs(self):
        data = _make_session_data(track_names=["Main", "Side"])

        assert data.filter_categories == "__track:Main;__track:Side"

    def test_category_becomes_category_pair(self):
        data = _make_session_data(category_name="RPG")

        assert data.filter_categories == "__category:RPG"

    def test_track_and_category_combined(self):
        data = _make_session_data(track_names=["Main"], category_name="RPG")

        assert data.filter_categories == "__track:Main;__category:RPG"

    def test_prepends_public_field_tags(self):
        data = _make_session_data(
            field_values=[
                SessionFieldValueDTO(
                    field_name="System",
                    field_question="",
                    field_slug="system",
                    field_type="select",
                    is_public=True,
                    value=["D&D"],
                )
            ],
            track_names=["Main"],
            category_name="RPG",
        )

        assert data.filter_categories == "system:D&D;__track:Main;__category:RPG"


class TestBuildScheduleDays:
    def test_skips_unscheduled_pending_proposal(self):
        pending = _make_session_data(agenda_item=None)
        scheduled = _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, 10, 12, tzinfo=UTC),
                end_time=datetime(2026, 7, 10, 14, tzinfo=UTC),
                pk=1,
                session_confirmed=True,
            )
        )

        days = build_schedule_days({1: pending, 2: scheduled})

        assert len(days) == 1
        assert [tile.data for tile in days[0].hours[0].tiles] == [scheduled]

    def test_only_pending_proposals_yield_no_days(self):
        pending = _make_session_data(agenda_item=None)

        assert not build_schedule_days({1: pending})


class TestNightSessions:
    @staticmethod
    def _night_session() -> SessionData:
        tz = timezone.get_current_timezone()
        return _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, 10, 22, tzinfo=tz),
                end_time=datetime(2026, 7, 11, 2, tzinfo=tz),
                pk=1,
                session_confirmed=True,
            ),
            loc=_loc(space_name="Sala A", parent_slug="hall", parent_name="Hall"),
        )

    def test_session_crossing_midnight_lands_on_both_days(self):
        night = self._night_session()

        days = build_schedule_days({1: night})

        assert [[hour.start.hour for hour in day.hours] for day in days] == [[22], [0]]
        assert [[tile.data for tile in day.hours[0].tiles] for day in days] == [
            [night],
            [night],
        ]

    def test_room_lanes_clip_the_night_session_at_midnight(self):
        lanes = build_room_lanes(build_schedule_days({1: self._night_session()}))

        # Both days share one grid. The first day opens it, so its two hours are
        # rows 1 and 2; the seam that opens the second day takes row 3, which is
        # the one row-numbering invariant worth pinning.
        assert [
            (row.day, row.hour.hour if row.hour else None) for row in lanes.rows
        ] == [(0, 22), (0, 23), (1, None), (1, 0), (1, 1)]
        assert [
            (row, tile.row_span) for row, tile in _positioned_room_tiles(lanes)
        ] == [(1, 2), (4, 2)]
        # Span rules are emitted per distinct height, not per row.
        assert lanes.spans == [2]


class TestDaylightSavingRows:
    @staticmethod
    def _session(*, start: datetime, end: datetime) -> SessionData:
        return _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=start, end_time=end, pk=1, session_confirmed=True
            ),
            loc=_loc(space_name="Sala A", parent_slug="hall", parent_name="Hall"),
        )

    @pytest.mark.parametrize(
        ("start", "end", "expected_hours"),
        (
            (
                datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
                datetime(2026, 3, 29, 2, 30, tzinfo=UTC),
                [(1, 60), (3, 120), (4, 120)],
            ),
            (
                datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
                datetime(2026, 10, 25, 2, 30, tzinfo=UTC),
                [(2, 120), (2, 60), (3, 60)],
            ),
        ),
    )
    def test_rows_follow_real_hours_across_clock_changes(
        self, start: datetime, end: datetime, expected_hours: list[tuple[int, int]]
    ):
        with timezone.override("Europe/Warsaw"):
            lanes = build_room_lanes(
                build_schedule_days({1: self._session(start=start, end=end)})
            )

        hour_rows = [row for row in lanes.rows if row.hour and row.hour_end]
        assert [
            (
                row.hour.hour,
                int((row.hour.utcoffset() or timedelta()).total_seconds() / 60),
            )
            for row in hour_rows
        ] == expected_hours
        assert all(
            row.hour_end.timestamp() - row.hour.timestamp() == _HOUR_SECONDS
            for row in hour_rows
        )
        assert len({row.slot_key for row in hour_rows}) == len(hour_rows)
        assert [tile.row_span for tile in _room_tiles(lanes)] == [3]

    @pytest.mark.parametrize(
        ("start", "expected_zone"),
        (
            (datetime(2026, 10, 25, 0, 15, tzinfo=UTC), "CEST"),
            (datetime(2026, 10, 25, 1, 15, tzinfo=UTC), "CET"),
        ),
    )
    def test_single_repeated_hour_still_names_its_zone(
        self, start: datetime, expected_zone: str
    ):
        with timezone.override("Europe/Warsaw"):
            days = build_schedule_days(
                {1: self._session(start=start, end=start + timedelta(minutes=30))}
            )
            lanes = build_room_lanes(days)

        assert len(days[0].hours) == 1
        assert days[0].hours[0].is_repeated
        assert days[0].hours[0].start.tzname() == expected_zone
        session_row = next(row for row in lanes.rows if row.starting_tiles)
        assert session_row.is_repeated
        assert session_row.hour
        assert session_row.hour.tzname() == expected_zone

    def test_session_crossing_repeated_hours_keeps_both_offsets(self):
        with timezone.override("Europe/Warsaw"):
            days = build_schedule_days(
                {
                    1: self._session(
                        start=datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
                        end=datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
                    )
                }
            )

        tile = days[0].hours[0].tiles[0]
        assert tile.start.hour == tile.end.hour
        assert tile.start.utcoffset() != tile.end.utcoffset()
        assert tile.start.tzname() == "CEST"
        assert tile.end.tzname() == "CET"

    def test_repeated_wall_hours_have_distinct_targets(self):
        with timezone.override("Europe/Warsaw"):
            days = build_schedule_days(
                {
                    1: self._session(
                        start=datetime(2026, 10, 25, 0, 15, tzinfo=UTC),
                        end=datetime(2026, 10, 25, 0, 45, tzinfo=UTC),
                    ),
                    2: self._session(
                        start=datetime(2026, 10, 25, 1, 15, tzinfo=UTC),
                        end=datetime(2026, 10, 25, 1, 45, tzinfo=UTC),
                    ),
                }
            )
            lanes = build_room_lanes(days)

        expected_hours = [_REPEATED_HOUR] * _REPEATED_HOUR_COUNT
        assert [hour.start.hour for hour in days[0].hours] == expected_hours
        assert all(hour.is_repeated for hour in days[0].hours)
        assert len({hour.slot_key for hour in days[0].hours}) == _REPEATED_HOUR_COUNT
        rows = [row for row in lanes.rows if row.starting_tiles]
        assert [row.hour.hour for row in rows if row.hour] == expected_hours
        assert all(row.is_repeated for row in rows)
        assert len({row.slot_key for row in rows}) == _REPEATED_HOUR_COUNT


class TestRoomLaneColumns:
    @staticmethod
    def _session(*, space_name: str, sort_key: str, day: int) -> SessionData:
        tz = timezone.get_current_timezone()
        return _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, day, 10, tzinfo=tz),
                end_time=datetime(2026, 7, day, 11, tzinfo=tz),
                pk=day,
                session_confirmed=True,
            ),
            loc=_loc(space_name=space_name, parent_name="", sort_key=sort_key),
        )

    def test_a_room_used_on_one_day_keeps_its_column_on_every_other(self):
        # Rooms are the outer axis, so the column set is the union across days
        # and a room idle on a day shows the gap rather than shifting its
        # neighbours into it.
        sessions = {
            1: self._session(space_name="Sala A", sort_key="000000|Sala A|a", day=10),
            2: self._session(space_name="Sala B", sort_key="000001|Sala B|b", day=11),
        }

        lanes = build_room_lanes(build_schedule_days(sessions))

        assert [lane.name for lane in lanes.rooms] == ["Sala A", "Sala B"]
        # Day one's session holds column 1, day two's holds column 2 — neither
        # day renumbers the columns for itself.
        assert [(tile.col, row) for row, tile in _positioned_room_tiles(lanes)] == [
            (1, 1),
            (2, 3),
        ]

    def test_no_schedule_makes_no_rows(self):
        lanes = build_room_lanes([])

        assert not lanes.rows
        assert not lanes.rooms


class TestRoomLaneConflicts:
    @staticmethod
    def _session(*, pk: int, start_hour: int, end_hour: int) -> SessionData:
        tz = timezone.get_current_timezone()
        return _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, 10, start_hour, tzinfo=tz),
                end_time=datetime(2026, 7, 10, end_hour, tzinfo=tz),
                pk=pk,
                session_confirmed=True,
            ),
            session=MagicMock(pk=pk, title=f"Session {pk}"),
            loc=_loc(
                space_name="Sala A", parent_name="", sort_key="000000|Sala A|sala-a"
            ),
        )

    def test_exact_conflicts_get_separate_visual_lanes(self):
        lanes = build_room_lanes(
            build_schedule_days(
                {
                    1: self._session(pk=1, start_hour=10, end_hour=11),
                    2: self._session(pk=2, start_hour=10, end_hour=11),
                }
            )
        )

        assert [(tile.lane_index, tile.lane_count) for tile in _room_tiles(lanes)] == [
            (0, 2),
            (1, 2),
        ]
        assert lanes.lane_indices == [0, 1]
        assert lanes.lane_counts == [2]

    def test_partial_conflicts_keep_their_lanes_across_rows(self):
        lanes = build_room_lanes(
            build_schedule_days(
                {
                    1: self._session(pk=1, start_hour=10, end_hour=12),
                    2: self._session(pk=2, start_hour=11, end_hour=13),
                }
            )
        )

        assert [
            (row, tile.row_span, tile.lane_index, tile.lane_count)
            for row, tile in _positioned_room_tiles(lanes)
        ] == [(1, 2, 0, 2), (2, 2, 1, 2)]


class TestRoomLaneOrdering:
    @staticmethod
    def _in_room(*, parent_name: str, space_name: str, sort_key: str) -> SessionData:
        tz = timezone.get_current_timezone()
        return _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, 10, 10, tzinfo=tz),
                end_time=datetime(2026, 7, 10, 11, tzinfo=tz),
                pk=1,
                session_confirmed=True,
            ),
            loc=_loc(space_name=space_name, parent_name=parent_name, sort_key=sort_key),
        )

    def test_columns_follow_the_space_tree_not_the_alphabet(self):
        # "Aula" sorts first alphabetically but sits on the second floor, which
        # the organizer ordered last.
        sessions = {
            1: self._in_room(
                parent_name="Piętro 2",
                space_name="Aula",
                sort_key="000001|Piętro 2|p2|000000|Aula|aula",
            ),
            2: self._in_room(
                parent_name="Piętro 1",
                space_name="Sala B",
                sort_key="000000|Piętro 1|p1|000001|Sala B|sala-b",
            ),
            3: self._in_room(
                parent_name="Piętro 1",
                space_name="Sala A",
                sort_key="000000|Piętro 1|p1|000000|Sala A|sala-a",
            ),
        }

        lanes = build_room_lanes(build_schedule_days(sessions))

        assert [(lane.group, lane.name, lane.starts_group) for lane in lanes.rooms] == [
            ("Piętro 1", "Sala A", True),
            ("Piętro 1", "Sala B", False),
            ("Piętro 2", "Aula", True),
        ]
        assert [tile.col for tile in lanes.rows[0].starting_tiles] == [1, 2, 3]

    def test_same_named_parents_in_different_branches_stay_apart(self):
        sessions = {
            1: self._in_room(
                parent_name="Parter",
                space_name="Sala A",
                sort_key="000000|Budynek A|a|000000|Parter|parter|000000|Sala A|sala-a",
            ),
            2: self._in_room(
                parent_name="Parter",
                space_name="Sala B",
                sort_key="000001|Budynek B|b|000000|Parter|parter|000000|Sala B|sala-b",
            ),
        }

        lanes = build_room_lanes(build_schedule_days(sessions))

        assert [(lane.group, lane.name, lane.starts_group) for lane in lanes.rooms] == [
            ("Parter", "Sala A", True),
            ("Parter", "Sala B", True),
        ]


class TestGroupSessionsByState:
    @staticmethod
    def _future_session(*, participants_limit: int) -> SessionData:
        session = MagicMock()
        session.participants_limit = participants_limit
        start = datetime.now(tz=UTC) + timedelta(days=1)
        return _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=start,
                end_time=start + timedelta(hours=2),
                pk=1,
                session_confirmed=True,
            ),
            is_enrollment_available=False,
            session=session,
        )

    def test_skips_unscheduled_pending_proposal(self):
        pending = _make_session_data(agenda_item=None)

        assert group_sessions_by_state({1: pending}) == ({}, {}, {})

    def test_future_session_awaiting_its_window_is_not_yet_available(self):
        closed = self._future_session(participants_limit=10)

        _, current, future_unavailable = group_sessions_by_state({1: closed})

        assert not current
        assert list(future_unavailable.values()) == [[closed]]

    def test_future_session_without_enrollment_stays_in_the_schedule(self):
        no_enrollment = self._future_session(participants_limit=0)

        _, current, future_unavailable = group_sessions_by_state({1: no_enrollment})

        assert list(current.values()) == [[no_enrollment]]
        assert not future_unavailable


class TestFlattenCloudOverflow:
    def test_empty(self):
        assert flatten_cloud_overflow([]) == []

    def test_merges_overflow_from_every_field(self):
        system = build_display_field_row(
            SessionFieldValueDTO(
                field_icon="book-open",
                field_name="System",
                field_question="System",
                field_slug="system",
                field_type="select",
                is_public=True,
                value=["a", "b", "c", "d", "e"],
            )
        )
        triggers = build_display_field_row(
            SessionFieldValueDTO(
                field_icon="exclamation-triangle",
                field_name="Triggers",
                field_question="Triggers",
                field_slug="triggers",
                field_type="select",
                is_public=True,
                value=["one", "two", "three", "four", "five", "six"],
            )
        )

        assert flatten_cloud_overflow([system, triggers]) == [
            CloudPill(icon="book-open", value="e"),
            CloudPill(icon="exclamation-triangle", value="five"),
            CloudPill(icon="exclamation-triangle", value="six"),
        ]

    def test_session_data_exposes_one_overflow_list(self):
        row = DisplayFieldRow(
            icon="book-open",
            name="System",
            visible_values=["a", "b", "c", "d"],
            overflow_values=["e", "f"],
        )
        data = _make_session_data(displayed_field_rows=[row])

        assert data.cloud_overflow == [
            CloudPill(icon="book-open", value="e"),
            CloudPill(icon="book-open", value="f"),
        ]
