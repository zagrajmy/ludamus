import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts import (
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    SessionStatus,
)
from ludamus.pacts.chronology import (
    TIMETABLE_ROOM_PAGE_SIZE,
    TIMETABLE_SLOT_MINUTES,
    TIMETABLE_SNAP_MINUTES,
    DateSelection,
    SessionPlacement,
    SessionPositionDTO,
    SpaceColumnDTO,
    SpaceGroupDTO,
    TimeLabelDTO,
    TimetableDayGridDTO,
    TimetableGridDTO,
)

if TYPE_CHECKING:
    from ludamus.pacts import AgendaItemDTO, SpaceDTO, UnitOfWorkProtocol


def _position_sessions(
    items: list[AgendaItemDTO], event_start: datetime
) -> list[SessionPositionDTO]:
    if not items:
        return []

    groups: list[list[AgendaItemDTO]] = []
    current_group: list[AgendaItemDTO] = []
    group_end: datetime | None = None

    for item in items:
        if group_end is None or item.start_time >= group_end:
            if current_group:
                groups.append(current_group)
            current_group = [item]
            group_end = item.end_time
        else:
            current_group.append(item)
            group_end = max(group_end, item.end_time)
    groups.append(current_group)

    positions: list[SessionPositionDTO] = []
    for group in groups:
        lane_width_pct = 100.0 / len(group)
        for index, item in enumerate(group):
            offset_min = (item.start_time - event_start).total_seconds() / 60
            duration_min = (item.end_time - item.start_time).total_seconds() / 60
            positions.append(
                SessionPositionDTO(
                    agenda_item=item,
                    start_minutes=round(offset_min),
                    duration_minutes=round(duration_min),
                    lane_start_pct=index * lane_width_pct,
                    lane_width_pct=lane_width_pct,
                )
            )

    return positions


class TimetableService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def build_grid(
        self,
        *,
        event_pk: int,
        tz: tzinfo,
        track_pk: int | None = None,
        space_page: int = 1,
        date_selection: DateSelection = "all",
    ) -> TimetableGridDTO:
        all_nodes = self._uow.spaces.list_by_event(event_pk)
        node_name_by_pk = {node.pk: node.name for node in all_nodes}
        leaf_spaces = self._leaves_in_tree_order(all_nodes)
        if track_pk is not None:
            track_space_pks = set(self._uow.tracks.list_space_pks(track_pk))
            leaf_spaces = [
                space for space in leaf_spaces if space.pk in track_space_pks
            ]

        total_spaces = len(leaf_spaces)
        total_pages = max(1, math.ceil(total_spaces / TIMETABLE_ROOM_PAGE_SIZE))
        space_page = max(1, min(space_page, total_pages))
        start = (space_page - 1) * TIMETABLE_ROOM_PAGE_SIZE
        spaces = leaf_spaces[start : start + TIMETABLE_ROOM_PAGE_SIZE]

        all_slots = self._uow.time_slots.list_by_event(event_pk)
        windows_by_date = slot_windows_by_local_date(all_slots, tz)
        available_dates = sorted(windows_by_date)
        if date_selection != "all" and date_selection not in windows_by_date:
            date_selection = available_dates[0] if available_dates else "all"

        groups = self._build_space_groups(spaces, node_name_by_pk)
        dates_to_render = (
            available_dates if date_selection == "all" else [date_selection]
        )
        all_items = (
            self._uow.agenda_items.list_by_track(track_pk)
            if track_pk is not None
            else self._uow.agenda_items.list_by_event(event_pk)
        )
        grid_start_minute, grid_end_minute = self._grid_minute_bounds(
            dates_to_render, windows_by_date
        )
        total_minutes = grid_end_minute - grid_start_minute
        days = [
            self._build_day_grid(
                date_to_render=date_to_render,
                day_windows=windows_by_date[date_to_render],
                spaces=spaces,
                all_items=all_items,
                grid_minute_bounds=(grid_start_minute, grid_end_minute),
            )
            for date_to_render in dates_to_render
        ]
        time_labels: list[TimeLabelDTO] = []
        if dates_to_render:
            first_date = dates_to_render[0]
            first_window_start = windows_by_date[first_date][0][0]
            first_midnight = datetime.combine(
                first_date, datetime.min.time(), tzinfo=first_window_start.tzinfo
            )
            label_start = first_midnight + timedelta(minutes=grid_start_minute)
            slot_delta = timedelta(minutes=TIMETABLE_SLOT_MINUTES)
            time_labels = [
                TimeLabelDTO(
                    time=label_start + slot_delta * index,
                    offset_minutes=index * TIMETABLE_SLOT_MINUTES,
                )
                for index in range(total_minutes // TIMETABLE_SLOT_MINUTES + 1)
            ]

        return TimetableGridDTO(
            spaces=spaces,
            groups=groups,
            days=days,
            time_labels=time_labels,
            total_minutes=total_minutes,
            slot_minutes=TIMETABLE_SLOT_MINUTES,
            snap_minutes=TIMETABLE_SNAP_MINUTES,
            page=space_page,
            total_pages=total_pages,
            total_spaces=total_spaces,
            available_dates=available_dates,
            date_selection=date_selection,
        )

    @staticmethod
    def _build_day_grid(
        *,
        date_to_render: date,
        day_windows: list[tuple[datetime, datetime]],
        spaces: list[SpaceDTO],
        all_items: list[AgendaItemDTO],
        grid_minute_bounds: tuple[int, int],
    ) -> TimetableDayGridDTO:
        grid_start_minute, grid_end_minute = grid_minute_bounds
        day_midnight = datetime.combine(
            date_to_render, datetime.min.time(), tzinfo=day_windows[0][0].tzinfo
        )
        grid_start = day_midnight + timedelta(minutes=grid_start_minute)
        grid_end = day_midnight + timedelta(minutes=grid_end_minute)

        space_pk_set = {space.pk for space in spaces}
        space_items: dict[int, list[AgendaItemDTO]] = defaultdict(list)
        for item in all_items:
            if (
                item.space_id in space_pk_set
                and item.start_time < grid_end
                and item.end_time > grid_start
            ):
                space_items[item.space_id].append(item)

        columns: list[SpaceColumnDTO] = []
        for space in spaces:
            items_for_space = space_items.get(space.pk, [])
            items_for_space.sort(key=lambda item: item.start_time)
            columns.append(
                SpaceColumnDTO(
                    space=space,
                    sessions=_position_sessions(
                        items_for_space, event_start=grid_start
                    ),
                )
            )

        return TimetableDayGridDTO(
            date=date_to_render, columns=columns, event_start_iso=grid_start.isoformat()
        )

    @staticmethod
    def _grid_minute_bounds(
        dates_to_render: list[date],
        windows_by_date: dict[date, list[tuple[datetime, datetime]]],
    ) -> tuple[int, int]:
        if not dates_to_render:
            return 0, 0

        start_minutes: list[int] = []
        end_minutes: list[int] = []
        for day in dates_to_render:
            for window_start, window_end in windows_by_date[day]:
                start_minutes.append(window_start.hour * 60 + window_start.minute)
                if window_end.date() > day:
                    end_minutes.append(24 * 60)
                else:
                    end_minutes.append(
                        math.ceil(
                            (
                                window_end.hour * 60
                                + window_end.minute
                                + window_end.second / 60
                            )
                            / TIMETABLE_SLOT_MINUTES
                        )
                        * TIMETABLE_SLOT_MINUTES
                    )

        return (
            min(start_minutes) // TIMETABLE_SLOT_MINUTES * TIMETABLE_SLOT_MINUTES,
            max(end_minutes),
        )

    @staticmethod
    def _leaves_in_tree_order(nodes: list[SpaceDTO]) -> list[SpaceDTO]:
        children: dict[int | None, list[SpaceDTO]] = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node)

        leaves: list[SpaceDTO] = []

        def walk(node: SpaceDTO) -> None:
            if kids := children.get(node.pk, []):
                for kid in kids:
                    walk(kid)
            else:
                leaves.append(node)

        for root in children.get(None, []):
            walk(root)
        return leaves

    @staticmethod
    def _build_space_groups(
        spaces: list[SpaceDTO], name_by_pk: dict[int, str]
    ) -> list[SpaceGroupDTO]:
        groups: list[SpaceGroupDTO] = []
        for space in spaces:
            parent_pk = space.parent_id
            if not groups or groups[-1].parent_pk != parent_pk:
                groups.append(
                    SpaceGroupDTO(
                        parent_pk=parent_pk,
                        parent_name=name_by_pk.get(parent_pk, "") if parent_pk else "",
                        span=0,
                    )
                )
            groups[-1].span += 1
        return groups

    def _require_session_in_event(self, session_pk: int, event_pk: int) -> None:
        if self._uow.sessions.read_event(session_pk).pk != event_pk:
            raise NotFoundError

    def _require_space_in_event(self, space_pk: int, event_pk: int) -> None:
        leaf_pks = {
            space.pk
            for space in self._leaves_in_tree_order(
                self._uow.spaces.list_by_event(event_pk)
            )
        }
        if space_pk not in leaf_pks:
            raise NotFoundError

    def assign_session(
        self,
        *,
        session_pk: int,
        placement: SessionPlacement,
        event_pk: int,
        user_pk: int | None = None,
    ) -> None:
        with self._uow.atomic():
            self._require_session_in_event(session_pk, event_pk)
            self._require_space_in_event(placement.space_pk, event_pk)
            self._uow.spaces.lock(placement.space_pk)
            is_move = self._uow.agenda_items.read_by_session(session_pk) is not None
            if is_move:
                self.unassign_session(
                    session_pk=session_pk, event_pk=event_pk, user_pk=user_pk
                )
            session = self._uow.sessions.read(session_pk)
            if session.status != SessionStatus.ACCEPTED:
                msg = f"Session {session_pk} is not in ACCEPTED status"
                raise ValueError(msg)
            event = self._uow.sessions.read_event(session_pk)
            self._uow.agenda_items.create(
                {
                    "session_id": session_pk,
                    "space_id": placement.space_pk,
                    "start_time": placement.start_time,
                    "end_time": placement.end_time,
                    "session_confirmed": event.auto_confirm_sessions and not is_move,
                }
            )
            log_data: ScheduleChangeLogData = {
                "event_id": event.pk,
                "session_id": session_pk,
                "user_id": user_pk,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": placement.space_pk,
                "new_start_time": placement.start_time,
                "new_end_time": placement.end_time,
            }
            self._uow.schedule_change_logs.create(log_data)

    def unassign_session(
        self, *, session_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None:
        self._require_session_in_event(session_pk, event_pk)
        if (agenda_item := self._uow.agenda_items.read_by_session(session_pk)) is None:
            raise NotFoundError
        event = self._uow.sessions.read_event(session_pk)
        self._uow.agenda_items.delete(agenda_item.pk)
        log_data: ScheduleChangeLogData = {
            "event_id": event.pk,
            "session_id": session_pk,
            "user_id": user_pk,
            "action": ScheduleChangeAction.UNASSIGN,
            "old_space_id": agenda_item.space_id,
            "old_start_time": agenda_item.start_time,
            "old_end_time": agenda_item.end_time,
        }
        self._uow.schedule_change_logs.create(log_data)

    def revert_change(
        self, *, log_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None:
        log = self._uow.schedule_change_logs.read(log_pk)
        if log.event_id != event_pk:
            raise NotFoundError
        with self._uow.atomic():
            self._uow.sessions.lock(log.session_id)
            latest_pk = self._uow.schedule_change_logs.latest_pk_for_session(
                event_pk, log.session_id
            )
            if latest_pk != log_pk:
                msg = "Only the latest change for a session can be reverted"
                raise ValueError(msg)
            if log.action == ScheduleChangeAction.ASSIGN:
                agenda_item = self._uow.agenda_items.read_by_session(log.session_id)
                if agenda_item is None:
                    raise NotFoundError
                self._uow.agenda_items.delete(agenda_item.pk)
            elif log.action == ScheduleChangeAction.UNASSIGN:
                if (
                    log.old_space_id is None
                    or log.old_start_time is None
                    or log.old_end_time is None
                ):
                    msg = "Cannot revert UNASSIGN: missing original placement data"
                    raise ValueError(msg)
                session = self._uow.sessions.read(log.session_id)
                if session.status != SessionStatus.ACCEPTED:
                    msg = f"Session {log.session_id} is not in ACCEPTED status"
                    raise ValueError(msg)
                self._uow.agenda_items.create(
                    {
                        "session_id": log.session_id,
                        "space_id": log.old_space_id,
                        "start_time": log.old_start_time,
                        "end_time": log.old_end_time,
                        "session_confirmed": False,
                    }
                )
            else:
                msg = f"Cannot revert action: {log.action}"
                raise ValueError(msg)
            event = self._uow.sessions.read_event(log.session_id)
            revert_log: ScheduleChangeLogData = {
                "event_id": event.pk,
                "session_id": log.session_id,
                "user_id": user_pk,
                "action": ScheduleChangeAction.REVERT,
            }
            if log.action == ScheduleChangeAction.ASSIGN:
                revert_log["old_space_id"] = log.new_space_id
                revert_log["old_start_time"] = log.new_start_time
                revert_log["old_end_time"] = log.new_end_time
            else:
                revert_log["new_space_id"] = log.old_space_id
                revert_log["new_start_time"] = log.old_start_time
                revert_log["new_end_time"] = log.old_end_time
            self._uow.schedule_change_logs.create(revert_log)
