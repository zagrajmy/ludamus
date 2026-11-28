from datetime import UTC, date, datetime, timedelta
from itertools import starmap
from unittest.mock import MagicMock

import pytest

from ludamus.mills.timetable import ConflictDetectionService
from ludamus.pacts.availability import AvailabilityDTO, DayPart
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import TimeSlotDTO
from ludamus.pacts.timetable import ConflictType, RoomBookingConflict
from ludamus.pacts.tracks import TrackDTO
from ludamus.pacts.venues import SpaceDTO
from tests.unit.factories import agenda_item_dto, space_dto
from tests.unit.timetable_helpers import (
    END,
    START,
    FakeAgendaItems,
    conflict_service,
    event_track,
    facilitator_stub,
    lookup,
    numbered_track,
    offered,
    spec_uow,
    stub_warning_reads,
    subset,
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
        uow = self._uow(all_items=[first, second], spaces=[space_dto(pk=1, capacity=2)])

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
        assert conflicts[0].type is RoomBookingConflict.KIND
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
            all_items=[item], spaces=[space_dto(pk=1, capacity=_SESSION_LIMIT)]
        )

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_a_session_without_a_limit_fits_a_room_of_no_capacity(self):
        item = agenda_item_dto(pk=1, session_id=10, space_id=1)
        uow = self._uow(all_items=[item], spaces=[space_dto(pk=1, capacity=0)])

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


class TestTrackAttribution:
    @pytest.fixture
    def uow(self):
        shared = facilitator_stub(7, display_name="Alice")
        uow = spec_uow(
            agenda_items=FakeAgendaItems(
                agenda_item_dto(pk=1, session_id=10, space_id=1, session_title="Mine"),
                agenda_item_dto(
                    pk=2, session_id=20, space_id=2, session_title="Theirs"
                ),
            )
        )
        uow.agenda_items.by_track = {3: [uow.agenda_items.rows[1]]}
        uow.spaces.list_by_event.return_value = [space_dto(pk=1), space_dto(pk=2)]
        stub_warning_reads(uow)
        uow.sessions.read_facilitators_by_sessions.side_effect = subset(
            {10: [shared], 20: [shared]}
        )
        uow.sessions.list_track_names_by_session.side_effect = subset(
            {20: {3: "Zeta", 5: "Alpha"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = subset({5: ["Ann"]})
        uow.tracks.read.side_effect = lookup({3: numbered_track(3)})
        return uow

    def test_a_facilitator_clash_names_the_other_sessions_track(self, uow):
        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [
            (c.type, c.facilitator_name, c.track_name, c.manager_names)
            for c in conflicts
        ] == [(ConflictType.FACILITATOR_OVERLAP, "Alice", "Alpha", ["Ann"])]

    def test_a_foreign_track_without_managers_is_still_named(self, uow):
        uow.tracks.list_manager_names_by_tracks.side_effect = subset({})

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [(c.track_name, c.manager_names) for c in conflicts] == [("Alpha", [])]

    def test_only_facilitator_clashes_are_attributed(self, uow):
        uow.agenda_items.rows[2] = agenda_item_dto(
            pk=2, session_id=20, space_id=1, session_title="Theirs"
        )

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [(c.type, c.track_name) for c in conflicts] == [
            (ConflictType.SPACE_OVERLAP, None),
            (ConflictType.FACILITATOR_OVERLAP, "Alpha"),
        ]

    def test_the_current_track_is_never_named_as_foreign(self, uow):
        uow.sessions.list_track_names_by_session.side_effect = subset(
            {20: {3: "Alpha"}}
        )

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)

        assert [(c.track_name, c.manager_names) for c in conflicts] == [(None, [])]

    def test_a_track_listing_only_reports_its_own_sessions_clashes(self, uow):
        uow.agenda_items.rows[3] = agenda_item_dto(pk=3, session_id=30, space_id=9)
        uow.agenda_items.rows[4] = agenda_item_dto(pk=4, session_id=40, space_id=9)

        conflicts = conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)

        assert [(c.subject_session_pk, c.session_pk) for c in conflicts] == [(10, 20)]

    def test_a_foreign_track_is_not_found(self, uow):
        uow.tracks.read.side_effect = lookup(
            {3: TrackDTO(**(numbered_track(3).model_dump() | {"event_id": 2}))}
        )

        with pytest.raises(NotFoundError):
            conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)


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


class TestOfferedTimeViolations:
    @pytest.fixture
    def uow(self):
        free = agenda_item_dto(pk=1, session_id=30, session_title="Free")
        inside = agenda_item_dto(pk=2, session_id=10, session_title="Inside")
        outside = agenda_item_dto(
            pk=3,
            session_id=20,
            session_title="Outside",
            start_time=START + timedelta(hours=5),
            end_time=END + timedelta(hours=5),
        )
        elsewhere = agenda_item_dto(
            pk=4,
            session_id=40,
            session_title="Elsewhere",
            start_time=START + timedelta(hours=5),
            end_time=END + timedelta(hours=5),
        )
        uow = spec_uow(agenda_items=FakeAgendaItems(free, inside, outside, elsewhere))
        uow.agenda_items.by_track = {3: [free, inside, outside]}
        stub_warning_reads(uow)
        morning = [offered(1, DayPart.MORNING)]
        uow.sessions.read_availability_by_sessions.side_effect = subset(
            {10: morning, 20: morning, 40: morning}
        )
        uow.tracks.read.side_effect = lookup({3: numbered_track(3)})
        return uow

    @pytest.mark.parametrize(
        ("track_pk", "titles"), ((None, ["Outside", "Elsewhere"]), (3, ["Outside"]))
    )
    def test_only_sessions_outside_their_picks_are_reported(
        self, uow, track_pk, titles
    ):
        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=track_pk, tz=UTC
        )

        assert [(v.session_title, v.track_name) for v in violations] == [
            (title, None) for title in titles
        ]

    def test_a_violation_names_the_sessions_foreign_track(self, uow):
        uow.sessions.list_track_names_by_session.side_effect = subset(
            {20: {3: "Alpha", 5: "Beta"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = subset({5: ["Bob"]})

        violations = conflict_service(uow).list_offered_time_violations(
            event_pk=1, track_pk=3, tz=UTC
        )

        assert [(v.session_pk, v.track_name, v.manager_names) for v in violations] == [
            (20, "Beta", ["Bob"])
        ]


class TestListGridWarnings:
    def test_warnings_are_about_the_tracks_sessions_and_name_foreign_tracks(self):
        shared = facilitator_stub(7)
        mine = agenda_item_dto(pk=1, session_id=10, space_id=1, session_title="Mine")
        theirs = agenda_item_dto(
            pk=2, session_id=20, space_id=2, session_title="Theirs"
        )
        uow = spec_uow(agenda_items=FakeAgendaItems(mine, theirs))
        uow.agenda_items.by_track = {3: [mine]}
        stub_warning_reads(uow)
        uow.sessions.read_facilitators_by_sessions.side_effect = subset(
            {10: [shared], 20: [shared]}
        )
        next_day = [offered(2, DayPart.MORNING)]
        uow.sessions.read_availability_by_sessions.side_effect = subset(
            {10: next_day, 20: next_day}
        )
        uow.sessions.list_track_names_by_session.side_effect = subset(
            {10: {3: "Alpha"}, 20: {3: "Alpha"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = subset({3: ["Ann"]})
        uow.tracks.read.side_effect = lookup({3: numbered_track(3)})

        conflicts, violations = conflict_service(uow).list_grid_warnings(
            event_pk=1,
            track_pk=3,
            items=[mine, theirs],
            spaces=[space_dto(pk=1), space_dto(pk=2)],
            tz=UTC,
        )

        assert [
            (c.type, c.subject_session_pk, c.session_pk, c.track_name)
            for c in conflicts
        ] == [(ConflictType.FACILITATOR_OVERLAP, 10, 20, None)]
        assert [(v.session_pk, v.track_name) for v in violations] == [(10, None)]
