from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.pacts.availability import DayPart
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.timetable import (
    SpaceGroupDTO,
    TimetableGridFilter,
    UnscheduledSessionFilter,
)
from ludamus.pacts.venues import SpaceDTO
from tests.unit.factories import agenda_item_dto, event_dto, space_dto
from tests.unit.timetable_helpers import (
    END,
    START,
    FakeAgendaItems,
    con_event,
    event_stub,
    event_track,
    lookup,
    offered,
    spec_uow,
    stub_warning_reads,
    subset,
    timetable_service,
)


class TestBuildGridOverlappingSessions:
    def test_overlapping_items_are_placed_side_by_side(self):
        uow = MagicMock()
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]

        item_a = agenda_item_dto(
            pk=1,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        item_b = agenda_item_dto(
            pk=2,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        item_c = agenda_item_dto(
            pk=3,
            space_id=1,
            start_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [item_a, item_b, item_c]

        svc = timetable_service(uow)
        grid = svc.build_grid(event_pk=1, tz=UTC)

        sessions = grid.days[0].columns[0].sessions
        expected_count = 3
        expected_half_width = 50.0
        assert len(sessions) == expected_count
        assert sessions[0].lane_width_pct == pytest.approx(expected_half_width)
        assert sessions[1].lane_width_pct == pytest.approx(expected_half_width)
        assert sessions[0].lane_start_pct == pytest.approx(0.0)
        assert sessions[1].lane_start_pct == pytest.approx(expected_half_width)

    def test_a_chain_of_overlaps_shares_one_group(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(
                agenda_item_dto(
                    pk=1,
                    session_id=1,
                    start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                ),
                agenda_item_dto(
                    pk=2,
                    session_id=2,
                    start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
                ),
                agenda_item_dto(
                    pk=3,
                    session_id=3,
                    start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
            )
        )
        uow.spaces.list_by_event.side_effect = lookup({1: [space_dto(pk=1)]})
        uow.events.read.side_effect = lookup(
            {1: event_stub(START, START + timedelta(hours=2))}
        )
        stub_warning_reads(uow)

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        sessions = grid.days[0].columns[0].sessions
        assert [pos.lane_width_pct for pos in sessions] == pytest.approx([100 / 3] * 3)
        assert [pos.lane_start_pct for pos in sessions] == pytest.approx(
            [0, 100 / 3, 200 / 3]
        )

    def test_track_filter_still_shows_every_booking_in_the_visible_rooms(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.tracks.list_space_pks.side_effect = lookup({5: [1]})
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        mine = agenda_item_dto(
            pk=1,
            session_title="Mine",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        theirs = agenda_item_dto(
            pk=2,
            session_id=2,
            session_title="Theirs",
            start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        untracked = agenda_item_dto(
            pk=3,
            session_id=3,
            session_title="Untracked",
            start_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [mine, theirs, untracked]
        uow.agenda_items.list_by_track.return_value = [mine]
        uow.tracks.read.side_effect = lookup({5: event_track(event_pk=1)})
        stub_warning_reads(uow)
        uow.sessions.read_availability_by_sessions.side_effect = subset(
            {3: [offered(2, DayPart.MORNING)]}
        )

        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(track_pk=5)
        )

        sessions = grid.days[0].columns[0].sessions
        assert [(pos.agenda_item.session_title, pos.state) for pos in sessions] == [
            ("Mine", "conflict"),
            ("Theirs", "conflict"),
            ("Untracked", "normal"),
        ]
        assert [(c.subject_session_pk, c.session_pk) for c in grid.conflicts] == [
            (1, 2)
        ]

    def test_invalid_date_falls_back_to_the_first_event_day(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = []

        grid = timetable_service(uow).build_grid(
            event_pk=1,
            tz=UTC,
            filters=TimetableGridFilter(date_selection=date(2027, 1, 1)),
        )

        assert grid.date_selection == date(2026, 1, 1)
        assert [day.total_minutes for day in grid.days] == [2 * 60]

    def test_something_scheduled_overnight_adds_the_day_it_lands_on(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
        )
        night_owl = agenda_item_dto(
            start_time=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [night_owl]

        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(date_selection="all")
        )

        assert grid.available_dates == [date(2026, 1, 1), date(2026, 1, 2)]
        day_one, day_two = grid.days
        assert [day.total_minutes for day in grid.days] == [22 * 60, 22 * 60]
        assert day_one.time_labels[0].time.strftime("%H:%M") == "00:00"
        assert day_two.time_labels[0].time.strftime("%H:%M") == "00:00"
        assert day_one.columns[0].sessions == []
        assert [pos.start_minutes for pos in day_two.columns[0].sessions] == [0]

    def test_session_crossing_midnight_renders_clipped_on_both_days(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        # An event that opens in the small hours and runs late covers the whole
        # clock, so both halves of a midnight session have a row to sit on.
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 22, 0, tzinfo=UTC),
        )
        night_owl = agenda_item_dto(
            start_time=datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
            session_duration_minutes=4 * 60,
        )
        uow.agenda_items.list_by_event.return_value = [night_owl]

        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(date_selection="all")
        )

        day_one, day_two = grid.days
        # 22:00 -> 24:00 on one day and 00:00 -> 02:00 on the next share a
        # 00:00 -> 24:00 axis, so each fragment sits at its own clock hour.
        assert [day.total_minutes for day in grid.days] == [24 * 60, 24 * 60]
        friday, saturday = (
            day_one.columns[0].sessions[0],
            (day_two.columns[0].sessions[0]),
        )
        assert (friday.start_minutes, friday.duration_minutes) == (22 * 60, 2 * 60)
        assert (saturday.start_minutes, saturday.duration_minutes) == (0, 2 * 60)
        assert friday.agenda_item.session_duration_minutes == 4 * 60


class TestGridExtendedHours:
    @staticmethod
    def _uow(start, end):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        uow.spaces.list_by_event.return_value = [
            SpaceDTO(
                capacity=None,
                creation_time=now,
                modification_time=now,
                name="Room 1",
                order=0,
                pk=1,
                slug="room-1",
            )
        ]
        uow.events.read.return_value = event_stub(start, end)
        uow.agenda_items.list_by_event.return_value = []
        return uow

    def test_the_grid_reports_the_room_page_it_is_showing(self):
        uow = self._uow(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert (grid.first_space_number, grid.last_space_number) == (1, 1)
        assert (grid.extend_before_hours, grid.extend_after_hours) == (0, 0)
        assert grid.can_extend_before is True
        assert grid.can_extend_after is True

    def test_asking_for_extra_hours_widens_the_axis(self):
        uow = self._uow(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        grid = timetable_service(uow).build_grid(
            event_pk=1,
            tz=UTC,
            filters=TimetableGridFilter(extend_before_hours=2, extend_after_hours=1),
        )

        assert grid.days[0].total_minutes == 5 * 60
        assert grid.days[0].time_labels[0].time.strftime("%H:%M") == "08:00"
        assert (grid.extend_before_hours, grid.extend_after_hours) == (2, 1)

    def test_an_axis_already_at_the_edge_of_the_day_cannot_extend_further(self):
        uow = self._uow(
            datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
            datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        )

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert grid.can_extend_before is False
        assert grid.can_extend_after is False


class TestSpaceFilter:
    @staticmethod
    def _space(*, pk, name, parent_id=None):
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        return SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name=name,
            order=0,
            programme_order=pk,
            parent_id=parent_id,
            pk=pk,
            slug=f"space-{pk}",
        )

    @pytest.fixture
    def uow(self):
        uow = MagicMock()
        uow.spaces.list_by_event.return_value = [
            self._space(pk=1, name="Building A"),
            self._space(pk=2, name="Floor 2", parent_id=1),
            self._space(pk=3, name="Room 201", parent_id=2),
            self._space(pk=4, name="Room 202", parent_id=2),
            self._space(pk=5, name="Building B"),
            self._space(pk=6, name="Room 1", parent_id=5),
        ]
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = []
        return uow

    def test_grid_uses_programme_order_instead_of_tree_order(self, uow):
        by_pk = {space.pk: space for space in uow.spaces.list_by_event.return_value}
        by_pk[6].programme_order = 0
        by_pk[3].programme_order = 1
        by_pk[4].programme_order = 2

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [6, 3, 4]


class TestSpaceTree:
    @pytest.fixture
    def uow(self):
        uow = spec_uow(agenda_items=FakeAgendaItems())
        uow.spaces.list_by_event.side_effect = lookup(
            {
                1: [
                    space_dto(pk=1),
                    space_dto(pk=2, parent_id=1),
                    space_dto(pk=3, parent_id=2),
                    space_dto(pk=4, parent_id=2),
                    space_dto(pk=5),
                ]
            }
        )
        uow.events.read.side_effect = lookup(
            {1: con_event(start_time=START, end_time=END)}
        )
        stub_warning_reads(uow)
        return uow

    def test_filter_options_follow_the_tree_with_depths(self, uow):
        options = timetable_service(uow).space_filter_options(event_pk=1)

        assert [(o.value, o.depth) for o in options] == [
            (1, 0),
            (2, 1),
            (3, 2),
            (4, 2),
            (5, 0),
        ]

    def test_the_tree_is_read_once_per_service(self, uow):
        tree = uow.spaces.list_by_event(1)
        uow.spaces.list_by_event.side_effect = [tree, []]
        service = timetable_service(uow)

        service.space_filter_options(event_pk=1)
        grid = service.build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [3, 4, 5]

    def test_an_unfiltered_grid_reads_the_agenda_once(self, uow):
        timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert uow.agenda_items.reads == [(1, None)]

    def test_leaf_columns_group_under_their_parent(self, uow):
        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert grid.groups == [
            SpaceGroupDTO(parent_pk=2, parent_name="Room 2", span=2),
            SpaceGroupDTO(parent_pk=None, parent_name="", span=1),
        ]
        assert (grid.page, grid.total_pages, grid.total_spaces) == (1, 1, 3)

    def test_rooms_are_paged_five_at_a_time_from_the_first(self, uow):
        uow.spaces.list_by_event.side_effect = lookup(
            {1: [space_dto(pk=pk) for pk in range(1, 8)]}
        )
        service = timetable_service(uow)

        first = service.build_grid(event_pk=1, tz=UTC)
        second = service.build_grid(event_pk=1, tz=UTC, space_page=2)

        assert [
            (
                grid.page,
                grid.total_pages,
                grid.total_spaces,
                grid.first_space_number,
                grid.last_space_number,
                [space.pk for space in grid.spaces],
            )
            for grid in (first, second)
        ] == [(1, 2, 7, 1, 5, [1, 2, 3, 4, 5]), (2, 2, 7, 6, 7, [6, 7])]

    def test_an_event_needing_no_space_adds_a_column_for_sessions_without_one(
        self, uow
    ):
        uow.events.read.side_effect = lookup(
            {1: con_event(require_session_space=False)}
        )

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [
            column.space.pk if column.space else None for column in grid.days[0].columns
        ] == [3, 4, 5, None]
        assert grid.columns_per_day == len(grid.days[0].columns)
        assert grid.groups[-1].span == 1

    def test_a_session_placed_without_a_space_keeps_its_column_once_one_is_required(
        self, uow
    ):
        uow.agenda_items.rows = {1: agenda_item_dto(space_id=None)}

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        column = grid.days[0].columns[-1]
        assert column.space is None
        assert [pos.agenda_item.session_title for pos in column.sessions] == ["Session"]

    def test_a_room_filter_leaves_the_no_space_column_out(self, uow):
        uow.events.read.side_effect = lookup(
            {1: con_event(require_session_space=False)}
        )

        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(space_pks={2})
        )

        assert None not in [column.space for column in grid.days[0].columns]

    def test_a_booking_renders_in_its_rooms_column(self, uow):
        uow.agenda_items.rows = {1: agenda_item_dto(space_id=4)}

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [
            [pos.agenda_item.session_title for pos in column.sessions]
            for column in grid.days[0].columns
        ] == [[], ["Session"], []]

    def test_the_facilitator_filter_narrows_the_shown_sessions(self, uow):
        uow.agenda_items.rows = {
            1: agenda_item_dto(pk=1, session_id=1, space_id=3, session_title="Mine"),
            2: agenda_item_dto(pk=2, session_id=2, space_id=4, session_title="Theirs"),
        }
        uow.agenda_items.facilitators_by_session = {1: {7}, 2: {8}}

        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(facilitator_pks={7})
        )

        assert [
            [pos.agenda_item.session_title for pos in column.sessions]
            for column in grid.days[0].columns
        ] == [["Mine"], [], []]

    def test_selecting_a_branch_keeps_every_leaf_beneath_it(self, uow):
        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(space_pks={2})
        )

        assert [space.pk for space in grid.spaces] == [3, 4]

    def test_a_foreign_space_pk_narrows_to_nothing(self, uow):
        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(space_pks={99})
        )

        assert grid.spaces == []
        assert grid.total_pages == 1


class TestTimetablePanelReads:
    def test_categories_come_from_the_event(self):
        # NOTE: a hand-off to the repository; the stub answers only for the
        # event asked about, so a dropped or swapped id fails here.
        categories = SimpleNamespace(list_by_event={1: ["RPG"]}.__getitem__)

        service = timetable_service(spec_uow(), categories=categories)

        assert service.list_categories(1) == ["RPG"]

    def test_unscheduled_sessions_report_whether_more_wait(self):
        uow = spec_uow()
        uow.sessions.list_unscheduled_by_event.return_value = (["session"], True)
        filters = UnscheduledSessionFilter(search="dragons")

        result = timetable_service(uow).list_unscheduled(event_pk=1, filters=filters)

        assert (result.sessions, result.has_more) == (["session"], True)
        uow.sessions.list_unscheduled_by_event.assert_called_once_with(1, filters)

    def test_a_session_of_another_event_has_no_detail(self):
        uow = spec_uow()
        uow.sessions.read_event.return_value = event_dto(pk=2)

        with pytest.raises(NotFoundError):
            timetable_service(uow).session_detail(event_pk=1, session_pk=5)

        uow.sessions.read.assert_not_called()

    def test_a_session_detail_carries_its_placement_and_people(self):
        uow = spec_uow()
        uow.sessions.read_event.return_value = event_dto(pk=1)

        detail = timetable_service(uow).session_detail(event_pk=1, session_pk=5)

        assert detail.session is uow.sessions.read.return_value
        assert detail.agenda_item is uow.agenda_items.read_by_session.return_value
        assert detail.facilitators is uow.sessions.read_facilitators.return_value
        assert detail.availability is uow.sessions.read_availability.return_value

    def test_only_each_sessions_newest_change_is_revertible(self):
        uow = spec_uow()
        uow.schedule_change_logs.latest_pks_by_session.return_value = {5: 30, 6: 31}

        log = timetable_service(uow).change_log(event_pk=1, space_pk=4)

        assert log.revertible_pks == {30, 31}
        uow.schedule_change_logs.list_by_event.assert_called_once_with(1, space_pk=4)
