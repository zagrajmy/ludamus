import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, NamedTuple

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts import (
    AgendaItemDTO,
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    SessionStatus,
    TrackSessionCountsDTO,
)
from ludamus.pacts.chronology import (
    CapacityHoursDTO,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    DateSelection,
    HeatmapCellDTO,
    HeatmapCellStatus,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
    PreferredSlotRangeDTO,
    PreferredSlotViolationDTO,
    SessionPlacement,
    SessionPositionDTO,
    SpaceColumnDTO,
    SpaceGroupDTO,
    TimeLabelDTO,
    TimetableDayGridDTO,
    TimetableGridDTO,
    TrackProgressDTO,
)
from ludamus.specs.timetable import (
    TIMETABLE_ROOM_PAGE_SIZE,
    TIMETABLE_SLOT_MINUTES,
    TIMETABLE_SNAP_MINUTES,
)

if TYPE_CHECKING:
    from ludamus.pacts import FacilitatorDTO, SpaceDTO, TimeSlotDTO, UnitOfWorkProtocol


def _position_sessions(
    *, items: list[AgendaItemDTO], grid_start: datetime, grid_end: datetime
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
            # A session crossing midnight renders on every day it touches,
            # clipped to that day's range; `duration_minutes` stays the real
            # length so a drag reschedules the whole session, not the fragment.
            visible_start = max(item.start_time, grid_start)
            visible_end = min(item.end_time, grid_end)
            offset_min = (visible_start - grid_start).total_seconds() / 60
            duration_min = (item.end_time - item.start_time).total_seconds() / 60
            visible_min = (visible_end - visible_start).total_seconds() / 60
            positions.append(
                SessionPositionDTO(
                    agenda_item=item,
                    start_minutes=round(offset_min),
                    duration_minutes=round(duration_min),
                    visible_minutes=round(visible_min),
                    lane_start_pct=index * lane_width_pct,
                    lane_width_pct=lane_width_pct,
                )
            )

    return positions


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
        leaf_spaces = _leaves_in_tree_order(all_nodes)
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
        day_range_starts = [
            datetime.combine(day, datetime.min.time(), tzinfo=tz)
            + timedelta(minutes=grid_start_minute)
            for day in dates_to_render
        ]
        days: list[TimetableDayGridDTO] = []
        for index, date_to_render in enumerate(dates_to_render):
            range_start = day_range_starts[index]
            range_end = range_start + timedelta(minutes=total_minutes)
            days.append(
                self._build_day_grid(
                    date_to_render=date_to_render,
                    day_range=(range_start, range_end),
                    spaces=spaces,
                    all_items=all_items,
                )
            )
        time_labels: list[TimeLabelDTO] = []
        if day_range_starts:
            label_start = day_range_starts[0]
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
            # Every day renders the same page of spaces -- `groups` already
            # relies on that -- so the calendar's flat track list is just the
            # page repeated once per day.
            total_columns=len(spaces) * len(days),
            available_dates=available_dates,
            date_selection=date_selection,
        )

    @staticmethod
    def _build_day_grid(
        *,
        date_to_render: date,
        day_range: tuple[datetime, datetime],
        spaces: list[SpaceDTO],
        all_items: list[AgendaItemDTO],
    ) -> TimetableDayGridDTO:
        grid_start, grid_end = day_range

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
                        items=items_for_space, grid_start=grid_start, grid_end=grid_end
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
                # An overnight window ends past 24:00 on its own day's clock.
                days_past_midnight = (window_end.date() - day).days
                end_minutes.append(
                    math.ceil(
                        (
                            days_past_midnight * 24 * 60
                            + window_end.hour * 60
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
            for space in _leaves_in_tree_order(self._uow.spaces.list_by_event(event_pk))
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


def _slot_start(slot: TimeSlotDTO) -> datetime:
    return slot.start_time


def _merged_slot_ranges(slots: list[TimeSlotDTO]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for slot in sorted(slots, key=_slot_start):
        if merged and slot.start_time <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], slot.end_time))
        else:
            merged.append((slot.start_time, slot.end_time))
    return merged


def _items_overlap(a: AgendaItemDTO, b: AgendaItemDTO) -> bool:
    return b.start_time < a.end_time and b.end_time > a.start_time


class _EventConflictContext(NamedTuple):
    # Everything conflict detection needs about an event, loaded once.
    items: list[AgendaItemDTO]
    items_by_space: dict[int, list[AgendaItemDTO]]
    items_by_facilitator: dict[int, list[AgendaItemDTO]]
    facilitators_by_session: dict[int, list[FacilitatorDTO]]
    spaces: dict[int, SpaceDTO]


class ConflictDetectionService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def detect_for_assignment(
        self, event_pk: int, session_pk: int
    ) -> list[ConflictDTO]:
        # Runs after the assignment commits, so the session's own agenda item
        # is already in the event context — detect on the real row through the
        # same in-memory engine as the full listing, so every conflict shape
        # has exactly one definition.
        context = self._load_event_context(event_pk)
        subject = next(
            (item for item in context.items if item.session_id == session_pk), None
        )
        if subject is None:
            raise NotFoundError
        limits = self._uow.sessions.read_participants_limits({session_pk})
        return self._detect(subject, context, limit=limits.get(session_pk, 0))

    def list_all_for_track(
        self, event_pk: int, track_pk: int | None
    ) -> list[ConflictDTO]:
        # Everything is loaded up front and overlaps are detected in memory:
        # a query per scheduled session turns one page load into thousands of
        # queries at a big event. Overlaps are checked against every scheduled
        # item in the event so a track page still surfaces cross-track clashes.
        context = self._load_event_context(event_pk)
        subjects = (
            context.items
            if track_pk is None
            else self._uow.agenda_items.list_by_track(track_pk)
        )
        if not subjects:
            return []

        limits = self._uow.sessions.read_participants_limits(
            {item.session_id for item in subjects}
        )
        all_conflicts: list[ConflictDTO] = []
        seen: set[tuple[int, int]] = set()
        for item in subjects:
            for conflict in self._detect(
                item, context, limit=limits.get(item.session_id, 0)
            ):
                key = (item.session_id, conflict.session_pk)
                reverse_key = (conflict.session_pk, item.session_id)
                if key not in seen and reverse_key not in seen:
                    seen.add(key)
                    all_conflicts.append(conflict)

        return self._add_track_attribution(all_conflicts, track_pk)

    def _load_event_context(self, event_pk: int) -> _EventConflictContext:
        items = self._uow.agenda_items.list_by_event(event_pk)
        facilitators_by_session = self._uow.sessions.read_facilitators_by_sessions(
            {item.session_id for item in items}
        )
        items_by_space: dict[int, list[AgendaItemDTO]] = defaultdict(list)
        items_by_facilitator: dict[int, list[AgendaItemDTO]] = defaultdict(list)
        for item in items:
            items_by_space[item.space_id].append(item)
            for facilitator in facilitators_by_session.get(item.session_id, []):
                items_by_facilitator[facilitator.pk].append(item)
        return _EventConflictContext(
            items=items,
            items_by_space=items_by_space,
            items_by_facilitator=items_by_facilitator,
            facilitators_by_session=facilitators_by_session,
            spaces={s.pk: s for s in self._uow.spaces.list_by_event(event_pk)},
        )

    def _detect(
        self, item: AgendaItemDTO, context: _EventConflictContext, *, limit: int
    ) -> list[ConflictDTO]:
        # The space->event invariant is enforced when assignments are created
        # but not by the database, so a stale row degrades to a skipped
        # capacity warning instead of a 500 on the whole grid.
        return [
            *self._space_conflicts(item, context.items_by_space),
            *self._capacity_conflicts(item, context.spaces.get(item.space_id), limit),
            *self._facilitator_conflicts(
                item, context.facilitators_by_session, context.items_by_facilitator
            ),
        ]

    @staticmethod
    def _space_conflicts(
        item: AgendaItemDTO, items_by_space: dict[int, list[AgendaItemDTO]]
    ) -> list[ConflictDTO]:
        return [
            ConflictDTO(
                type=ConflictType.SPACE_OVERLAP,
                severity=ConflictSeverity.ERROR,
                subject_session_title=item.session_title,
                subject_session_pk=item.session_id,
                session_title=other.session_title,
                session_pk=other.session_id,
            )
            for other in items_by_space.get(item.space_id, [])
            if other.session_id != item.session_id and _items_overlap(item, other)
        ]

    @staticmethod
    def _capacity_conflicts(
        item: AgendaItemDTO, space: SpaceDTO | None, limit: int
    ) -> list[ConflictDTO]:
        if space is None or space.capacity is None or space.capacity >= limit:
            return []
        return [
            ConflictDTO(
                type=ConflictType.CAPACITY_EXCEEDED,
                severity=ConflictSeverity.WARNING,
                subject_session_title=item.session_title,
                subject_session_pk=item.session_id,
                session_title=item.session_title,
                session_pk=item.session_id,
                space_capacity=space.capacity,
                session_limit=limit,
            )
        ]

    @staticmethod
    def _facilitator_conflicts(
        item: AgendaItemDTO,
        facilitators_by_session: dict[int, list[FacilitatorDTO]],
        items_by_facilitator: dict[int, list[AgendaItemDTO]],
    ) -> list[ConflictDTO]:
        return [
            ConflictDTO(
                type=ConflictType.FACILITATOR_OVERLAP,
                severity=ConflictSeverity.ERROR,
                subject_session_title=item.session_title,
                subject_session_pk=item.session_id,
                session_title=other.session_title,
                session_pk=other.session_id,
                facilitator_name=facilitator.display_name,
            )
            for facilitator in facilitators_by_session.get(item.session_id, [])
            for other in items_by_facilitator.get(facilitator.pk, [])
            if other.session_id != item.session_id and _items_overlap(item, other)
        ]

    def _foreign_track_attribution(
        self, session_pks: set[int], current_track_pk: int | None
    ) -> dict[int, tuple[str, list[str]]]:
        # A clash is often another track's doing; name that track and its
        # managers so organizers know whom to talk to. Sessions with no track
        # beyond the current one are simply absent from the result.
        if not session_pks:
            return {}
        tracks_by_session = self._uow.tracks.list_by_sessions(session_pks)
        manager_names = self._uow.tracks.list_manager_names_by_tracks(
            {t.pk for tracks in tracks_by_session.values() for t in tracks}
        )
        result: dict[int, tuple[str, list[str]]] = {}
        for session_pk, tracks in tracks_by_session.items():
            foreign = [
                t
                for t in tracks
                if current_track_pk is None or t.pk != current_track_pk
            ]
            if foreign:
                result[session_pk] = (
                    foreign[0].name,
                    manager_names.get(foreign[0].pk, []),
                )
        return result

    def _add_track_attribution(
        self, conflicts: list[ConflictDTO], current_track_pk: int | None
    ) -> list[ConflictDTO]:
        attribution = self._foreign_track_attribution(
            {
                c.session_pk
                for c in conflicts
                if c.type == ConflictType.FACILITATOR_OVERLAP
            },
            current_track_pk,
        )
        result: list[ConflictDTO] = []
        for conflict in conflicts:
            attributed = (
                attribution.get(conflict.session_pk)
                if conflict.type == ConflictType.FACILITATOR_OVERLAP
                else None
            )
            if attributed is None:
                result.append(conflict)
                continue
            update: dict[str, str | list[str]] = {
                "track_name": attributed[0],
                "manager_names": attributed[1],
            }
            result.append(conflict.model_copy(update=update))
        return result

    def list_preferred_slot_violations(
        self, event_pk: int, track_pk: int | None
    ) -> list[PreferredSlotViolationDTO]:
        scheduled = (
            self._uow.agenda_items.list_by_event(event_pk)
            if track_pk is None
            else self._uow.agenda_items.list_by_track(track_pk)
        )
        if not scheduled:
            return []

        preferred_by_session = self._uow.sessions.read_preferred_time_slots_by_sessions(
            {item.session_id for item in scheduled}
        )

        violating: list[tuple[AgendaItemDTO, list[TimeSlotDTO]]] = []
        for item in scheduled:
            if not (preferred := preferred_by_session.get(item.session_id, [])):
                continue
            if any(
                start <= item.start_time and end >= item.end_time
                for start, end in _merged_slot_ranges(preferred)
            ):
                continue
            violating.append((item, preferred))
        if not violating:
            return []

        attribution = self._foreign_track_attribution(
            {item.session_id for item, _ in violating}, track_pk
        )
        violations: list[PreferredSlotViolationDTO] = []
        for item, preferred in violating:
            track_name, managers = attribution.get(item.session_id, (None, []))
            violations.append(
                PreferredSlotViolationDTO(
                    session_pk=item.session_id,
                    session_title=item.session_title,
                    scheduled_start=item.start_time,
                    scheduled_end=item.end_time,
                    preferred_slots=[
                        PreferredSlotRangeDTO(
                            start_time=slot.start_time, end_time=slot.end_time
                        )
                        for slot in preferred
                    ],
                    track_name=track_name,
                    manager_names=managers,
                )
            )

        return violations


def _duration_hours(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / 3600, 0.0)


class TimetableOverviewService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def get_all_conflicts(self, event_pk: int) -> list[ConflictDTO]:
        return ConflictDetectionService(self._uow).list_all_for_track(
            event_pk, track_pk=None
        )

    def build_heatmap(
        self, event_pk: int, tz: tzinfo, conflicts: list[ConflictDTO] | None = None
    ) -> HeatmapDTO:
        # Only leaf spaces are bookable rooms; a venue or area column would be
        # permanently empty.
        spaces = _leaves_in_tree_order(self._uow.spaces.list_by_event(event_pk))
        all_items = self._uow.agenda_items.list_by_event(event_pk)
        if conflicts is None:
            conflicts = self.get_all_conflicts(event_pk)
        conflict_session_pks = {c.session_pk for c in conflicts}

        space_pk_set = {s.pk for s in spaces}
        space_items: dict[int, list[AgendaItemDTO]] = defaultdict(list)
        for item in all_items:
            if item.space_id in space_pk_set:
                space_items[item.space_id].append(item)

        windows_by_date = slot_windows_by_local_date(
            self._uow.time_slots.list_by_event(event_pk), tz
        )

        slot_delta = timedelta(minutes=TIMETABLE_SLOT_MINUTES)
        days: list[HeatmapDayDTO] = []
        all_rows: list[HeatmapRowDTO] = []

        for day_date in sorted(windows_by_date.keys()):
            day_windows = windows_by_date[day_date]
            day_start = min(w[0] for w in day_windows).replace(
                minute=0, second=0, microsecond=0
            )
            latest_end = max(w[1] for w in day_windows)
            day_end = latest_end.replace(minute=0, second=0, microsecond=0)
            if latest_end != day_end:
                day_end += slot_delta

            num_slots = int(
                (day_end - day_start).total_seconds() / 60 / TIMETABLE_SLOT_MINUTES
            )
            day_rows: list[HeatmapRowDTO] = []
            for i in range(num_slots):
                slot_time = day_start + slot_delta * i
                cells = []
                for space in spaces:
                    overlapping = next(
                        (
                            it
                            for it in space_items.get(space.pk, [])
                            if it.start_time <= slot_time < it.end_time
                        ),
                        None,
                    )
                    if overlapping is None:
                        status = HeatmapCellStatus.EMPTY
                    elif overlapping.session_id in conflict_session_pks:
                        status = HeatmapCellStatus.CONFLICT
                    else:
                        status = HeatmapCellStatus.SCHEDULED
                    cells.append(HeatmapCellDTO(space_pk=space.pk, status=status))
                day_rows.append(HeatmapRowDTO(time=slot_time, cells=cells))

            days.append(HeatmapDayDTO(date=day_date, rows=day_rows))
            all_rows.extend(day_rows)

        return HeatmapDTO(spaces=spaces, rows=all_rows, days=days)

    def all_conflicts_grouped(
        self, event_pk: int, conflicts: list[ConflictDTO] | None = None
    ) -> dict[str, list[ConflictDTO]]:
        if conflicts is None:
            conflicts = self.get_all_conflicts(event_pk)
        grouped: dict[str, list[ConflictDTO]] = {}
        for conflict in conflicts:
            if (key := conflict.type) not in grouped:
                grouped[key] = []
            grouped[key].append(conflict)
        return grouped

    def track_progress(self, event_pk: int) -> list[TrackProgressDTO]:
        # Counts come from one aggregate query; loading every session row per
        # track just to count statuses made the overview page O(tracks) in
        # full-table queries.
        if not (tracks := self._uow.tracks.list_by_event(event_pk)):
            return []
        counts_by_track = self._uow.sessions.count_by_track(event_pk)
        manager_names = self._uow.tracks.list_manager_names_by_tracks(
            {track.pk for track in tracks}
        )

        result = []
        no_sessions = TrackSessionCountsDTO()
        for track in tracks:
            counts = counts_by_track.get(track.pk, no_sessions)
            # Progress is measured against the active pool (everything not
            # rejected / on hold), so pending proposals still awaiting a
            # decision count as unscheduled program to place.
            active_count = counts.pending + counts.accepted
            progress_pct = (
                round(counts.scheduled * 100 / active_count) if active_count else 0
            )
            result.append(
                TrackProgressDTO(
                    track_pk=track.pk,
                    track_name=track.name,
                    manager_names=manager_names.get(track.pk, []),
                    accepted_count=counts.accepted,
                    scheduled_count=counts.scheduled,
                    pending_count=counts.pending,
                    on_hold_count=counts.on_hold,
                    rejected_count=counts.rejected,
                    progress_pct=progress_pct,
                )
            )
        return result

    def capacity_hours(self, event_pk: int) -> CapacityHoursDTO:
        # Capacity = one program slot per room: every room is bookable for the
        # whole of each event time slot. Scheduled = hours already occupied by
        # placed agenda items in those rooms. Hours-to-fill is the remainder.
        rooms = _leaves_in_tree_order(self._uow.spaces.list_by_event(event_pk))
        room_count = len(rooms)

        slots = self._uow.time_slots.list_by_event(event_pk)
        slot_hours = sum(_duration_hours(s.start_time, s.end_time) for s in slots)
        capacity_hours = slot_hours * room_count

        room_pks = {s.pk for s in rooms}
        scheduled_hours = sum(
            _duration_hours(item.start_time, item.end_time)
            for item in self._uow.agenda_items.list_by_event(event_pk)
            if item.space_id in room_pks
        )

        hours_to_fill = max(capacity_hours - scheduled_hours, 0.0)
        filled_pct = (
            round(scheduled_hours * 100 / capacity_hours) if capacity_hours else 0
        )
        return CapacityHoursDTO(
            room_count=room_count,
            slot_hours=round(slot_hours, 1),
            capacity_hours=round(capacity_hours, 1),
            scheduled_hours=round(scheduled_hours, 1),
            hours_to_fill=round(hours_to_fill, 1),
            filled_pct=filled_pct,
        )
