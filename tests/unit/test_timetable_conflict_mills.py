from datetime import UTC, date, datetime
from itertools import starmap
from unittest.mock import MagicMock

import pytest

from ludamus.mills.timetable import ConflictDetectionService, TimetableOverviewService
from ludamus.pacts.availability import AvailabilityDTO, DayPart
from ludamus.pacts.event import TimeSlotDTO
from ludamus.pacts.timetable import (
    CapacityHoursDTO,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    HeatmapCellDTO,
    HeatmapCellStatus,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
)
from ludamus.pacts.venues import SpaceDTO
from tests.unit.factories import agenda_item_dto
from tests.unit.timetable_helpers import (
    conflict_service,
    event_stub,
    event_track,
    facilitator_stub,
    offered,
    overview_service,
    space_dto,
)

# 10-12 and 12-14 back to back, then a gap, then 15-16.
_SLOTS = ((1, 12, 14), (2, 10, 12), (3, 15, 16))


def _slot_offered(pk: int, opens: int, closes: int) -> AvailabilityDTO:
    return AvailabilityDTO(
        day=date(2026, 1, 1),
        offer=TimeSlotDTO(
            pk=pk,
            start_time=datetime(2026, 1, 1, opens, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, closes, tzinfo=UTC),
        ),
    )


_SUBJECT_SESSION_PK = 10
_OTHER_SESSION_PK = 20
_ROOM_CAPACITY = 10
_SESSION_LIMIT = 25


class TestListAllForTrack:
    """Batched conflict detection: repos are hit once, overlaps found in memory."""

    @staticmethod
    def _uow(*, all_items, subjects=None, spaces=(), facilitators=None):
        uow = MagicMock()
        uow.agenda_items.list_by_event.return_value = all_items
        uow.agenda_items.list_by_track.return_value = (
            all_items if subjects is None else subjects
        )
        uow.spaces.list_by_event.return_value = list(spaces)
        uow.sessions.read_facilitators_by_sessions.return_value = facilitators or {}
        uow.sessions.list_track_names_by_session.return_value = {}
        uow.tracks.read.return_value = event_track(event_pk=1)
        uow.tracks.list_manager_names_by_tracks.return_value = {}
        return uow

    def test_sessions_without_a_space_share_no_room_to_clash_over(self):
        first = agenda_item_dto(
            pk=1, session_id=10, space_id=None, session_title="First"
        )
        second = agenda_item_dto(
            pk=2, session_id=20, space_id=None, session_title="Other"
        )
        uow = self._uow(all_items=[first, second], spaces=[space_dto(1, capacity=2)])

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_space_overlap_detected_and_deduplicated(self):
        first = agenda_item_dto(pk=1, session_id=10, space_id=1, session_title="First")
        second = agenda_item_dto(
            pk=2, session_id=20, space_id=1, session_title="Second"
        )
        uow = self._uow(all_items=[first, second])

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.SPACE_OVERLAP
        assert conflicts[0].subject_session_pk == _SUBJECT_SESSION_PK
        assert conflicts[0].session_pk == _OTHER_SESSION_PK

    def test_disjoint_times_in_same_space_do_not_conflict(self):
        first = agenda_item_dto(pk=1, session_id=10, space_id=1)
        second = agenda_item_dto(
            pk=2,
            session_id=20,
            space_id=1,
            start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow = self._uow(all_items=[first, second])

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_back_to_back_items_do_not_conflict_from_the_later_side(self):
        # A clash is reported from the lower session pk, so that pk goes last.
        earlier = agenda_item_dto(pk=1, session_id=20, space_id=1)
        later = agenda_item_dto(
            pk=2,
            session_id=10,
            space_id=1,
            start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow = self._uow(all_items=[earlier, later])

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_capacity_exceeded_uses_batched_limits(self):
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=_ROOM_CAPACITY,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        item = agenda_item_dto(
            pk=1, session_id=10, space_id=1, session_participants_limit=_SESSION_LIMIT
        )
        uow = self._uow(all_items=[item], spaces=[space])

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.CAPACITY_EXCEEDED
        assert conflicts[0].space_capacity == _ROOM_CAPACITY
        assert conflicts[0].session_limit == _SESSION_LIMIT

    def test_a_room_as_big_as_the_limit_is_not_exceeded(self):
        item = agenda_item_dto(
            pk=1, session_id=10, space_id=1, session_participants_limit=_SESSION_LIMIT
        )
        uow = self._uow(
            all_items=[item], spaces=[space_dto(1, capacity=_SESSION_LIMIT)]
        )

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_a_session_without_a_limit_fits_a_room_of_no_capacity(self):
        item = agenda_item_dto(pk=1, session_id=10, space_id=1)
        uow = self._uow(all_items=[item], spaces=[space_dto(1, capacity=0)])

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_collective_facilitator_overlap_is_not_a_conflict(self):
        subject = agenda_item_dto(pk=1, session_id=10, space_id=1)
        other = agenda_item_dto(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = facilitator_stub(7, is_collective=True)
        uow = self._uow(
            all_items=[subject, other], facilitators={10: [shared], 20: [shared]}
        )

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

        assert not conflicts

    def test_collective_facilitator_still_clashes_over_a_space(self):
        subject = agenda_item_dto(pk=1, session_id=10, space_id=1)
        other = agenda_item_dto(pk=2, session_id=20, space_id=1, session_title="Other")
        shared = facilitator_stub(7, is_collective=True)
        uow = self._uow(
            all_items=[subject, other], facilitators={10: [shared], 20: [shared]}
        )

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

        assert [c.type for c in conflicts] == [ConflictType.SPACE_OVERLAP]

    def test_every_shared_facilitator_is_named_once(self):
        subject = agenda_item_dto(pk=1, session_id=10, space_id=1)
        other = agenda_item_dto(pk=2, session_id=20, space_id=2, session_title="Other")
        alice = facilitator_stub(7, display_name="Alice")
        bob = facilitator_stub(8, display_name="Bob")
        uow = self._uow(
            all_items=[subject, other],
            facilitators={10: [alice, bob], 20: [alice, bob]},
        )

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [c.facilitator_name for c in conflicts] == ["Alice", "Bob"]

    def test_namesakes_shared_by_a_pair_are_two_clashes(self):
        subject = agenda_item_dto(pk=1, session_id=10, space_id=1)
        other = agenda_item_dto(pk=2, session_id=20, space_id=2, session_title="Other")
        first = facilitator_stub(7, display_name="Alice")
        second = facilitator_stub(8, display_name="Alice")
        uow = self._uow(
            all_items=[subject, other],
            facilitators={10: [first, second], 20: [first, second]},
        )

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [c.facilitator_name for c in conflicts] == ["Alice", "Alice"]


class TestListOfferedTimeViolations:
    @staticmethod
    def _uow(*, items, available):
        uow = MagicMock()
        uow.agenda_items.list_by_event.return_value = items
        uow.agenda_items.list_by_track.return_value = items
        uow.sessions.read_availability_by_sessions.return_value = available
        uow.sessions.list_track_names_by_session.return_value = {}
        uow.tracks.read.return_value = event_track(event_pk=1)
        uow.tracks.list_manager_names_by_tracks.return_value = {}
        return uow

    def test_session_in_a_part_its_facilitator_offered_is_not_a_violation(self):
        item = agenda_item_dto(
            pk=1,
            session_id=10,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        uow = self._uow(items=[item], available={10: [offered(1, DayPart.MORNING)]})

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=None, tz=UTC
        )

        assert not violations

    def test_a_block_opening_after_midnight_belongs_to_the_night_before(self):
        # The facilitator answered about Thursday night, so a block opening at
        # 01:00 is judged against the evening it grew out of, not the morning
        # the calendar has just turned over into.
        item = agenda_item_dto(
            pk=1,
            session_id=10,
            start_time=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 3, 0, tzinfo=UTC),
        )
        uow = self._uow(items=[item], available={10: [offered(1, DayPart.NIGHT)]})

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=None, tz=UTC
        )

        assert not violations

    def test_the_right_day_in_the_wrong_part_is_a_violation(self):
        # The day axis alone no longer settles it: a morning placement on a
        # day the facilitator only offered the evening of is still misplaced.
        item = agenda_item_dto(
            pk=1,
            session_id=10,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        uow = self._uow(items=[item], available={10: [offered(1, DayPart.EVENING)]})

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=None, tz=UTC
        )

        assert [violation.session_pk for violation in violations] == [
            _SUBJECT_SESSION_PK
        ]

    @pytest.mark.parametrize(
        ("start_hour", "end_hour", "violates"),
        (
            # Across two back-to-back slots, which read as one window.
            (11, 13, False),
            # In the last slot, past a gap.
            (15, 16, False),
            # Running from the joined window into the gap.
            (13, 15, True),
            # Starting inside a slot is not enough; the whole session must fit.
            (15, 17, True),
        ),
    )
    def test_a_slot_offer_holds_only_sessions_that_fit_in_it(
        self, start_hour, end_hour, violates
    ):
        item = agenda_item_dto(
            pk=1,
            session_id=10,
            start_time=datetime(2026, 1, 1, start_hour, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, end_hour, 0, tzinfo=UTC),
        )
        slots = list(starmap(_slot_offered, _SLOTS))
        uow = self._uow(items=[item], available={10: slots})

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=None, tz=UTC
        )

        assert bool(violations) is violates

    def test_a_session_with_nothing_offered_is_not_a_violation(self):
        item = agenda_item_dto(pk=1, session_id=10)
        uow = self._uow(items=[item], available={})

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=None, tz=UTC
        )

        assert not violations

    def test_session_outside_the_offered_times_carries_foreign_attribution(self):
        item = agenda_item_dto(
            pk=1,
            session_id=10,
            session_title="Evening quiz",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        uow = self._uow(items=[item], available={10: [offered(2, DayPart.MORNING)]})
        uow.sessions.list_track_names_by_session.return_value = {10: {6: "Board games"}}
        uow.tracks.list_manager_names_by_tracks.return_value = {6: ["Basia"]}

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=5, tz=UTC
        )

        assert len(violations) == 1
        violation = violations[0]
        assert violation.session_pk == _SUBJECT_SESSION_PK
        assert violation.session_title == "Evening quiz"
        assert violation.scheduled_start == item.start_time
        assert violation.scheduled_end == item.end_time
        assert violation.availability == [offered(2, DayPart.MORNING)]
        assert violation.track_name == "Board games"
        assert violation.manager_names == ["Basia"]


class TestBuildHeatmap:
    @pytest.fixture
    def mock_uow(self):
        uow = MagicMock()
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.spaces.list_by_event.return_value = []
        uow.agenda_items.list_by_event.return_value = []
        return uow

    @pytest.mark.parametrize(
        ("event_end", "row_times"),
        (
            (datetime(2026, 1, 1, 11, 0, tzinfo=UTC), [10]),
            (datetime(2026, 1, 1, 11, 30, tzinfo=UTC), [10, 11]),
            (datetime(2026, 1, 1, 12, 30, tzinfo=UTC), [10, 11, 12]),
        ),
    )
    def test_build_heatmap_rounds_the_day_out_to_whole_hours(
        self, mock_uow, event_end, row_times
    ):
        mock_uow.spaces.list_by_event.return_value = [space_dto(3)]
        mock_uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC), event_end
        )
        mock_uow.agenda_items.list_by_event.return_value = [
            agenda_item_dto(
                space_id=3,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]

        result = TimetableOverviewService(mock_uow).build_heatmap(
            event_pk=1, tz=UTC, conflicts=[]
        )

        rows = [
            HeatmapRowDTO(
                time=datetime(2026, 1, 1, hour, 0, tzinfo=UTC),
                cells=[
                    HeatmapCellDTO(
                        space_pk=3,
                        status=(
                            HeatmapCellStatus.SCHEDULED
                            if hour == row_times[0]
                            else HeatmapCellStatus.EMPTY
                        ),
                    )
                ],
            )
            for hour in row_times
        ]
        assert result == HeatmapDTO(
            spaces=[space_dto(3)],
            rows=rows,
            days=[HeatmapDayDTO(date=date(2026, 1, 1), rows=rows)],
        )

    def test_build_heatmap_rounds_the_day_start_down_to_the_hour(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [space_dto(3)]
        mock_uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 30, 30, 500_000, tzinfo=UTC),
            datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        mock_uow.agenda_items.list_by_event.return_value = []

        result = TimetableOverviewService(mock_uow).build_heatmap(
            event_pk=1, tz=UTC, conflicts=[]
        )

        assert [row.time for row in result.rows] == [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        ]

    def test_build_heatmap_columns_are_leaf_spaces_only(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [
            space_dto(1),
            space_dto(2, parent_id=1),
            space_dto(3, parent_id=2),
            space_dto(4, parent_id=2),
        ]
        mock_uow.agenda_items.list_by_event.return_value = [agenda_item_dto(space_id=3)]
        svc = TimetableOverviewService(mock_uow)

        result = svc.build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [s.pk for s in result.spaces] == [3, 4]
        assert [c.space_pk for c in result.rows[0].cells] == [3, 4]
        assert [c.status for c in result.rows[0].cells] == [
            HeatmapCellStatus.SCHEDULED,
            HeatmapCellStatus.EMPTY,
        ]

    def test_build_heatmap_marks_both_ends_of_a_clash(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [space_dto(3), space_dto(4)]
        mock_uow.agenda_items.list_by_event.return_value = [
            agenda_item_dto(pk=1, session_id=10, space_id=3),
            agenda_item_dto(pk=2, session_id=20, space_id=4),
        ]
        conflict = ConflictDTO(
            type=ConflictType.FACILITATOR_OVERLAP,
            severity=ConflictSeverity.ERROR,
            subject_session_title="Mine",
            subject_session_pk=10,
            session_title="Theirs",
            session_pk=20,
        )

        result = TimetableOverviewService(mock_uow).build_heatmap(
            event_pk=1, tz=UTC, conflicts=[conflict]
        )

        assert [c.status for c in result.rows[0].cells] == [
            HeatmapCellStatus.CONFLICT,
            HeatmapCellStatus.CONFLICT,
        ]

    def test_all_conflicts_grouped_keeps_every_conflict_under_its_type(self):
        def conflict(kind, subject):
            return ConflictDTO(
                type=kind,
                severity=ConflictSeverity.ERROR,
                subject_session_title="Mine",
                subject_session_pk=subject,
                session_title="Theirs",
                session_pk=20,
            )

        first = conflict(ConflictType.FACILITATOR_OVERLAP, 10)
        second = conflict(ConflictType.FACILITATOR_OVERLAP, 11)
        other = conflict(ConflictType.SPACE_OVERLAP, 12)

        result = TimetableOverviewService(MagicMock()).all_conflicts_grouped(
            event_pk=1, conflicts=[first, other, second]
        )

        assert result == {
            ConflictType.FACILITATOR_OVERLAP: [first, second],
            ConflictType.SPACE_OVERLAP: [other],
        }


class TestTimetableOverviewCapacityHours:
    @staticmethod
    def _uow(*, spaces, event, items):
        uow = MagicMock()
        uow.spaces.list_by_event.return_value = spaces
        uow.events.read.return_value = event
        uow.agenda_items.list_by_event.return_value = items
        return uow

    @staticmethod
    def _event(open_hour, close_hour, *, days=1):
        # Every day of the event keeps the same opening hours, so the last day
        # closes at the same clock time the first one opened against.
        return event_stub(
            datetime(2026, 1, 1, open_hour, 0, tzinfo=UTC),
            datetime(2026, 1, days, close_hour, 0, tzinfo=UTC),
        )

    def test_hours_are_rounded_to_one_decimal(self):
        uow = self._uow(
            spaces=[space_dto(1), space_dto(2)],
            event=self._event(10, 11),
            items=[
                agenda_item_dto(
                    space_id=1,
                    start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 10, 10, tzinfo=UTC),
                )
            ],
        )

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=1.0,
            capacity_hours=2.0,
            scheduled_hours=0.2,
            hours_to_fill=1.8,
            filled_pct=8,
        )

    def test_an_event_with_no_rooms_has_no_capacity(self):
        uow = self._uow(spaces=[], event=self._event(10, 12), items=[])

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=0,
            slot_hours=2.0,
            capacity_hours=0.0,
            scheduled_hours=0.0,
            hours_to_fill=0.0,
            filled_pct=0,
        )

    def test_capacity_is_rooms_times_open_hours(self):
        uow = self._uow(
            spaces=[space_dto(1), space_dto(2)], event=self._event(10, 14), items=[]
        )

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=4.0,
            capacity_hours=8.0,
            scheduled_hours=0.0,
            hours_to_fill=8.0,
            filled_pct=0,
        )

    def test_every_day_of_the_event_counts_its_open_hours(self):
        uow = self._uow(
            spaces=[space_dto(1)], event=self._event(10, 12, days=2), items=[]
        )

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=4.0,
            capacity_hours=4.0,
            scheduled_hours=0.0,
            hours_to_fill=4.0,
            filled_pct=0,
        )

    def test_branch_spaces_are_not_bookable_rooms(self):
        spaces = [space_dto(1), space_dto(2, parent_id=1), space_dto(3, parent_id=1)]
        uow = self._uow(spaces=spaces, event=self._event(10, 12), items=[])

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=2.0,
            capacity_hours=4.0,
            scheduled_hours=0.0,
            hours_to_fill=4.0,
            filled_pct=0,
        )

    def test_a_double_booked_room_clamps_hours_to_fill_to_zero(self):
        items = [
            agenda_item_dto(
                pk=n,
                session_id=n,
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
            for n in (1, 2)
        ]
        uow = self._uow(spaces=[space_dto(1)], event=self._event(10, 11), items=items)

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=1.0,
            capacity_hours=1.0,
            scheduled_hours=2.0,
            hours_to_fill=0.0,
            filled_pct=200,
        )

    def test_an_odd_session_length_rounds_to_one_decimal(self):
        items = [
            agenda_item_dto(
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 20, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[space_dto(1)], event=self._event(10, 12), items=items)

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=2.0,
            capacity_hours=2.0,
            scheduled_hours=1.3,
            hours_to_fill=0.7,
            filled_pct=67,
        )
