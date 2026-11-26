from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ludamus.pacts.availability import DayPart
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.timetable import (
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    HeatmapCellStatus,
    PlacementRejectedError,
    PlacementRejection,
    ScheduleChangeAction,
    ScheduleChangeLogDTO,
    SessionPlacement,
    SpaceGroupDTO,
    TimetableGridFilter,
    TrackProgressDTO,
    UnscheduledSessionFilter,
)
from ludamus.pacts.tracks import TrackDTO, TrackSessionCountsDTO
from tests.unit.factories import agenda_item_dto, event_dto, session_dto, track_dto
from tests.unit.timetable_helpers import (
    START,
    FakeAgendaItems,
    conflict_service,
    facilitator_stub,
    lookup,
    offered,
    overview_service,
    space_dto,
    spec_uow,
    spheres_stub,
    stub_warning_reads,
    subset,
    timetable_service,
)


class _FakeScheduleChangeLogs:
    def __init__(self, *logs):
        self.rows = {log.pk: log for log in logs}
        self.created: list[dict] = []

    def create(self, data):
        self.created.append(data)
        return len(self.rows) + len(self.created)

    def read(self, pk):
        return self.rows[pk]

    def latest_pk_for_session(self, event_pk, session_id):
        return max(
            (
                log.pk
                for log in self.rows.values()
                if log.event_id == event_pk and log.session_id == session_id
            ),
            default=None,
        )


_END = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def _event(**overrides):
    return event_dto(
        **{
            "end_time": _END + timedelta(days=1),
            "name": "Con",
            "slug": "con",
            "sphere_id": 3,
            "start_time": START - timedelta(days=1),
            **overrides,
        }
    )


def _session(**overrides):
    return session_dto(
        **{"creation_time": START, "modification_time": START, **overrides}
    )


def _schedule_log(**overrides):
    defaults = {
        "pk": 1,
        "event_id": 1,
        "session_id": 1,
        "session_title": "Session",
        "user_id": None,
        "user_name": "",
        "action": ScheduleChangeAction.ASSIGN,
        "old_space_id": None,
        "old_space_name": None,
        "new_space_id": None,
        "new_space_name": None,
        "old_start_time": None,
        "old_end_time": None,
        "new_start_time": None,
        "new_end_time": None,
        "creation_time": START,
        "moved_from_id": None,
        "acknowledgement_time": None,
        "acknowledged_by_name": "",
        "important": False,
    }
    return ScheduleChangeLogDTO(**(defaults | overrides))


def _track(pk, name="Track"):
    return track_dto(
        creation_time=START,
        modification_time=START,
        name=name,
        pk=pk,
        slug=f"track-{pk}",
    )


class TestSpaceTree:
    @pytest.fixture
    def uow(self):
        uow = spec_uow(agenda_items=FakeAgendaItems())
        uow.spaces.list_by_event.side_effect = lookup(
            {
                1: [
                    space_dto(1),
                    space_dto(2, parent_id=1),
                    space_dto(3, parent_id=2),
                    space_dto(4, parent_id=2),
                    space_dto(5),
                ]
            }
        )
        uow.events.read.side_effect = lookup(
            {1: _event(start_time=START, end_time=_END)}
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
            {1: [space_dto(pk) for pk in range(1, 8)]}
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
        uow.events.read.return_value = event_dto(require_session_space=False)
        uow.agenda_items.rows = {1: agenda_item_dto(space_id=None)}

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [
            (
                column.space.pk if column.space else None,
                [pos.agenda_item.session_title for pos in column.sessions],
            )
            for column in grid.days[0].columns
        ] == [(3, []), (4, []), (5, []), (None, ["Session"])]
        assert grid.columns_per_day == len(grid.days[0].columns)
        assert grid.groups[-1].span == 1

    def test_a_session_placed_without_a_space_keeps_its_column_once_one_is_required(
        self, uow
    ):
        uow.agenda_items.rows = {1: agenda_item_dto(space_id=None)}

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert grid.days[0].columns[-1].space is None

    def test_a_room_filter_leaves_the_no_space_column_out(self, uow):
        uow.events.read.return_value = event_dto(require_session_space=False)

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


class TestAssignSessionRejections:
    @staticmethod
    def _placement(space_pk=1, start=START, end=_END):
        return SessionPlacement(space_pk=space_pk, start_time=start, end_time=end)

    @pytest.fixture
    def uow(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read.return_value = _session()
        uow.sessions.read_event.return_value = _event()
        uow.events.read.return_value = _event()
        uow.spaces.list_by_event.return_value = [space_dto(1)]
        return uow

    def test_a_space_outside_the_event_is_not_found(self, uow):
        with pytest.raises(NotFoundError):
            timetable_service(uow).assign_session(
                session_pk=1, placement=self._placement(space_pk=2), event_pk=1
            )

        assert uow.agenda_items.created == []

    def test_a_drop_before_publication_is_rejected(self, uow):
        published = _event(
            start_time=START + timedelta(days=1),
            publication_time=START + timedelta(hours=1),
        )
        uow.sessions.read_event.return_value = published
        uow.events.read.side_effect = lookup({1: published})

        with pytest.raises(PlacementRejectedError) as excinfo:
            timetable_service(uow).assign_session(
                session_pk=1, placement=self._placement(), event_pk=1
            )

        assert excinfo.value.reason is PlacementRejection.BEFORE_PUBLICATION
        assert str(excinfo.value) == (
            "start_time is before the event's publication_time; move the "
            "publication first (update_event)"
        )
        assert uow.agenda_items.created == []

    def test_an_accepted_drop_places_the_session_and_logs_it(self, uow):
        timetable_service(uow).assign_session(
            session_pk=1, placement=self._placement(), event_pk=1, user_pk=4
        )

        assert [item["session_id"] for item in uow.agenda_items.created] == [1]
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": 1,
                "new_start_time": START,
                "new_end_time": _END,
                "moved_from_id": None,
            }
        ]


class TestUnassignSession:
    def test_an_unscheduled_session_is_not_found(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read_event.return_value = _event()

        with pytest.raises(NotFoundError):
            timetable_service(uow).unassign_session(session_pk=1, event_pk=1)

        assert uow.schedule_change_logs.created == []


class TestRevertChangeOutcomes:
    @pytest.fixture
    def uow(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read.side_effect = lookup({1: _session()})
        uow.sessions.read_event.side_effect = lookup({1: _event()})
        return uow

    @staticmethod
    def _revert(uow, log_pk=1):
        timetable_service(uow).revert_change(log_pk=log_pk, event_pk=1, user_pk=4)

    def test_a_log_from_another_event_is_not_found(self, uow):
        uow.schedule_change_logs.rows = {1: _schedule_log(event_id=2)}

        with pytest.raises(NotFoundError):
            self._revert(uow)

    def test_only_the_latest_change_of_a_session_reverts(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(pk=1),
            2: _schedule_log(pk=2, action=ScheduleChangeAction.UNASSIGN),
        }

        with pytest.raises(
            ValueError, match=r"^Only the latest change for a session can be reverted$"
        ):
            self._revert(uow, log_pk=1)

        assert uow.schedule_change_logs.created == []

    def test_reverting_an_assign_takes_the_session_off_the_grid(self, uow):
        uow.agenda_items.rows = {7: agenda_item_dto(pk=7, session_id=1, space_id=3)}
        uow.schedule_change_logs.rows = {
            1: _schedule_log(new_space_id=3, new_start_time=START, new_end_time=_END)
        }

        self._revert(uow)

        uow.sessions.lock.assert_called_once_with(1)
        uow.sessions.update.assert_called_once_with(1, {"schedule_confirmed": False})
        assert uow.agenda_items.rows == {}
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.REVERT,
                "old_space_id": 3,
                "old_start_time": START,
                "old_end_time": _END,
            }
        ]

    def test_reverting_an_assign_of_an_already_removed_item_is_not_found(self, uow):
        uow.schedule_change_logs.rows = {1: _schedule_log()}

        with pytest.raises(NotFoundError):
            self._revert(uow)

        assert uow.schedule_change_logs.created == []

    def test_reverting_an_unassign_puts_the_session_back(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN,
                old_space_id=3,
                old_start_time=START,
                old_end_time=_END,
            )
        }

        self._revert(uow)

        uow.sessions.update.assert_called_once_with(1, {"schedule_confirmed": False})
        assert uow.agenda_items.created == [
            {
                "session_id": 1,
                "space_id": 3,
                "start_time": START,
                "end_time": _END,
                "session_confirmed": False,
            }
        ]
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.REVERT,
                "new_space_id": 3,
                "new_start_time": START,
                "new_end_time": _END,
            }
        ]

    @pytest.mark.parametrize("missing", ("old_start_time", "old_end_time"))
    def test_an_unassign_missing_any_part_of_its_placement_cannot_revert(
        self, uow, missing
    ):
        placement = {"old_space_id": 3, "old_start_time": START, "old_end_time": _END}
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN, **(placement | {missing: None})
            )
        }

        with pytest.raises(
            ValueError,
            match=r"^Cannot revert UNASSIGN: missing original placement data$",
        ):
            self._revert(uow)

        assert uow.agenda_items.created == []

    def test_an_unassign_without_a_space_cannot_revert_where_one_is_required(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN,
                old_space_id=None,
                old_start_time=START,
                old_end_time=_END,
            )
        }

        with pytest.raises(ValueError, match="its space no longer exists"):
            self._revert(uow)

        assert uow.agenda_items.created == []

    def test_an_unassign_without_a_space_reverts_where_none_is_required(self, uow):
        uow.spheres = spheres_stub(require_session_space=False)
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN,
                old_space_id=None,
                old_start_time=START,
                old_end_time=_END,
            )
        }

        self._revert(uow)

        assert [item["space_id"] for item in uow.agenda_items.created] == [None]

    def test_a_revert_row_itself_cannot_be_reverted(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(action=ScheduleChangeAction.REVERT)
        }

        with pytest.raises(ValueError, match="Cannot revert action"):
            self._revert(uow)

        assert uow.schedule_change_logs.created == []


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
        uow.spaces.list_by_event.return_value = [space_dto(1), space_dto(2)]
        stub_warning_reads(uow)
        uow.sessions.read_facilitators_by_sessions.side_effect = subset(
            {10: [shared], 20: [shared]}
        )
        uow.sessions.list_track_names_by_session.side_effect = subset(
            {20: {3: "Zeta", 5: "Alpha"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = subset({5: ["Ann"]})
        uow.tracks.read.side_effect = lookup({3: _track(3)})
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
            {3: TrackDTO(**(_track(3).model_dump() | {"event_id": 2}))}
        )

        with pytest.raises(NotFoundError):
            conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)


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
            end_time=_END + timedelta(hours=5),
        )
        elsewhere = agenda_item_dto(
            pk=4,
            session_id=40,
            session_title="Elsewhere",
            start_time=START + timedelta(hours=5),
            end_time=_END + timedelta(hours=5),
        )
        uow = spec_uow(agenda_items=FakeAgendaItems(free, inside, outside, elsewhere))
        uow.agenda_items.by_track = {3: [free, inside, outside]}
        stub_warning_reads(uow)
        morning = [offered(1, DayPart.MORNING)]
        uow.sessions.read_availability_by_sessions.side_effect = subset(
            {10: morning, 20: morning, 40: morning}
        )
        uow.tracks.read.side_effect = lookup({3: _track(3)})
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
        uow.tracks.read.side_effect = lookup({3: _track(3)})

        conflicts, violations = conflict_service(uow).list_grid_warnings(
            event_pk=1,
            track_pk=3,
            items=[mine, theirs],
            spaces=[space_dto(1), space_dto(2)],
            tz=UTC,
        )

        assert [
            (c.type, c.subject_session_pk, c.session_pk, c.track_name)
            for c in conflicts
        ] == [(ConflictType.FACILITATOR_OVERLAP, 10, 20, None)]
        assert [(v.session_pk, v.track_name) for v in violations] == [(10, None)]


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
        uow.spaces.list_by_event.side_effect = lookup({1: [space_dto(3)]})
        uow.events.read.side_effect = lookup(
            {1: _event(start_time=START, end_time=_END)}
        )
        stub_warning_reads(uow)
        return uow

    def test_heatmap_detects_conflicts_when_none_are_handed_in(self, uow):
        result = overview_service(uow).build_heatmap(event_pk=1, tz=UTC)

        assert [c.status for c in result.rows[0].cells] == [HeatmapCellStatus.CONFLICT]

    def test_heatmap_ignores_bookings_on_branch_spaces(self, uow):
        uow.spaces.list_by_event.side_effect = lookup(
            {1: [space_dto(1), space_dto(3, parent_id=1)]}
        )
        uow.agenda_items.rows = {1: agenda_item_dto(pk=1, session_id=10, space_id=1)}

        result = overview_service(uow).build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [c.status for c in result.rows[0].cells] == [HeatmapCellStatus.EMPTY]

    def test_heatmap_rounds_a_partial_last_hour_up(self, uow):
        uow.events.read.side_effect = lookup(
            {1: _event(start_time=START, end_time=_END + timedelta(minutes=30))}
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


class TestTrackProgress:
    def test_no_tracks_means_no_rows(self):
        uow = spec_uow()
        uow.tracks.list_by_event.return_value = []

        assert not overview_service(uow).track_progress(event_pk=1)

    def test_progress_is_measured_against_the_active_pool(self):
        uow = spec_uow()
        uow.tracks.list_by_event.side_effect = lookup(
            {1: [_track(1, "Busy"), _track(2, "Empty")]}
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
        uow.tracks.list_by_event.return_value = [_track(1, "RPG")]
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
