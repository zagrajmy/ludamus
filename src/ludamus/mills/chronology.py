"""Chronology subdomain business logic.

Currently spans the Timetable (agenda scheduling) and CFP (personal-data
field management) bounded contexts. Split per `plans/hex_refactor.md` if
the file grows past ~12 top-level members or 1000 lines.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts import (
    EventDTO,
    FieldUsageSummary,
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    SessionDTO,
    SessionSelfEditContext,
    SessionStatus,
)
from ludamus.pacts.chronology import (
    TIMETABLE_ROOM_PAGE_SIZE,
    TIMETABLE_SLOT_MINUTES,
    AreaGroupDTO,
    CheckOutcome,
    CheckResult,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    EventIntegrationCreateData,
    EventIntegrationDTO,
    EventIntegrationsRepositoryProtocol,
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
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    PreferredSlotRangeDTO,
    PreferredSlotViolationDTO,
    SessionPlacement,
    SessionPositionDTO,
    SpaceColumnDTO,
    TimeLabelDTO,
    TimetableGridDTO,
    TrackProgressDTO,
    VenueGroupDTO,
)
from ludamus.specs.chronology import resolve_facilitator_session_edit
from ludamus.specs.proposal import SESSION_CONTENT_FIELD_LABELS

if TYPE_CHECKING:
    from ludamus.pacts import (
        AgendaItemDTO,
        AreaDTO,
        ContentChangeLogData,
        ContentChangeLogDTO,
        ContentChangeLogRepositoryProtocol,
        ContentFieldChange,
        ContentFieldValue,
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryRepositoryProtocol,
        SessionFieldDTO,
        SessionFieldRepositoryProtocol,
        SessionFieldValueData,
        SessionFieldValueDTO,
        SessionRepositoryProtocol,
        SessionUpdateData,
        SpaceDTO,
        SphereRepositoryProtocol,
        UnitOfWorkProtocol,
    )
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


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
        all_spaces = self._uow.spaces.list_by_event(event_pk)
        if track_pk is not None:
            track_space_pks = set(self._uow.tracks.list_space_pks(track_pk))
            all_spaces = [s for s in all_spaces if s.pk in track_space_pks]

        total_spaces = len(all_spaces)
        total_pages = max(1, math.ceil(total_spaces / TIMETABLE_ROOM_PAGE_SIZE))
        space_page = max(1, min(space_page, total_pages))
        start = (space_page - 1) * TIMETABLE_ROOM_PAGE_SIZE
        spaces = all_spaces[start : start + TIMETABLE_ROOM_PAGE_SIZE]

        all_slots = self._uow.time_slots.list_by_event(event_pk)
        windows_by_date = slot_windows_by_local_date(all_slots, tz)
        available_dates = sorted(windows_by_date.keys())

        if selected_date is None or selected_date not in windows_by_date:
            selected_date = available_dates[0] if available_dates else None

        venue_groups = self._build_venue_groups(event_pk, spaces)

        if selected_date is None:
            return TimetableGridDTO(
                spaces=spaces,
                columns=[SpaceColumnDTO(space=s, sessions=[]) for s in spaces],
                venue_groups=venue_groups,
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
            venue_groups=venue_groups,
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

    def _build_venue_groups(
        self, event_pk: int, spaces: list[SpaceDTO]
    ) -> list[VenueGroupDTO]:
        if not (area_ids := [s.area_id for s in spaces if s.area_id is not None]):
            return []

        venues_by_pk = {v.pk: v for v in self._uow.venues.list_by_event(event_pk)}
        areas_by_pk: dict[int, AreaDTO] = {
            area.pk: area
            for venue_pk in venues_by_pk
            for area in self._uow.areas.list_by_venue(venue_pk)
        }

        venue_groups: list[VenueGroupDTO] = []
        for area_id in area_ids:
            area = areas_by_pk[area_id]
            venue_pk = area.venue_id
            if not venue_groups or venue_groups[-1].venue_pk != venue_pk:
                venue_groups.append(
                    VenueGroupDTO(
                        venue_pk=venue_pk,
                        venue_name=venues_by_pk[venue_pk].name,
                        span=0,
                        areas=[],
                    )
                )
            current_venue = venue_groups[-1]
            current_venue.span += 1
            if not current_venue.areas or current_venue.areas[-1].area_pk != area_id:
                current_venue.areas.append(
                    AreaGroupDTO(area_pk=area_id, area_name=area.name, span=0)
                )
            current_venue.areas[-1].span += 1
        return venue_groups

    def _require_session_in_event(self, session_pk: int, event_pk: int) -> None:
        # Panel access only proves you manage `event_pk`; a session named in
        # the request must belong to it, or it is cross-event tampering.
        if self._uow.sessions.read_event(session_pk).pk != event_pk:
            raise NotFoundError

    def _require_space_in_event(self, space_pk: int, event_pk: int) -> None:
        if space_pk not in {s.pk for s in self._uow.spaces.list_by_event(event_pk)}:
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
        self._require_session_in_event(session_pk, event_pk)
        self._require_space_in_event(placement.space_pk, event_pk)
        self._clear_existing_assignment(session_pk, event_pk, user_pk)
        session = self._uow.sessions.read(session_pk)
        if session.status != SessionStatus.PENDING:
            msg = f"Session {session_pk} is not in PENDING status"
            raise ValueError(msg)
        self._uow.agenda_items.create(
            {
                "session_id": session_pk,
                "space_id": placement.space_pk,
                "start_time": placement.start_time,
                "end_time": placement.end_time,
                "session_confirmed": False,
            }
        )
        self._uow.sessions.update(session_pk, {"status": SessionStatus.SCHEDULED})
        event = self._uow.sessions.read_event(session_pk)
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
        if log.action == ScheduleChangeAction.ASSIGN:
            agenda_item = self._uow.agenda_items.read_by_session(log.session_id)
            if agenda_item is None:
                raise NotFoundError
            self._uow.agenda_items.delete(agenda_item.pk)
            self._uow.sessions.update(log.session_id, {"status": SessionStatus.PENDING})
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


class CFPPersonalDataFieldService:
    """Backoffice operations for an event's personal-data fields."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        fields: PersonalDataFieldRepositoryProtocol,
        categories: ProposalCategoryRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._fields = fields
        self._categories = categories

    def list_summaries(self, event_pk: int) -> list[FieldUsageSummary]:
        fields = self._fields.list_by_event(event_pk)
        usage_counts = self._fields.get_usage_counts(event_pk)
        return [
            FieldUsageSummary(
                field=f,
                required_count=usage_counts.get(f.pk, {}).get("required", 0),
                optional_count=usage_counts.get(f.pk, {}).get("optional", 0),
            )
            for f in fields
        ]

    def get_create_form_context(self, event_pk: int) -> PersonalDataFieldFormContextDTO:
        return PersonalDataFieldFormContextDTO(
            categories=self._categories.list_by_event(event_pk)
        )

    def get_edit_form_context(
        self, event_pk: int, field_slug: str
    ) -> PersonalDataFieldEditContextDTO:
        field = self._fields.read_by_slug(event_pk, field_slug)
        categories = self._categories.list_by_event(event_pk)
        field_cats = self._categories.get_personal_field_categories(field.pk)
        return PersonalDataFieldEditContextDTO(
            field=field,
            categories=categories,
            required_category_pks={pk for pk, req in field_cats.items() if req},
            optional_category_pks={pk for pk, req in field_cats.items() if not req},
        )

    def _scope_to_event(
        self, event_pk: int, category_requirements: dict[int, bool]
    ) -> dict[int, bool]:
        # Drop category pks that belong to another event so a tampered
        # request cannot link this field to a foreign event's categories.
        valid_pks = {c.pk for c in self._categories.list_by_event(event_pk)}
        return {pk: req for pk, req in category_requirements.items() if pk in valid_pks}

    def create(
        self,
        event_pk: int,
        data: PersonalDataFieldCreateData,
        category_requirements: dict[int, bool],
    ) -> PersonalDataFieldDTO:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if scoped := self._scope_to_event(event_pk, category_requirements):
                self._categories.add_field_to_categories(field.pk, scoped)
        return field

    def update(
        self,
        event_pk: int,
        field_slug: str,
        data: PersonalDataFieldUpdateData,
        category_requirements: dict[int, bool],
    ) -> None:
        field = self._fields.read_by_slug(event_pk, field_slug)
        scoped = self._scope_to_event(event_pk, category_requirements)
        with self._transaction.atomic():
            self._fields.update(field.pk, data)
            self._categories.set_personal_field_categories(field.pk, scoped)

    def delete(self, event_pk: int, field_slug: str) -> bool:
        # Returns False when the field is in use by session types.
        # NotFoundError on bad slug surfaces to the caller for distinct messaging.
        field = self._fields.read_by_slug(event_pk, field_slug)
        if self._fields.has_requirements(field.pk):
            return False
        self._fields.delete(field.pk)
        return True


class SessionEditNotAllowedError(Exception):
    """Raised when a user may not self-edit the requested session."""


def _normalize(value: ContentFieldValue) -> ContentFieldValue:
    return "" if value is None else value


def _diff_cover_image(
    old_url: str, new_value: object, label: str
) -> ContentFieldChange | None:
    # new_value is "" when the cover was cleared, or a file object on upload.
    if not new_value:
        if old_url:
            return {"field": "cover_image", "label": label, "old": old_url, "new": ""}
        return None
    return {"field": "cover_image", "label": label, "old": old_url, "new": "(updated)"}


def _diff_field_values(
    old_values: list[SessionFieldValueDTO],
    new_values: list[SessionFieldValueData],
    fields: list[SessionFieldDTO],
) -> list[ContentFieldChange]:
    slug_by_id = {f.pk: f.slug for f in fields}
    label_by_id = {f.pk: f.name for f in fields}
    old_by_id = {v.field_id: v.value for v in old_values}
    changes: list[ContentFieldChange] = []
    for new in new_values:
        field_id = new["field_id"]
        old_value = old_by_id.get(field_id)
        new_value = new["value"]
        if _normalize(old_value) == _normalize(new_value):
            continue
        changes.append(
            {
                "field": slug_by_id.get(field_id, str(field_id)),
                "label": label_by_id.get(field_id, ""),
                "old": old_value,
                "new": new_value,
            }
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
    fields: list[SessionFieldDTO],
) -> list[ContentFieldChange]:
    # Field-by-field diff of a session edit, as a flat list of changes: core
    # session columns plus dynamic session-field answers. Pure — mirrors
    # exactly what the edit persists.
    changes: list[ContentFieldChange] = [
        {
            "field": key,
            "label": SESSION_CONTENT_FIELD_LABELS[key],
            "old": old_value,
            "new": new_value,
        }
        for key, old_value, new_value in _core_comparisons(old_session, update)
        if old_value != new_value
    ]
    if "cover_image" in update:
        cover_change = _diff_cover_image(
            old_session.cover_image_url,
            update["cover_image"],
            SESSION_CONTENT_FIELD_LABELS["cover_image"],
        )
        if cover_change is not None:
            changes.append(cover_change)
    changes.extend(_diff_field_values(old_values, new_values, fields))
    return changes


class SessionContentEditService:
    """Persist a session content edit and record it in the audit log.

    Shared by the facilitator self-edit and the organizer panel edit so both
    paths write the same `ContentChangeLog`. Owns the transactional boundary.
    """

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
        update: SessionUpdateData,
        field_values: list[SessionFieldValueData],
    ) -> None:
        with self._transaction.atomic():
            old_session = self._sessions.read(session_id)
            old_values = self._sessions.read_field_values(session_id)
            fields = self._session_fields.list_by_event(event_id)
            self._sessions.update(session_id, update)
            if field_values:
                self._sessions.save_field_values(session_id, field_values)
            changes = diff_session_content(
                old_session, update, old_values, field_values, fields
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
        field_values: list[SessionFieldValueData],
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
        # ClearableFileInput yields a file on upload, False when cleared, or the
        # unchanged value otherwise. Only set the key when it actually changes so
        # the repository keeps the current cover untouched.
        if cover_image := cleaned_data.get("cover_image"):
            update["cover_image"] = cover_image
        elif cover_image is False:
            update["cover_image"] = ""
        self._content_edit.apply(
            session_id=session_id,
            event_id=event.pk,
            user_id=user_id,
            update=update,
            field_values=field_values,
        )


class IntegrationImplementationNotFoundError(Exception):
    """Raised when the registry has no implementation for an identifier."""


class EventIntegrationsService:
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
