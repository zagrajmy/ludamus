from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from ludamus.gates.web.django.chronology.event_presentation import SessionData
from ludamus.gates.web.django.chronology.schedule import (
    build_room_lanes,
    build_schedule_days,
    group_sessions_by_state,
)
from ludamus.pacts import NO_LOCATION, AgendaItemDTO
from ludamus.pacts.legacy import SessionFieldValueDTO


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
        assert days[0].hours[0].sessions == [scheduled]

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
        assert [day.hours[0].sessions for day in days] == [[night], [night]]

    def test_room_lanes_clip_the_night_session_at_midnight(self):
        lanes = build_room_lanes(build_schedule_days({1: self._night_session()}))

        assert lanes is not None
        # Both days share one grid: the first day's heading takes row 1 and its
        # two hours rows 2 and 3, so the second day's heading lands on row 4.
        assert [mark.row for mark in lanes.day_marks] == [1, 4]
        assert [(mark.start.hour, mark.row) for mark in lanes.hour_marks] == [
            (22, 2),
            (23, 3),
            (0, 5),
            (1, 6),
        ]
        assert [(tile.row_start, tile.row_span) for tile in lanes.tiles] == [
            (2, 2),
            (5, 2),
        ]


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

        assert lanes is not None
        assert [(lane.group, lane.name, lane.starts_group) for lane in lanes.rooms] == [
            ("Piętro 1", "Sala A", True),
            ("Piętro 1", "Sala B", False),
            ("Piętro 2", "Aula", True),
        ]

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

        assert lanes is not None
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
