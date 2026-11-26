from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.timetable import TimetableOverviewService
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
    TrackProgressDTO,
)
from ludamus.pacts.tracks import TrackSessionCountsDTO
from tests.unit.factories import agenda_item_dto, space_dto
from tests.unit.timetable_helpers import (
    END,
    START,
    FakeAgendaItems,
    con_event,
    event_stub,
    lookup,
    numbered_track,
    overview_service,
    spec_uow,
    stub_warning_reads,
    subset,
)


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
        mock_uow.spaces.list_by_event.return_value = [space_dto(pk=3)]
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
            spaces=[space_dto(pk=3)],
            rows=rows,
            days=[HeatmapDayDTO(date=date(2026, 1, 1), rows=rows)],
        )

    def test_build_heatmap_rounds_the_day_start_down_to_the_hour(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [space_dto(pk=3)]
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
            space_dto(pk=1),
            space_dto(pk=2, parent_id=1),
            space_dto(pk=3, parent_id=2),
            space_dto(pk=4, parent_id=2),
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
        mock_uow.spaces.list_by_event.return_value = [space_dto(pk=3), space_dto(pk=4)]
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


class TestOverviewConflicts:
    @pytest.fixture
    def uow(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(
                agenda_item_dto(pk=1, session_id=10, space_id=3, session_title="Mine"),
                agenda_item_dto(
                    pk=2, session_id=20, space_id=3, session_title="Theirs"
                ),
            )
        )
        uow.spaces.list_by_event.side_effect = lookup({1: [space_dto(pk=3)]})
        uow.events.read.side_effect = lookup(
            {1: con_event(start_time=START, end_time=END)}
        )
        stub_warning_reads(uow)
        return uow

    def test_heatmap_detects_conflicts_when_none_are_handed_in(self, uow):
        result = overview_service(uow).build_heatmap(event_pk=1, tz=UTC)

        assert [c.status for c in result.rows[0].cells] == [HeatmapCellStatus.CONFLICT]

    def test_heatmap_ignores_bookings_on_branch_spaces(self, uow):
        uow.spaces.list_by_event.side_effect = lookup(
            {1: [space_dto(pk=1), space_dto(pk=3, parent_id=1)]}
        )
        uow.agenda_items.rows = {1: agenda_item_dto(pk=1, session_id=10, space_id=1)}

        result = overview_service(uow).build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [c.status for c in result.rows[0].cells] == [HeatmapCellStatus.EMPTY]

    def test_heatmap_rounds_a_partial_last_hour_up(self, uow):
        uow.events.read.side_effect = lookup(
            {1: con_event(start_time=START, end_time=END + timedelta(minutes=30))}
        )

        result = overview_service(uow).build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [row.time.strftime("%H:%M") for row in result.rows] == ["10:00", "11:00"]

    def test_grouping_detects_conflicts_when_none_are_handed_in(self, uow):
        grouped = overview_service(uow).all_conflicts_grouped(event_pk=1)

        assert list(grouped) == [ConflictType.SPACE_OVERLAP]
        assert [c.session_pk for c in grouped[ConflictType.SPACE_OVERLAP]] == [20]

    def test_grouping_keeps_each_type_together(self, uow):
        def conflict(kind, pk):
            return ConflictDTO(
                type=kind,
                severity=ConflictSeverity.ERROR,
                subject_session_title="",
                subject_session_pk=1,
                session_title="",
                session_pk=pk,
            )

        conflicts = [
            conflict(ConflictType.SPACE_OVERLAP, 2),
            conflict(ConflictType.FACILITATOR_OVERLAP, 3),
            conflict(ConflictType.SPACE_OVERLAP, 4),
        ]

        grouped = overview_service(uow).all_conflicts_grouped(
            event_pk=1, conflicts=conflicts
        )

        assert {k: [c.session_pk for c in v] for k, v in grouped.items()} == {
            ConflictType.SPACE_OVERLAP: [2, 4],
            ConflictType.FACILITATOR_OVERLAP: [3],
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
    def _event(*, open_hour, close_hour, days=1):
        # Every day of the event keeps the same opening hours, so the last day
        # closes at the same clock time the first one opened against.
        return event_stub(
            datetime(2026, 1, 1, open_hour, 0, tzinfo=UTC),
            datetime(2026, 1, days, close_hour, 0, tzinfo=UTC),
        )

    def test_hours_are_rounded_to_one_decimal(self):
        uow = self._uow(
            spaces=[space_dto(pk=1), space_dto(pk=2)],
            event=self._event(open_hour=10, close_hour=11),
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
        uow = self._uow(
            spaces=[], event=self._event(open_hour=10, close_hour=12), items=[]
        )

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
            spaces=[space_dto(pk=1), space_dto(pk=2)],
            event=self._event(open_hour=10, close_hour=14),
            items=[],
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
            spaces=[space_dto(pk=1)],
            event=self._event(open_hour=10, close_hour=12, days=2),
            items=[],
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
        spaces = [
            space_dto(pk=1),
            space_dto(pk=2, parent_id=1),
            space_dto(pk=3, parent_id=1),
        ]
        uow = self._uow(
            spaces=spaces, event=self._event(open_hour=10, close_hour=12), items=[]
        )

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
        uow = self._uow(
            spaces=[space_dto(pk=1)],
            event=self._event(open_hour=10, close_hour=11),
            items=items,
        )

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
        uow = self._uow(
            spaces=[space_dto(pk=1)],
            event=self._event(open_hour=10, close_hour=12),
            items=items,
        )

        result = overview_service(uow).capacity_hours(event_pk=1, tz=UTC)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=2.0,
            capacity_hours=2.0,
            scheduled_hours=1.3,
            hours_to_fill=0.7,
            filled_pct=67,
        )


class TestTrackProgress:
    def test_no_tracks_means_no_rows(self):
        uow = spec_uow()
        uow.tracks.list_by_event.return_value = []

        assert not overview_service(uow).track_progress(event_pk=1)

    def test_progress_is_measured_against_the_active_pool(self):
        uow = spec_uow()
        uow.tracks.list_by_event.side_effect = lookup(
            {1: [numbered_track(1, "Busy"), numbered_track(2, "Empty")]}
        )
        uow.sessions.count_by_track.side_effect = lookup(
            {
                1: {
                    1: TrackSessionCountsDTO(
                        pending=1, accepted=3, scheduled=2, on_hold=1, rejected=5
                    )
                }
            }
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = subset({1: ["Ann"]})

        assert overview_service(uow).track_progress(event_pk=1) == [
            TrackProgressDTO(
                track_pk=1,
                track_name="Busy",
                manager_names=["Ann"],
                accepted_count=3,
                scheduled_count=2,
                pending_count=1,
                on_hold_count=1,
                rejected_count=5,
                progress_pct=50,
            ),
            TrackProgressDTO(
                track_pk=2,
                track_name="Empty",
                manager_names=[],
                accepted_count=0,
                scheduled_count=0,
                progress_pct=0,
            ),
        ]

    def test_on_hold_sessions_are_reported_but_not_counted_as_active(self):
        uow = spec_uow()
        uow.tracks.list_by_event.return_value = [numbered_track(1, "RPG")]
        uow.sessions.count_by_track.return_value = {
            1: TrackSessionCountsDTO(pending=1, accepted=2, scheduled=1, on_hold=5)
        }
        uow.tracks.list_manager_names_by_tracks.return_value = {}

        assert overview_service(uow).track_progress(event_pk=1) == [
            TrackProgressDTO(
                track_pk=1,
                track_name="RPG",
                manager_names=[],
                accepted_count=2,
                scheduled_count=1,
                pending_count=1,
                on_hold_count=5,
                rejected_count=0,
                progress_pct=33,
            )
        ]
