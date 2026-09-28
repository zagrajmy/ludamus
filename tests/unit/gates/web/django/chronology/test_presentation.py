from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from ludamus.gates.web.django.chronology.event_presentation import (
    CloudPill,
    SessionData,
    build_display_field_row,
    flatten_cloud_overflow,
)
from ludamus.gates.web.django.chronology.schedule import (
    build_card_days,
    build_schedule_days,
    group_sessions_by_state,
)
from ludamus.pacts import AgendaItemDTO
from ludamus.pacts.legacy import SessionFieldValueDTO
from tests.unit.gates.web.django.chronology.helpers import make_session_data


class TestSessionDataSpotsLeft:
    def test_over_limit_clamps_to_zero(self):
        data = make_session_data(effective_participants_limit=5, enrolled_count=7)

        assert data.spots_left == 0


class TestSessionDataTakesEnrollment:
    def test_ignores_a_window_zeroed_effective_limit(self):
        session = MagicMock()
        session.participants_limit = 30
        data = make_session_data(effective_participants_limit=0, session=session)

        assert data.takes_enrollment is True


def _availability_data(limit: int = 30, **overrides) -> SessionData:
    session = MagicMock()
    session.participants_limit = limit
    return make_session_data(session=session, **overrides)


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


class TestSessionDataSpotsScarce:
    @pytest.mark.parametrize(
        ("limit", "enrolled", "expected"),
        ((10, 8, False), (10, 9, True), (5, 4, False)),
    )
    def test_threshold(self, limit, enrolled, expected):
        data = make_session_data(
            effective_participants_limit=limit, enrolled_count=enrolled
        )

        assert data.spots_scarce is expected

    def test_zero_limit_is_not_scarce(self):
        data = make_session_data(effective_participants_limit=0, enrolled_count=0)

        assert data.spots_scarce is False


class TestSessionDataFilterCategories:
    def test_prepends_public_field_tags(self):
        data = make_session_data(
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
        pending = make_session_data(agenda_item=None)
        scheduled = make_session_data(
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


class TestBuildCardDays:
    @staticmethod
    def _hour(day: int, hour: int) -> datetime:
        return datetime(2026, 7, day, hour, tzinfo=timezone.get_current_timezone())

    def test_days_split_on_the_local_date_with_kinds_in_state_order(self):
        early = make_session_data()
        late = make_session_data()
        tomorrow = make_session_data()

        days = build_card_days(
            ended={self._hour(10, 12): [early]},
            current={self._hour(10, 10): [late], self._hour(11, 9): [tomorrow]},
            future_unavailable={},
        )

        assert [day.day_start.date().day for day in days] == [10, 11]
        # Within a day the ended group keeps its place ahead of the current
        # one, exactly as the single-day page has always read.
        assert [(slot.kind, slot.hour.hour) for slot in days[0].slots] == [
            ("ended", 12),
            ("current", 10),
        ]
        assert days[1].slots[0].sessions == [tomorrow]
        # The day headings state the dates, so no pill repeats them.
        assert not any(slot.show_date for day in days for slot in day.slots)

    def test_only_the_first_current_slot_is_marked_now(self):
        days = build_card_days(
            ended={},
            current={
                self._hour(10, 10): [make_session_data()],
                self._hour(10, 12): [make_session_data()],
            },
            future_unavailable={self._hour(10, 8): [make_session_data()]},
        )

        assert [
            (slot.kind, slot.is_first_current) for day in days for slot in day.slots
        ] == [("current", True), ("current", False), ("future", False)]
        # A single-day schedule has no day heading, so every pill keeps its date.
        assert all(slot.show_date for slot in days[0].slots)


class TestGroupSessionsByState:
    @staticmethod
    def _future_session(*, participants_limit: int) -> SessionData:
        session = MagicMock()
        session.participants_limit = participants_limit
        start = datetime.now(tz=UTC) + timedelta(days=1)
        return make_session_data(
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
        pending = make_session_data(agenda_item=None)

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
