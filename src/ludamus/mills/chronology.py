"""Chronology subdomain business logic.

Currently spans the Timetable (agenda scheduling) and CFP (personal-data
field management) bounded contexts. Split per `plans/hex_refactor.md` if
the file grows past ~12 top-level members or 1000 lines.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts import (
    EventDTO,
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    SessionContentEditData,
    SessionDTO,
    SessionFieldValueData,
    SessionSelfEditContext,
    SessionStatus,
)
from ludamus.pacts.chronology import (
    TIMETABLE_ROOM_PAGE_SIZE,
    TIMETABLE_SLOT_MINUTES,
    CapacityHoursDTO,
    CheckOutcome,
    CheckResult,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    EventIntegrationCreateData,
    EventIntegrationDTO,
    EventIntegrationsRepositoryProtocol,
    EventIntegrationsServiceProtocol,
    EventIntegrationUpdateData,
    HeatmapCellDTO,
    HeatmapCellStatus,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
    IntegrationCheckRequest,
    IntegrationImplementation,
    IntegrationImplementationId,
    IntegrationKind,
    PreferredSlotRangeDTO,
    PreferredSlotViolationDTO,
    SessionPlacement,
    SessionPositionDTO,
    SourceQuestion,
    SpaceColumnDTO,
    SpaceGroupDTO,
    TimeLabelDTO,
    TimetableGridDTO,
    TrackProgressDTO,
)
from ludamus.pacts.legacy import resolve_cover_image
from ludamus.pacts.submissions import ImportRow, ImportSettings, QuestionTarget
from ludamus.specs.chronology import resolve_facilitator_session_edit

_SOURCE_QUESTIONS_ADAPTER = TypeAdapter(list[SourceQuestion])

if TYPE_CHECKING:
    from ludamus.pacts import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        ContentChangeLogData,
        ContentChangeLogDTO,
        ContentChangeLogRepositoryProtocol,
        ContentFieldChange,
        ContentFieldValue,
        ScheduleChangeLogRepositoryProtocol,
        SessionFieldRepositoryProtocol,
        SessionFieldValueDTO,
        SessionRepositoryProtocol,
        SessionUpdateData,
        SpaceDTO,
        SphereRepositoryProtocol,
        TrackRepositoryProtocol,
        UnitOfWorkProtocol,
    )
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


def _duration_hours(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / 3600, 0.0)


def _position_sessions(
    items: list[AgendaItemDTO], event_start: datetime
) -> list[SessionPositionDTO]:
    # Compute time-domain positions for sessions in a single space column.
    # Overlapping sessions are placed side by side by splitting the column width.
    if not items:
        return []

    # Group items into non-overlapping clusters using a sweep
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
    if current_group:
        groups.append(current_group)

    positions: list[SessionPositionDTO] = []
    for group in groups:
        n = len(group)
        lane_width_pct = 100.0 / n
        for i, item in enumerate(group):
            offset_min = (item.start_time - event_start).total_seconds() / 60
            duration_min = (item.end_time - item.start_time).total_seconds() / 60
            positions.append(
                SessionPositionDTO(
                    agenda_item=item,
                    start_minutes=round(offset_min),
                    duration_minutes=round(duration_min),
                    lane_start_pct=i * lane_width_pct,
                    lane_width_pct=lane_width_pct,
                )
            )

    return positions


def require_session_in_event(
    sessions: SessionRepositoryProtocol, session_pk: int, event_pk: int
) -> None:
    # Panel access only proves you manage `event_pk`; a session named in
    # the request must belong to it, or it is cross-event tampering.
    if sessions.read_event(session_pk).pk != event_pk:
        raise NotFoundError


class TimetableService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def build_grid(
        self,
        event_pk: int,
        tz: tzinfo,
        track_pk: int | None = None,
        space_page: int = 1,
        selected_date: date | None = None,
    ) -> TimetableGridDTO:
        all_nodes = self._uow.spaces.list_by_event(event_pk)
        node_name_by_pk = {node.pk: node.name for node in all_nodes}
        leaf_spaces = self._leaves_in_tree_order(all_nodes)
        if track_pk is not None:
            track_space_pks = set(self._uow.tracks.list_space_pks(track_pk))
            leaf_spaces = [s for s in leaf_spaces if s.pk in track_space_pks]

        total_spaces = len(leaf_spaces)
        total_pages = max(1, math.ceil(total_spaces / TIMETABLE_ROOM_PAGE_SIZE))
        space_page = max(1, min(space_page, total_pages))
        start = (space_page - 1) * TIMETABLE_ROOM_PAGE_SIZE
        spaces = leaf_spaces[start : start + TIMETABLE_ROOM_PAGE_SIZE]

        all_slots = self._uow.time_slots.list_by_event(event_pk)
        windows_by_date = slot_windows_by_local_date(all_slots, tz)
        available_dates = sorted(windows_by_date.keys())

        if selected_date is None or selected_date not in windows_by_date:
            selected_date = available_dates[0] if available_dates else None

        groups = self._build_space_groups(spaces, node_name_by_pk)

        if selected_date is None:
            return TimetableGridDTO(
                spaces=spaces,
                columns=[SpaceColumnDTO(space=s, sessions=[]) for s in spaces],
                groups=groups,
                time_labels=[],
                total_minutes=0,
                event_start_iso="",
                slot_minutes=TIMETABLE_SLOT_MINUTES,
                page=space_page,
                total_pages=total_pages,
                total_spaces=total_spaces,
                available_dates=available_dates,
                selected_date=None,
            )

        day_windows = windows_by_date[selected_date]
        grid_start = min(w[0] for w in day_windows).replace(
            minute=0, second=0, microsecond=0
        )
        latest_end = max(w[1] for w in day_windows)
        grid_end = latest_end.replace(minute=0, second=0, microsecond=0)
        if latest_end != grid_end:
            grid_end += timedelta(hours=1)

        total_minutes = int((grid_end - grid_start).total_seconds() / 60)
        num_slots = total_minutes // TIMETABLE_SLOT_MINUTES

        slot_delta = timedelta(minutes=TIMETABLE_SLOT_MINUTES)
        time_labels = [
            TimeLabelDTO(
                time=grid_start + slot_delta * i,
                offset_minutes=i * TIMETABLE_SLOT_MINUTES,
            )
            for i in range(num_slots + 1)
        ]

        all_items = (
            self._uow.agenda_items.list_by_track(track_pk)
            if track_pk is not None
            else self._uow.agenda_items.list_by_event(event_pk)
        )
        space_pk_set = {s.pk for s in spaces}
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
            items_for_space.sort(key=lambda x: x.start_time)
            columns.append(
                SpaceColumnDTO(
                    space=space,
                    sessions=_position_sessions(
                        items_for_space, event_start=grid_start
                    ),
                )
            )

        return TimetableGridDTO(
            spaces=spaces,
            columns=columns,
            groups=groups,
            time_labels=time_labels,
            total_minutes=num_slots * TIMETABLE_SLOT_MINUTES,
            event_start_iso=grid_start.isoformat(),
            slot_minutes=TIMETABLE_SLOT_MINUTES,
            page=space_page,
            total_pages=total_pages,
            total_spaces=total_spaces,
            available_dates=available_dates,
            selected_date=selected_date,
        )

    @staticmethod
    def _leaves_in_tree_order(nodes: list[SpaceDTO]) -> list[SpaceDTO]:
        # Depth-first walk of the space tree, returning only the leaves (the
        # bookable rooms) in display order. Siblings keep `nodes` ordering.
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
        # One header cell per run of consecutive leaves sharing an immediate
        # parent (collapsing the old venue-row + area-row to a single row).
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
        require_session_in_event(self._uow.sessions, session_pk, event_pk)

    def _require_space_in_event(self, space_pk: int, event_pk: int) -> None:
        # Only leaf spaces (bookable rooms) may hold a session; a branch node
        # would violate the leaf-only invariant the timetable grid relies on.
        leaf_pks = {
            s.pk
            for s in self._leaves_in_tree_order(
                self._uow.spaces.list_by_event(event_pk)
            )
        }
        if space_pk not in leaf_pks:
            raise NotFoundError

    def _clear_existing_assignment(
        self, session_pk: int, event_pk: int, user_pk: int | None
    ) -> None:
        # Re-assigning an already-scheduled session: drop the old placement
        # first so the new one becomes its only agenda item.
        if self._uow.agenda_items.read_by_session(session_pk) is not None:
            self.unassign_session(session_pk, event_pk=event_pk, user_pk=user_pk)

    def assign_session(
        self,
        session_pk: int,
        placement: SessionPlacement,
        event_pk: int,
        user_pk: int | None = None,
    ) -> None:
        with self._uow.atomic():
            self._require_session_in_event(session_pk, event_pk)
            self._require_space_in_event(placement.space_pk, event_pk)
            # Lock the target Space row before creating the placement so a
            # concurrent subtree delete (which locks the same rows before its
            # no-sessions check) can't cascade this AgendaItem away in the gap
            # between that check and the delete.
            self._uow.spaces.lock(placement.space_pk)
            self._clear_existing_assignment(session_pk, event_pk, user_pk)
            session = self._uow.sessions.read(session_pk)
            if session.status != SessionStatus.PENDING:
                msg = f"Session {session_pk} is not in PENDING status"
                raise ValueError(msg)
            event = self._uow.sessions.read_event(session_pk)
            self._uow.agenda_items.create(
                {
                    "session_id": session_pk,
                    "space_id": placement.space_pk,
                    "start_time": placement.start_time,
                    "end_time": placement.end_time,
                    "session_confirmed": event.auto_confirm_sessions,
                }
            )
            self._uow.sessions.update(session_pk, {"status": SessionStatus.SCHEDULED})
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
        self, session_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None:
        self._require_session_in_event(session_pk, event_pk)
        if (agenda_item := self._uow.agenda_items.read_by_session(session_pk)) is None:
            raise NotFoundError
        event = self._uow.sessions.read_event(session_pk)
        self._uow.agenda_items.delete(agenda_item.pk)
        self._uow.sessions.update(session_pk, {"status": SessionStatus.PENDING})
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
        self, log_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None:
        log = self._uow.schedule_change_logs.read(log_pk)
        if log.event_id != event_pk:
            # The log belongs to another event — reject before reverting.
            raise NotFoundError
        # Lock the session row so concurrent reverts (and assign/unassign)
        # serialize: the latest-pk check and all mutations run under one
        # transaction, so a second revert re-reads a now-stale latest_pk and
        # is rejected instead of racing past the check (TOCTOU).
        with self._uow.atomic():
            self._uow.sessions.lock(log.session_id)
            latest_pk = self._uow.schedule_change_logs.latest_pk_for_session(
                event_pk, log.session_id
            )
            if latest_pk != log_pk:
                # Only the most recent change for a session may be undone, so
                # reverts always unwind history in order.
                msg = "Only the latest change for a session can be reverted"
                raise ValueError(msg)
            if log.action == ScheduleChangeAction.ASSIGN:
                agenda_item = self._uow.agenda_items.read_by_session(log.session_id)
                if agenda_item is None:
                    raise NotFoundError
                self._uow.agenda_items.delete(agenda_item.pk)
                self._uow.sessions.update(
                    log.session_id, {"status": SessionStatus.PENDING}
                )
            elif log.action == ScheduleChangeAction.UNASSIGN:
                if (
                    log.old_space_id is None
                    or log.old_start_time is None
                    or log.old_end_time is None
                ):
                    msg = "Cannot revert UNASSIGN: missing original placement data"
                    raise ValueError(msg)
                session = self._uow.sessions.read(log.session_id)
                if session.status != SessionStatus.PENDING:
                    msg = f"Session {log.session_id} is not in PENDING status"
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
                self._uow.sessions.update(
                    log.session_id, {"status": SessionStatus.SCHEDULED}
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
            elif log.action == ScheduleChangeAction.UNASSIGN:
                revert_log["new_space_id"] = log.old_space_id
                revert_log["new_start_time"] = log.old_start_time
                revert_log["new_end_time"] = log.old_end_time
            self._uow.schedule_change_logs.create(revert_log)


class SessionConfirmationService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        sessions: SessionRepositoryProtocol,
        tracks: TrackRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._agenda_items = agenda_items
        self._sessions = sessions
        self._tracks = tracks

    def set_session_confirmed(
        self, event_pk: int, agenda_item_pk: int, *, confirmed: bool
    ) -> None:
        agenda_item = self._agenda_items.read(agenda_item_pk)
        require_session_in_event(self._sessions, agenda_item.session_id, event_pk)
        with self._transaction.atomic():
            self._agenda_items.update(agenda_item_pk, {"session_confirmed": confirmed})

    def confirm_all(self, event_pk: int) -> None:
        with self._transaction.atomic():
            self._agenda_items.confirm_all_by_event(event_pk)

    def confirm_block(self, event_pk: int, track_pk: int) -> None:
        # Panel access only proves you manage `event_pk`; a track named in the
        # request must belong to it, or it is cross-event tampering.
        if self._tracks.read(track_pk).event_id != event_pk:
            raise NotFoundError
        with self._transaction.atomic():
            self._agenda_items.confirm_all_by_track(track_pk)


class SessionDeletionService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        schedule_change_logs: ScheduleChangeLogRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda_items = agenda_items
        self._schedule_change_logs = schedule_change_logs

    def soft_delete(
        self, event_pk: int, session_pk: int, user_pk: int | None = None
    ) -> None:
        with self._transaction.atomic():
            # Lock the session row first, then re-check event membership while
            # holding the lock: a concurrent request can no longer move the
            # session to another event (or delete it) between the check and the
            # mutation (TOCTOU). `lock` raises NotFound for missing/already-dead.
            self._sessions.lock(session_pk)
            require_session_in_event(self._sessions, session_pk, event_pk)
            # Free the timetable slot through the existing unschedule path:
            # drop the agenda item, return the session to PENDING, and record
            # the unassignment in the schedule activity log.
            agenda_item = self._agenda_items.read_by_session(session_pk)
            if agenda_item is not None:
                self._agenda_items.delete(agenda_item.pk)
                self._sessions.update(session_pk, {"status": SessionStatus.PENDING})
                log_data: ScheduleChangeLogData = {
                    "event_id": event_pk,
                    "session_id": session_pk,
                    "user_id": user_pk,
                    "action": ScheduleChangeAction.UNASSIGN,
                    "old_space_id": agenda_item.space_id,
                    "old_start_time": agenda_item.start_time,
                    "old_end_time": agenda_item.end_time,
                }
                self._schedule_change_logs.create(log_data)
            # Participations are retained as history (not cancelled).
            self._sessions.soft_delete(session_pk)

    def restore(self, event_pk: int, session_pk: int) -> None:
        # The session returns unscheduled (it was set to PENDING on delete); no
        # agenda item or schedule-change log — restore changes no slot. The repo
        # scopes to the event (the alive-manager check can't see deleted rows).
        with self._transaction.atomic():
            self._sessions.restore(session_pk, event_pk)


class ProposalStatusService:
    def __init__(
        self, transaction: TransactionProtocol, sessions: SessionRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions

    def mark_accepted(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.ACCEPTED
        )

    def mark_on_hold(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.ON_HOLD
        )

    def mark_rejected(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.REJECTED
        )

    def _set_status(
        self, *, event_pk: int, session_pk: int, status: SessionStatus
    ) -> None:
        with self._transaction.atomic():
            # Lock first, then re-check event membership under the lock so a
            # concurrent request can't move the session to another event between
            # the check and the write (TOCTOU). `lock` raises for missing/dead.
            self._sessions.lock(session_pk)
            require_session_in_event(self._sessions, session_pk, event_pk)
            self._sessions.update(session_pk, {"status": status})


class ConflictDetectionService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def detect_for_assignment(
        self, session_pk: int, placement: SessionPlacement
    ) -> list[ConflictDTO]:
        conflicts: list[ConflictDTO] = []
        session = self._uow.sessions.read(session_pk)
        space_pk = placement.space_pk
        start_time = placement.start_time
        end_time = placement.end_time

        # Space overlap
        overlapping_in_space = self._uow.agenda_items.list_overlapping_in_space(
            space_pk, start_time, end_time, exclude_session_pk=session_pk
        )
        conflicts.extend(
            [
                ConflictDTO(
                    type=ConflictType.SPACE_OVERLAP,
                    severity=ConflictSeverity.ERROR,
                    session_title=item.session_title,
                    session_pk=item.session_id,
                )
                for item in overlapping_in_space
            ]
        )

        # Capacity exceeded
        space = self._uow.spaces.read(space_pk)
        if space.capacity is not None and space.capacity < session.participants_limit:
            conflicts.append(
                ConflictDTO(
                    type=ConflictType.CAPACITY_EXCEEDED,
                    severity=ConflictSeverity.WARNING,
                    session_title=session.title,
                    session_pk=session_pk,
                    space_capacity=space.capacity,
                    session_limit=session.participants_limit,
                )
            )

        # Facilitator overlap
        facilitators = self._uow.sessions.read_facilitators(session_pk)
        for facilitator in facilitators:
            overlapping_for_facilitator = (
                self._uow.agenda_items.list_overlapping_by_facilitator(
                    facilitator.pk, start_time, end_time, exclude_session_pk=session_pk
                )
            )
            conflicts.extend(
                [
                    ConflictDTO(
                        type=ConflictType.FACILITATOR_OVERLAP,
                        severity=ConflictSeverity.ERROR,
                        session_title=item.session_title,
                        session_pk=item.session_id,
                        facilitator_name=facilitator.display_name,
                    )
                    for item in overlapping_for_facilitator
                ]
            )

        return conflicts

    def list_all_for_track(
        self, event_pk: int, track_pk: int | None
    ) -> list[ConflictDTO]:
        scheduled = (
            self._uow.agenda_items.list_by_event(event_pk)
            if track_pk is None
            else self._uow.agenda_items.list_by_track(track_pk)
        )

        all_conflicts: list[ConflictDTO] = []
        seen: set[tuple[int, int]] = set()
        for item in scheduled:
            conflicts = self.detect_for_assignment(
                session_pk=item.session_id,
                placement=SessionPlacement(
                    space_pk=item.space_id,
                    start_time=item.start_time,
                    end_time=item.end_time,
                ),
            )
            for conflict in conflicts:
                key = (item.session_id, conflict.session_pk)
                reverse_key = (conflict.session_pk, item.session_id)
                if key not in seen and reverse_key not in seen:
                    seen.add(key)
                    all_conflicts.append(
                        self._add_track_attribution(conflict, track_pk)
                    )

        return all_conflicts

    def _add_track_attribution(
        self, conflict: ConflictDTO, current_track_pk: int | None
    ) -> ConflictDTO:
        if conflict.type != ConflictType.FACILITATOR_OVERLAP:
            return conflict
        other_tracks = self._uow.tracks.list_by_session(conflict.session_pk)
        if current_track_pk is not None:
            other_tracks = [t for t in other_tracks if t.pk != current_track_pk]
        if not other_tracks:
            return conflict
        track = other_tracks[0]
        return ConflictDTO(
            type=conflict.type,
            severity=conflict.severity,
            session_title=conflict.session_title,
            session_pk=conflict.session_pk,
            facilitator_name=conflict.facilitator_name,
            track_name=track.name,
            manager_names=self._uow.tracks.list_manager_names(track.pk),
        )

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

        violations: list[PreferredSlotViolationDTO] = []
        for item in scheduled:
            if not (preferred := preferred_by_session.get(item.session_id, [])):
                continue
            if any(
                slot.start_time <= item.start_time and slot.end_time >= item.end_time
                for slot in preferred
            ):
                continue
            track_name, manager_names = self._slot_violation_track_attribution(
                item.session_id, track_pk
            )
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
                    manager_names=manager_names,
                )
            )

        return violations

    def _slot_violation_track_attribution(
        self, session_pk: int, current_track_pk: int | None
    ) -> tuple[str | None, list[str]]:
        tracks = self._uow.tracks.list_by_session(session_pk)
        if current_track_pk is not None:
            tracks = [t for t in tracks if t.pk != current_track_pk]
        if not tracks:
            return None, []
        track = tracks[0]
        return track.name, self._uow.tracks.list_manager_names(track.pk)


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
        spaces = self._uow.spaces.list_by_event(event_pk)
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
        tracks = self._uow.tracks.list_by_event(event_pk)
        result = []
        for track in tracks:
            sessions = self._uow.sessions.list_sessions_by_event(
                event_pk, track_pk=track.pk
            )
            accepted = [
                s
                for s in sessions
                if s.status in {SessionStatus.PENDING, SessionStatus.SCHEDULED}
            ]
            scheduled = [s for s in sessions if s.status == SessionStatus.SCHEDULED]
            accepted_count = len(accepted)
            scheduled_count = len(scheduled)
            progress_pct = (
                round(scheduled_count * 100 / accepted_count) if accepted_count else 0
            )
            manager_names = self._uow.tracks.list_manager_names(track.pk)
            result.append(
                TrackProgressDTO(
                    track_pk=track.pk,
                    track_name=track.name,
                    manager_names=manager_names,
                    accepted_count=accepted_count,
                    scheduled_count=scheduled_count,
                    progress_pct=progress_pct,
                )
            )
        return result

    def capacity_hours(self, event_pk: int) -> CapacityHoursDTO:
        # Capacity = one program slot per room: every room is bookable for the
        # whole of each event time slot. Scheduled = hours already occupied by
        # placed agenda items in those rooms. Hours-to-fill is the remainder.
        spaces = self._uow.spaces.list_by_event(event_pk)
        room_count = len(spaces)

        slots = self._uow.time_slots.list_by_event(event_pk)
        slot_hours = sum(_duration_hours(s.start_time, s.end_time) for s in slots)
        capacity_hours = slot_hours * room_count

        space_pk_set = {s.pk for s in spaces}
        scheduled_hours = sum(
            _duration_hours(item.start_time, item.end_time)
            for item in self._uow.agenda_items.list_by_event(event_pk)
            if item.space_id in space_pk_set
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


class SessionEditNotAllowedError(Exception):
    """Raised when a user may not self-edit the requested session."""


def _normalize(value: ContentFieldValue) -> ContentFieldValue:
    return "" if value is None else value


def _diff_cover_image(old_url: str, new_value: object) -> ContentFieldChange | None:
    # new_value is "" when the cover was cleared, or a file object on upload.
    if not new_value:
        if old_url:
            return {"field": "cover_image", "field_id": None, "old": old_url, "new": ""}
        return None
    return {
        "field": "cover_image",
        "field_id": None,
        "old": old_url,
        "new": "(updated)",
    }


def _diff_field_values(
    old_values: list[SessionFieldValueDTO], new_values: list[SessionFieldValueData]
) -> list[ContentFieldChange]:
    old_by_id = {v.field_id: v.value for v in old_values}
    changes: list[ContentFieldChange] = []
    for new in new_values:
        field_id = new["field_id"]
        old_value = old_by_id.get(field_id)
        new_value = new["value"]
        if _normalize(old_value) == _normalize(new_value):
            continue
        changes.append(
            {"field": "", "field_id": field_id, "old": old_value, "new": new_value}
        )
    return changes


def _core_comparisons(
    old_session: SessionDTO, update: SessionUpdateData
) -> list[tuple[str, ContentFieldValue, ContentFieldValue]]:
    # Keys are accessed literally (not in a loop) so the TypedDict / DTO field
    # types stay statically known. cover_image is handled separately.
    comparisons: list[tuple[str, ContentFieldValue, ContentFieldValue]] = []
    if "title" in update:
        comparisons.append(("title", old_session.title, update["title"]))
    if "display_name" in update:
        comparisons.append(
            ("display_name", old_session.display_name, update["display_name"])
        )
    if "description" in update:
        comparisons.append(
            ("description", old_session.description, update["description"])
        )
    if "requirements" in update:
        comparisons.append(
            ("requirements", old_session.requirements, update["requirements"])
        )
    if "needs" in update:
        comparisons.append(("needs", old_session.needs, update["needs"]))
    if "contact_email" in update:
        comparisons.append(
            ("contact_email", old_session.contact_email, update["contact_email"])
        )
    if "participants_limit" in update:
        comparisons.append(
            (
                "participants_limit",
                old_session.participants_limit,
                update["participants_limit"],
            )
        )
    if "min_age" in update:
        comparisons.append(("min_age", old_session.min_age, update["min_age"]))
    if "duration" in update:
        comparisons.append(("duration", old_session.duration, update["duration"]))
    return comparisons


def diff_session_content(
    old_session: SessionDTO,
    update: SessionUpdateData,
    old_values: list[SessionFieldValueDTO],
    new_values: list[SessionFieldValueData],
) -> list[ContentFieldChange]:
    # Field-by-field diff of a session edit, as a flat list of changes: core
    # session columns plus dynamic session-field answers. Pure, identity-only
    # (no display text) — mirrors exactly what the edit persists.
    changes: list[ContentFieldChange] = [
        {"field": key, "field_id": None, "old": old_value, "new": new_value}
        for key, old_value, new_value in _core_comparisons(old_session, update)
        if old_value != new_value
    ]
    if "cover_image" in update:
        cover_change = _diff_cover_image(
            old_session.cover_image_url, update["cover_image"]
        )
        if cover_change is not None:
            changes.append(cover_change)
    changes.extend(_diff_field_values(old_values, new_values))
    return changes


class SessionContentEditService:
    # Shared by the facilitator self-edit and organizer panel edit so both
    # paths write the same ContentChangeLog; owns the transactional boundary.

    def __init__(
        self,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        content_change_logs: ContentChangeLogRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._session_fields = session_fields
        self._content_change_logs = content_change_logs

    def apply(
        self,
        *,
        session_id: int,
        event_id: int,
        user_id: int | None,
        data: SessionContentEditData,
    ) -> None:
        # All writes share one transaction so a partial edit can never be
        # committed. data.facilitator_ids None leaves the assignment untouched
        # (self-edit); a list (possibly empty) replaces it.
        with self._transaction.atomic():
            old_session = self._sessions.read(session_id)
            old_values = self._sessions.read_field_values(session_id)
            self._sessions.update(session_id, data.update)
            if data.field_values is not None:
                self._sessions.save_field_values(session_id, data.field_values)
            values_for_diff = (
                data.field_values
                if data.field_values is not None
                else [
                    SessionFieldValueData(
                        session_id=session_id, field_id=fv.field_id, value=fv.value
                    )
                    for fv in old_values
                ]
            )
            if data.facilitator_ids is not None:
                self._sessions.set_facilitators(session_id, data.facilitator_ids)
            changes = diff_session_content(
                old_session, data.update, old_values, values_for_diff
            )
            if changes:
                log_data: ContentChangeLogData = {
                    "event_id": event_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "changes": changes,
                }
                self._content_change_logs.create(log_data)

    def list_log(self, event_id: int) -> list[ContentChangeLogDTO]:
        return self._content_change_logs.list_by_event(event_id)

    def list_field_names(self, event_id: int) -> dict[int, str]:
        # Render-time resolution of dynamic session-field labels (user content,
        # not UI text) so the log shows the field's current name.
        return {f.pk: f.name for f in self._session_fields.list_by_event(event_id)}


class SessionSelfEditService:
    """Facilitator self-service editing of their own session."""

    def __init__(
        self,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
        content_edit: SessionContentEditService,
    ) -> None:
        self._sessions = sessions
        self._session_fields = session_fields
        self._spheres = spheres
        self._content_edit = content_edit

    def _gate(
        self, session_id: int, user_id: int | None
    ) -> tuple[bool, SessionDTO | None, EventDTO | None]:
        if user_id is None:
            return False, None, None
        try:
            session = self._sessions.read(session_id)
        except NotFoundError:
            return False, None, None
        if session.presenter_id is None or session.presenter_id != user_id:
            return False, session, None
        try:
            event = self._sessions.read_event(session_id)
        except NotFoundError:
            return False, session, None
        sphere = self._spheres.read(event.sphere_id)
        allowed = resolve_facilitator_session_edit(
            event_override=event.allow_facilitator_session_edit,
            sphere_default=sphere.allow_facilitator_session_edit,
        )
        return allowed, session, event

    def can_edit(self, session_id: int, user_id: int | None) -> bool:
        allowed, _session, _event = self._gate(session_id, user_id)
        return allowed

    def get_edit_context(
        self, session_id: int, user_id: int | None
    ) -> SessionSelfEditContext:
        allowed, session, event = self._gate(session_id, user_id)
        if not allowed or session is None or event is None:
            raise SessionEditNotAllowedError
        fields = self._session_fields.list_by_event(event.pk)
        existing = self._sessions.read_field_values(session_id)
        values_by_slug = {fv.field_slug: fv.value for fv in existing}
        return SessionSelfEditContext(
            session=session,
            event=event,
            session_fields=[(f, values_by_slug.get(f.slug)) for f in fields],
            facilitators=self._sessions.read_facilitators(session_id),
        )

    def update(
        self,
        session_id: int,
        user_id: int | None,
        cleaned_data: dict[str, object],
        field_values: list[SessionFieldValueData] | None,
    ) -> None:
        allowed, _session, event = self._gate(session_id, user_id)
        if not allowed or event is None:
            raise SessionEditNotAllowedError

        def _str(key: str) -> str:
            value = cleaned_data.get(key)
            return str(value) if value else ""

        def _int(key: str) -> int:
            value = cleaned_data.get(key)
            return value if isinstance(value, int) else 0

        update: SessionUpdateData = {
            "title": _str("title"),
            "display_name": _str("display_name"),
            "description": _str("description"),
            "requirements": _str("requirements"),
            "needs": _str("needs"),
            "contact_email": _str("contact_email"),
            "participants_limit": _int("participants_limit"),
            "min_age": _int("min_age"),
            "duration": _str("duration"),
        }
        if (cover := resolve_cover_image(cleaned_data.get("cover_image"))) is not None:
            update["cover_image"] = cover
        self._content_edit.apply(
            session_id=session_id,
            event_id=event.pk,
            user_id=user_id,
            data=SessionContentEditData(update=update, field_values=field_values),
        )


class IntegrationImplementationNotFoundError(Exception):
    """Raised when the registry has no implementation for an identifier."""


class EventIntegrationsService(EventIntegrationsServiceProtocol):
    """CRUD + check dispatch for per-event integrations.

    The registry of `IntegrationImplementation`s is composition-time data
    passed in from `inits/`; the mill never imports a concrete impl.
    """

    def __init__(
        self,
        transaction: TransactionProtocol,
        integrations: EventIntegrationsRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        registry: dict[IntegrationImplementationId, IntegrationImplementation],
    ) -> None:
        self._transaction = transaction
        self._integrations = integrations
        self._connections = connections
        self._decryptor = decryptor
        self._registry = registry

    def list_implementations(
        self, kind: IntegrationKind
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return {
            impl_id: impl
            for impl_id, impl in self._registry.items()
            if impl.kind == kind
        }

    def list_all_implementations(
        self,
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return dict(self._registry)

    def list_for_event(
        self, event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]:
        return self._integrations.list_for_event(event_id, kind)

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        return self._integrations.get(event_id, pk)

    def create(
        self, sphere_id: int, event_id: int, data: EventIntegrationCreateData
    ) -> EventIntegrationDTO:
        self._require_implementation(data["implementation"], data["kind"])
        # Raises NotFoundError if the connection isn't in this sphere.
        self._connections.get(sphere_id, data["connection_id"])
        with self._transaction.atomic():
            return self._integrations.create(event_id, data)

    def update(
        self, sphere_id: int, event_id: int, pk: int, data: EventIntegrationUpdateData
    ) -> EventIntegrationDTO:
        self._connections.get(sphere_id, data["connection_id"])
        with self._transaction.atomic():
            return self._integrations.update(event_id, pk, data)

    def delete(self, event_id: int, pk: int) -> None:
        with self._transaction.atomic():
            self._integrations.delete(event_id, pk)

    def fetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_questions(
            secret=plaintext,
            config=config,
            header_row=settings.header_row,
            email_column=settings.email_column,
        )

    def get_cached_questions(self, event_id: int, pk: int) -> list[SourceQuestion]:
        integration = self._integrations.get(event_id, pk)
        raw = integration.questions_snapshot_json or "[]"
        try:
            return _SOURCE_QUESTIONS_ADAPTER.validate_json(raw)
        except ValidationError:
            return []

    def populate_questions_snapshot(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        # Transparent first-load cache fill: live-fetches and writes the
        # snapshot, but leaves `settings.questions` (including confirmed
        # flags) untouched. Use `refetch_questions` for the operator-driven
        # action that also resets confirmations.
        questions = self.fetch_questions(sphere_id=sphere_id, event_id=event_id, pk=pk)
        snapshot = _SOURCE_QUESTIONS_ADAPTER.dump_json(questions).decode()
        with self._transaction.atomic():
            self._integrations.update_questions_snapshot(
                event_id=event_id, pk=pk, questions_snapshot_json=snapshot
            )
        return questions

    def refetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        # Per shape: regenerate question entries against the freshly fetched
        # form, drop every `confirmed` flag, preserve definitions untouched.
        # Questions that no longer exist in the form are dropped from
        # `settings.questions`; new ones land as missing entries (rendered
        # as unconfirmed by the summary).
        questions = self.populate_questions_snapshot(
            sphere_id=sphere_id, event_id=event_id, pk=pk
        )
        integration = self._integrations.get(event_id, pk)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        seen = {q.title for q in questions}
        rebuilt: dict[str, QuestionTarget] = {}
        for title, target in settings.questions.items():
            if title in seen:
                target.confirmed = False
                rebuilt[title] = target
        settings.questions = rebuilt
        with self._transaction.atomic():
            self._integrations.update_settings(
                event_id=event_id, pk=pk, settings_json=settings.model_dump_json()
            )
        return questions

    def import_missing_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> tuple[list[SourceQuestion], int]:
        # Refresh the snapshot but leave settings.questions untouched: existing
        # mappings (and their confirmations) survive, questions that disappeared
        # from the form stay in settings until the operator explicitly refetches.
        # Returns the fresh snapshot plus the count of questions that were not
        # yet present in settings.questions.
        integration = self._integrations.get(event_id, pk)
        before = ImportSettings.model_validate_json(integration.settings_json or "{}")
        questions = self.populate_questions_snapshot(
            sphere_id=sphere_id, event_id=event_id, pk=pk
        )
        missing = sum(1 for q in questions if q.title not in before.questions)
        return questions, missing

    def fetch_responses(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[ImportRow]:
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_responses(
            secret=plaintext, config=config, header_row=settings.header_row
        )

    def save_settings(self, *, event_id: int, pk: int, settings_json: str) -> None:
        with self._transaction.atomic():
            self._integrations.update_settings(
                event_id=event_id, pk=pk, settings_json=settings_json
            )

    def check(self, request: IntegrationCheckRequest) -> CheckResult:
        if (impl := self._registry.get(request.implementation)) is None:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND,
                hint=f"Unknown implementation: {request.implementation}",
            )
        try:
            config = impl.config_model.model_validate_json(request.config_json)
        except ValidationError as exc:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint=f"Invalid config: {exc}"
            )
        try:
            blob = self._connections.read_secret(
                request.sphere_id, request.connection_id
            )
        except NotFoundError:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint="Connection not found."
            )
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.check(plaintext, config)

    def _require_implementation(
        self, identifier: IntegrationImplementationId, kind: IntegrationKind
    ) -> None:
        impl = self._registry.get(identifier)
        if impl is None or impl.kind != kind:
            raise IntegrationImplementationNotFoundError(identifier)
