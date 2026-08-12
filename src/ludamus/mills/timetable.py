import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from operator import itemgetter
from typing import TYPE_CHECKING, NamedTuple

from ludamus.mills.event import require_session_in_event, require_track_in_event
from ludamus.mills.timeslots import SlotWindow, slot_windows_by_local_date
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
    HeatmapCellDTO,
    HeatmapCellStatus,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
    MultiselectOptionDTO,
    PreferredSlotRangeDTO,
    PreferredSlotViolationDTO,
    SessionPlacement,
    SessionPositionDTO,
    SessionPositionState,
    SpaceColumnDTO,
    SpaceGroupDTO,
    TimeLabelDTO,
    TimetableDayGridDTO,
    TimetableGridDTO,
    TimetableGridFilter,
    TrackProgressDTO,
)
from ludamus.specs.timetable import (
    TIMETABLE_ROOM_PAGE_SIZE,
    TIMETABLE_SLOT_MINUTES,
    TIMETABLE_SNAP_MINUTES,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts import FacilitatorDTO, SpaceDTO, TimeSlotDTO, UnitOfWorkProtocol


def conflicting_session_pks(conflicts: Iterable[ConflictDTO]) -> set[int]:
    # Both ends of a clash are wrong, and only one row carries the pair:
    # attributing it to the counterpart alone marks the innocent side and
    # leaves the offending one clean.
    return {
        pk
        for conflict in conflicts
        for pk in (conflict.subject_session_pk, conflict.session_pk)
    }


def _card_states(
    conflicts: Iterable[ConflictDTO], violations: Iterable[PreferredSlotViolationDTO]
) -> dict[int, SessionPositionState]:
    # What each card warns about, resolved once per page so the grid stops
    # testing the same session against page-wide sets on every element. A clash
    # outranks a slot violation, so it merges last.
    states: dict[int, SessionPositionState] = {
        violation.session_pk: "slot_violation" for violation in violations
    }
    states.update((pk, "conflict") for pk in conflicting_session_pks(conflicts))
    return states


def _position_sessions(
    *,
    items: list[AgendaItemDTO],
    grid_start: datetime,
    grid_end: datetime,
    states: dict[int, SessionPositionState],
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
            # clipped to that day's range. The real length rides along on the
            # item, so a drag reschedules the whole session, not the fragment.
            visible_start = max(item.start_time, grid_start)
            visible_end = min(item.end_time, grid_end)
            offset_min = (visible_start - grid_start).total_seconds() / 60
            visible_min = (visible_end - visible_start).total_seconds() / 60
            positions.append(
                SessionPositionDTO(
                    agenda_item=item,
                    start_minutes=round(offset_min),
                    duration_minutes=round(visible_min),
                    lane_start_pct=index * lane_width_pct,
                    lane_width_pct=lane_width_pct,
                    state=states.get(item.session_id, "normal"),
                )
            )

    return positions


def _walk_tree(nodes: list[SpaceDTO]) -> list[tuple[SpaceDTO, int]]:
    # Pre-order (node, depth). The grid's leaves, the picker's options and the
    # ancestor walk all read off this one traversal; a node whose parent_id
    # names nothing never gets walked, so unreachable rows stay out of all
    # three.
    children: dict[int | None, list[SpaceDTO]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)

    walked: list[tuple[SpaceDTO, int]] = []

    def walk(node: SpaceDTO, depth: int) -> None:
        walked.append((node, depth))
        for kid in children.get(node.pk, []):
            walk(kid, depth + 1)

    for root in children.get(None, []):
        walk(root, 0)
    return walked


def _leaves(walked: list[tuple[SpaceDTO, int]]) -> list[SpaceDTO]:
    parent_pks = {node.parent_id for node, _ in walked}
    return [node for node, _ in walked if node.pk not in parent_pks]


def _leaves_in_tree_order(nodes: list[SpaceDTO]) -> list[SpaceDTO]:
    # For the callers that want only the bookable rooms and never the tree.
    return _leaves(_walk_tree(nodes))


def _within_selected_spaces(
    walked: list[tuple[SpaceDTO, int]], selected: set[int]
) -> set[int]:
    # A branch stands for every leaf beneath it, so a leaf survives when the
    # selection names it or any of its ancestors.
    parent_by_pk = {node.pk: node.parent_id for node, _ in walked}
    kept: set[int] = set()
    for node, _ in walked:
        pk: int | None = node.pk
        while pk is not None:
            if pk in selected:
                kept.add(node.pk)
                break
            pk = parent_by_pk.get(pk)
    return kept


def _day_range(
    day: date, span: tuple[int, int], tz: tzinfo
) -> tuple[datetime, datetime]:
    midnight = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    start_minute, end_minute = span
    return (
        midnight + timedelta(minutes=start_minute),
        midnight + timedelta(minutes=end_minute),
    )


class TimetableService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow
        self._walked_event_pk: int | None = None
        self._walked: list[tuple[SpaceDTO, int]] = []

    def _tree(self, event_pk: int) -> list[tuple[SpaceDTO, int]]:
        # The page builds the grid and the space filter's options from the same
        # tree; the instance lives for one request and sees one event, so read
        # and walk it once. Nothing this service writes touches spaces, so
        # there is nothing to invalidate.
        if self._walked_event_pk != event_pk:
            self._walked = _walk_tree(self._uow.spaces.list_by_event(event_pk))
            self._walked_event_pk = event_pk
        return self._walked

    def space_filter_options(self, event_pk: int) -> list[MultiselectOptionDTO]:
        return [
            MultiselectOptionDTO(value=node.pk, label=node.name, depth=depth)
            for node, depth in self._tree(event_pk)
        ]

    def build_grid(
        self,
        *,
        event_pk: int,
        tz: tzinfo,
        space_page: int = 1,
        filters: TimetableGridFilter | None = None,
    ) -> TimetableGridDTO:
        filters = filters or TimetableGridFilter()
        track_pk = filters.track_pk
        date_selection = filters.date_selection
        # Before the first read that names it, not merely before the render:
        # `list_space_pks` below would otherwise walk another event's track and
        # be told it is foreign only later, by `list_grid_warnings`.
        if track_pk is not None:
            require_track_in_event(
                tracks=self._uow.tracks, track_pk=track_pk, event_pk=event_pk
            )
        walked = self._tree(event_pk)
        all_nodes = [node for node, _ in walked]
        node_name_by_pk = {node.pk: node.name for node in all_nodes}
        leaf_spaces = _leaves(walked)
        if track_pk is not None:
            track_space_pks = set(self._uow.tracks.list_space_pks(track_pk))
            leaf_spaces = [
                space for space in leaf_spaces if space.pk in track_space_pks
            ]
        if filters.space_pks:
            # Only pks belonging to this event's tree can match, so a stale or
            # foreign id in the URL narrows nothing rather than leaking a space.
            kept = _within_selected_spaces(walked, filters.space_pks)
            leaf_spaces = [space for space in leaf_spaces if space.pk in kept]

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
        # The grid shows everything scheduled in the rooms on screen, whoever
        # booked it. A room's occupancy is what makes a clash visible *before*
        # it is created, and hiding another track's booking is how two tracks
        # end up in one room at once.
        all_items = self._uow.agenda_items.list_by_event(event_pk)
        # Fetched here rather than handed in: the full page and the partial
        # swap that replaces it have to mark the grid the same way, and passing
        # the warnings in left every caller free to forget them. The items and
        # nodes above are handed on so one render is one load of each.
        conflicts, violations = ConflictDetectionService(self._uow).list_grid_warnings(
            event_pk=event_pk, track_pk=track_pk, items=all_items, spaces=all_nodes
        )
        # The unscheduled list filters by facilitator in SQL, so the grid does
        # too -- same one clause, and a foreign pk is scoped out by the query
        # rather than by happening to intersect with nothing. The warnings above
        # still see the whole event, so narrowing the view cannot hide a clash.
        shown_items = (
            self._uow.agenda_items.list_by_event(
                event_pk, facilitator_pks=filters.facilitator_pks
            )
            if filters.facilitator_pks
            else all_items
        )
        states = _card_states(conflicts, violations)
        span = self._shared_day_span(dates_to_render, windows_by_date, tz)
        days = [
            self._build_day_grid(
                date_to_render=date_to_render,
                day_range=_day_range(date_to_render, span, tz),
                spaces=spaces,
                all_items=shown_items,
                states=states,
            )
            for date_to_render in dates_to_render
        ]

        return TimetableGridDTO(
            spaces=spaces,
            groups=groups,
            days=days,
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
            conflicts=conflicts,
        )

    @staticmethod
    def _build_day_grid(
        *,
        date_to_render: date,
        day_range: tuple[datetime, datetime],
        spaces: list[SpaceDTO],
        all_items: list[AgendaItemDTO],
        states: dict[int, SessionPositionState],
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
                        items=items_for_space,
                        grid_start=grid_start,
                        grid_end=grid_end,
                        states=states,
                    ),
                )
            )

        total_minutes = round((grid_end - grid_start).total_seconds() / 60)
        slot_delta = timedelta(minutes=TIMETABLE_SLOT_MINUTES)
        return TimetableDayGridDTO(
            date=date_to_render,
            columns=columns,
            event_start_iso=grid_start.isoformat(),
            total_minutes=total_minutes,
            time_labels=[
                TimeLabelDTO(
                    time=grid_start + slot_delta * index,
                    offset_minutes=index * TIMETABLE_SLOT_MINUTES,
                )
                for index in range(total_minutes // TIMETABLE_SLOT_MINUTES + 1)
            ],
        )

    @staticmethod
    def _shared_day_span(
        days: list[date], windows_by_date: dict[date, list[SlotWindow]], tz: tzinfo
    ) -> tuple[int, int]:
        # One span for every rendered day, so 16:00 sits on the same row
        # whether its day opens at 16:00 or at 10:00. Windows are already
        # clamped to their local date, so both ends are minutes from midnight.
        midnights = {
            day: datetime.combine(day, datetime.min.time(), tzinfo=tz) for day in days
        }
        minutes = [
            (edge - midnights[day]).total_seconds() / 60
            for day in days
            for window in windows_by_date[day]
            for edge in window
        ]
        if not minutes:
            return (0, 0)
        return (
            math.floor(min(minutes) / TIMETABLE_SLOT_MINUTES) * TIMETABLE_SLOT_MINUTES,
            math.ceil(max(minutes) / TIMETABLE_SLOT_MINUTES) * TIMETABLE_SLOT_MINUTES,
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
            require_session_in_event(
                sessions=self._uow.sessions, session_pk=session_pk, event_pk=event_pk
            )
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
        require_session_in_event(
            sessions=self._uow.sessions, session_pk=session_pk, event_pk=event_pk
        )
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
        if track_pk is not None:
            require_track_in_event(
                tracks=self._uow.tracks, track_pk=track_pk, event_pk=event_pk
            )
        context = self._load_event_context(event_pk)
        return self._conflicts(
            subjects=self._subjects(context, track_pk),
            context=context,
            track_pk=track_pk,
        )

    def list_grid_warnings(
        self,
        *,
        event_pk: int,
        track_pk: int | None,
        items: list[AgendaItemDTO],
        spaces: list[SpaceDTO],
    ) -> tuple[list[ConflictDTO], list[PreferredSlotViolationDTO]]:
        # The grid has already loaded the event's items and space nodes, and
        # both warnings run off the same subjects. Taking them as arguments
        # keeps one render to one load of each instead of three.
        if track_pk is not None:
            require_track_in_event(
                tracks=self._uow.tracks, track_pk=track_pk, event_pk=event_pk
            )
        context = self._build_context(items=items, spaces=spaces)
        subjects = self._subjects(context, track_pk)
        return (
            self._conflicts(subjects=subjects, context=context, track_pk=track_pk),
            self._violations(subjects, track_pk),
        )

    def _subjects(
        self, context: _EventConflictContext, track_pk: int | None
    ) -> list[AgendaItemDTO]:
        if track_pk is None:
            return context.items
        return self._uow.agenda_items.list_by_track(track_pk)

    def _conflicts(
        self,
        *,
        subjects: list[AgendaItemDTO],
        context: _EventConflictContext,
        track_pk: int | None,
    ) -> list[ConflictDTO]:
        # Everything is loaded up front and overlaps are detected in memory:
        # a query per scheduled session turns one page load into thousands of
        # queries at a big event. Overlaps are checked against every scheduled
        # item in the event so a track page still surfaces cross-track clashes.
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
        return self._build_context(
            items=self._uow.agenda_items.list_by_event(event_pk),
            spaces=self._uow.spaces.list_by_event(event_pk),
        )

    def _build_context(
        self, *, items: list[AgendaItemDTO], spaces: list[SpaceDTO]
    ) -> _EventConflictContext:
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
            spaces={space.pk: space for space in spaces},
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
            # A multi-session facilitator (guild, organizer crew) is not one
            # person, so its parallel program points are not a clash.
            for facilitator in facilitators_by_session.get(item.session_id, [])
            if not facilitator.multi_session
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
        names_by_session = self._uow.sessions.list_track_names_by_session(
            sorted(session_pks)
        )
        # First by name, decided here rather than relied on from the query, so
        # a session in two other tracks reports the same one run to run.
        named_by_session: dict[int, tuple[int, str]] = {}
        for session_pk, tracks in names_by_session.items():
            others = [
                (track_pk, name)
                for track_pk, name in tracks.items()
                if track_pk != current_track_pk
            ]
            if others:
                named_by_session[session_pk] = min(others, key=itemgetter(1))
        manager_names = self._uow.tracks.list_manager_names_by_tracks(
            {track_pk for track_pk, _ in named_by_session.values()}
        )
        return {
            session_pk: (name, manager_names.get(track_pk, []))
            for session_pk, (track_pk, name) in named_by_session.items()
        }

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
        if track_pk is not None:
            require_track_in_event(
                tracks=self._uow.tracks, track_pk=track_pk, event_pk=event_pk
            )
        return self._violations(
            (
                self._uow.agenda_items.list_by_event(event_pk)
                if track_pk is None
                else self._uow.agenda_items.list_by_track(track_pk)
            ),
            track_pk,
        )

    def _violations(
        self, scheduled: list[AgendaItemDTO], track_pk: int | None
    ) -> list[PreferredSlotViolationDTO]:
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
        conflict_pks = conflicting_session_pks(conflicts)

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
                    elif overlapping.session_id in conflict_pks:
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
