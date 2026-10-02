from datetime import UTC, datetime
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
)
from ludamus.pacts import AgendaItemDTO
from ludamus.pacts.legacy import SessionFieldValueDTO
from tests.integration.web.chronology.helpers import make_session_data


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

    def test_days_split_on_the_local_date_with_slots_in_time_order(self):
        # A session's enrollment state is no reason to move its slot: the
        # 10:00 whose sign-up has not opened still reads before the 14:00.
        not_open_yet = make_session_data(is_enrollment_available=False)
        no_sign_up = make_session_data()
        tomorrow = make_session_data()

        days = build_card_days(
            {
                self._hour(10, 14): [no_sign_up],
                self._hour(11, 9): [tomorrow],
                self._hour(10, 10): [not_open_yet],
            }
        )

        assert [day.day_start.date().day for day in days] == [10, 11]
        assert [(slot.hour.hour, slot.sessions) for slot in days[0].slots] == [
            (10, [not_open_yet]),
            (14, [no_sign_up]),
        ]
        assert days[1].slots[0].sessions == [tomorrow]
        # The day headings state the dates, so no label repeats them.
        assert not any(slot.show_date for day in days for slot in day.slots)

    def test_only_the_first_slot_still_to_run_is_marked_now(self):
        days = build_card_days(
            {
                self._hour(10, 8): [make_session_data(is_ended=True)],
                self._hour(10, 10): [
                    make_session_data(is_ended=True),
                    make_session_data(),
                ],
                self._hour(10, 12): [make_session_data()],
            }
        )

        # A slot is over only once every session in it is.
        assert [
            (slot.is_ended, slot.is_first_current) for day in days for slot in day.slots
        ] == [(True, False), (False, True), (False, False)]
        # A single-day schedule has no day heading, so every label keeps its date.
        assert all(slot.show_date for slot in days[0].slots)


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
