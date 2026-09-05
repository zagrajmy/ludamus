from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from ludamus.gates.web.django.chronology.event_presentation import (
    CloudPill,
    DisplayFieldRow,
    LocationCrumb,
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
from ludamus.pacts.legacy import SessionFieldValueDTO, SessionStatus
from tests.unit.gates.web.django.chronology.helpers import location, make_session_data


class TestSessionDataSpotsLeft:
    def test_no_enrollments(self):
        data = make_session_data(effective_participants_limit=10, enrolled_count=0)

        assert data.spots_left == data.effective_participants_limit

    def test_some_enrollments(self):
        data = make_session_data(effective_participants_limit=10, enrolled_count=3)

        assert (
            data.spots_left == data.effective_participants_limit - data.enrolled_count
        )

    def test_full(self):
        data = make_session_data(effective_participants_limit=10, enrolled_count=10)

        assert data.spots_left == 0

    def test_over_limit_clamps_to_zero(self):
        data = make_session_data(effective_participants_limit=5, enrolled_count=7)

        assert data.spots_left == 0

    def test_zero_limit_has_no_spots(self):
        data = make_session_data(effective_participants_limit=0, enrolled_count=5)

        assert data.spots_left == 0


class TestSessionDataTakesEnrollment:
    @pytest.mark.parametrize(("limit", "expected"), ((0, False), (1, True), (30, True)))
    def test_reads_the_sessions_own_limit(self, limit, expected):
        session = MagicMock()
        session.participants_limit = limit
        data = make_session_data(session=session)

        assert data.takes_enrollment is expected

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
        data = make_session_data(
            effective_participants_limit=limit, enrolled_count=enrolled
        )

        assert data.spots_scarce is expected

    def test_zero_limit_is_not_scarce(self):
        data = make_session_data(effective_participants_limit=0, enrolled_count=0)

        assert data.spots_scarce is False


class TestSessionDataWaitingCount:
    def test_default_is_zero(self):
        data = make_session_data()

        assert data.waiting_count == 0

    def test_explicit_value(self):
        waiting = 3
        data = make_session_data(waiting_count=waiting)

        assert data.waiting_count == waiting


class TestSessionDataLocationLabel:
    def test_returns_full_tree_path(self):
        data = make_session_data(loc=location(path="Hotel Mariot > Sala A > Stół 1"))

        assert data.location_label == "Hotel Mariot > Sala A > Stół 1"

    def test_empty_path_returns_empty(self):
        data = make_session_data(loc=location())

        assert not data.location_label


class TestSessionDataLocationCrumbs:
    def test_empty_path_returns_empty(self):
        data = make_session_data(loc=location())

        assert not data.location_crumbs

    def test_room_only_filters_to_the_room(self):
        data = make_session_data(
            loc=location(space_id=3, sort_path=((0, "Aula 2: Nassau", 3),))
        )

        assert data.location_crumbs == [
            LocationCrumb(name="Aula 2: Nassau", space_filter="3")
        ]

    def test_floor_and_room_link_to_all_rooms_and_the_room(self):
        data = make_session_data(
            loc=location(
                space_id=3,
                parent_id=2,
                sort_path=((0, "Poziom -1", 2), (0, "Aula 2: Nassau", 3)),
            )
        )

        assert data.location_crumbs == [
            LocationCrumb(name="Poziom -1", space_filter="venue:2"),
            LocationCrumb(name="Aula 2: Nassau", space_filter="3"),
        ]

    def test_building_stays_plain_text(self):
        data = make_session_data(
            loc=location(
                space_id=3,
                parent_id=2,
                sort_path=(
                    (0, "Budynek główny", 1),
                    (0, "Poziom -1", 2),
                    (0, "Aula 2: Nassau", 3),
                ),
            )
        )

        assert data.location_crumbs == [
            LocationCrumb(name="Budynek główny", space_filter=None),
            LocationCrumb(name="Poziom -1", space_filter="venue:2"),
            LocationCrumb(name="Aula 2: Nassau", space_filter="3"),
        ]


class TestSessionDataFilterCategories:
    def test_empty_without_tracks_or_category(self):
        data = make_session_data()

        assert not data.filter_categories

    def test_track_names_become_track_pairs(self):
        data = make_session_data(track_names=["Main", "Side"])

        assert data.filter_categories == "__track:Main;__track:Side"

    def test_category_becomes_category_pair(self):
        data = make_session_data(category_name="RPG")

        assert data.filter_categories == "__category:RPG"

    def test_track_and_category_combined(self):
        data = make_session_data(track_names=["Main"], category_name="RPG")

        assert data.filter_categories == "__track:Main;__category:RPG"

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

    def test_only_pending_proposals_yield_no_days(self):
        pending = make_session_data(agenda_item=None)

        assert not build_schedule_days({1: pending})


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
        data = make_session_data(displayed_field_rows=[row])

        assert data.cloud_overflow == [
            CloudPill(icon="book-open", value="e"),
            CloudPill(icon="book-open", value="f"),
        ]


class TestSessionDataIsPendingClaim:
    @staticmethod
    def _session(*, is_impromptu, status):
        session = MagicMock()
        session.is_impromptu = is_impromptu
        session.status = status
        return session

    def test_an_impromptu_session_still_pending_is_a_claim(self):
        data = make_session_data(
            session=self._session(is_impromptu=True, status=SessionStatus.PENDING)
        )

        assert data.is_pending_claim is True

    def test_an_accepted_claim_no_longer_awaits_anything(self):
        data = make_session_data(
            session=self._session(is_impromptu=True, status=SessionStatus.ACCEPTED)
        )

        assert data.is_pending_claim is False

    def test_an_imported_session_that_kept_pending_is_not_a_claim(self):
        data = make_session_data(
            session=self._session(is_impromptu=False, status=SessionStatus.PENDING)
        )

        assert data.is_pending_claim is False
