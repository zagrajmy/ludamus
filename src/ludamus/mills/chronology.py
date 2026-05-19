"""Chronology subdomain business logic.

Currently spans the Timetable (agenda scheduling) and CFP (personal-data
field management) bounded contexts. Split per `plans/hex_refactor.md` if
the file grows past ~12 top-level members or 1000 lines.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from ludamus.pacts import (
    FieldUsageSummary,
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    SessionStatus,
)
from ludamus.pacts.chronology import (
    TIMETABLE_ROOM_PAGE_SIZE,
    TIMETABLE_SLOT_MINUTES,
    AreaGroupDTO,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    HeatmapCellDTO,
    HeatmapCellStatus,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    PreferredSlotRangeDTO,
    PreferredSlotViolationDTO,
    SessionPositionDTO,
    SpaceColumnDTO,
    TimeLabelDTO,
    TimetableGridDTO,
    TrackProgressDTO,
    VenueGroupDTO,
)

if TYPE_CHECKING:
    from ludamus.pacts import (
        AgendaItemDTO,
        AreaDTO,
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryRepositoryProtocol,
        SpaceDTO,
        TimeSlotDTO,
        UnitOfWorkProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


def _slot_windows_by_local_date(
    slots: list[TimeSlotDTO], tz: tzinfo
) -> dict[date, list[tuple[datetime, datetime]]]:
    # A slot spanning multiple local dates contributes one (start, end) window
    # to each date it touches, clamped to that date's [00:00, 24:00) range.
    grouped: dict[date, list[tuple[datetime, datetime]]] = defaultdict(list)
    for slot in slots:
        local_start = slot.start_time.astimezone(tz)
        local_end = slot.end_time.astimezone(tz)
        days_span = (local_end.date() - local_start.date()).days + 1
        for offset in range(days_span):
            cursor_date = local_start.date() + timedelta(days=offset)
            day_start = datetime.combine(cursor_date, datetime.min.time(), tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            window_start = max(local_start, day_start)
            window_end = min(local_end, day_end)
            if window_start < window_end:
                grouped[cursor_date].append((window_start, window_end))
    return grouped


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
        windows_by_date = _slot_windows_by_local_date(all_slots, tz)
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

    def assign_session(
        self,
        *,
        event_pk: int,
        session_pk: int,
        space_pk: int,
        time_range: tuple[datetime, datetime],
        user_pk: int | None = None,
    ) -> None:
        start_time, end_time = time_range
        event = self._uow.sessions.read_event(session_pk)
        if event.pk != event_pk:
            raise NotFoundError
        if not any(
            space.pk == space_pk for space in self._uow.spaces.list_by_event(event_pk)
        ):
            raise NotFoundError
        session = self._uow.sessions.read(session_pk)
        if session.status != SessionStatus.PENDING:
            msg = f"Session {session_pk} is not in PENDING status"
            raise ValueError(msg)
        self._uow.agenda_items.create(
            {
                "session_id": session_pk,
                "space_id": space_pk,
                "start_time": start_time,
                "end_time": end_time,
                "session_confirmed": False,
            }
        )
        self._uow.sessions.update(session_pk, {"status": SessionStatus.SCHEDULED})
        log_data: ScheduleChangeLogData = {
            "event_id": event.pk,
            "session_id": session_pk,
            "user_id": user_pk,
            "action": ScheduleChangeAction.ASSIGN,
            "new_space_id": space_pk,
            "new_start_time": start_time,
            "new_end_time": end_time,
        }
        self._uow.schedule_change_logs.create(log_data)

    def unassign_session(
        self, event_pk: int, session_pk: int, user_pk: int | None = None
    ) -> None:
        event = self._uow.sessions.read_event(session_pk)
        if event.pk != event_pk:
            raise NotFoundError
        if (agenda_item := self._uow.agenda_items.read_by_session(session_pk)) is None:
            raise NotFoundError
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
        self, event_pk: int, log_pk: int, user_pk: int | None = None
    ) -> None:
        log = self._uow.schedule_change_logs.read(log_pk)
        if log.event_id != event_pk:
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
        revert_log: ScheduleChangeLogData = {
            "event_id": event_pk,
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
        self, session_pk: int, space_pk: int, start_time: datetime, end_time: datetime
    ) -> list[ConflictDTO]:
        conflicts: list[ConflictDTO] = []
        session = self._uow.sessions.read(session_pk)

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
                space_pk=item.space_id,
                start_time=item.start_time,
                end_time=item.end_time,
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

        windows_by_date = _slot_windows_by_local_date(
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

    def create(
        self,
        event_pk: int,
        data: PersonalDataFieldCreateData,
        category_requirements: dict[int, bool],
    ) -> PersonalDataFieldDTO:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if category_requirements:
                self._categories.add_field_to_categories(
                    field.pk, category_requirements
                )
        return field

    def update(
        self,
        event_pk: int,
        field_slug: str,
        data: PersonalDataFieldUpdateData,
        category_requirements: dict[int, bool],
    ) -> None:
        field = self._fields.read_by_slug(event_pk, field_slug)
        with self._transaction.atomic():
            self._fields.update(field.pk, data)
            self._categories.set_personal_field_categories(
                field.pk, category_requirements
            )

    def delete(self, event_pk: int, field_slug: str) -> bool:
        # Returns False when the field is in use by session types.
        # NotFoundError on bad slug surfaces to the caller for distinct messaging.
        field = self._fields.read_by_slug(event_pk, field_slug)
        if self._fields.has_requirements(field.pk):
            return False
        self._fields.delete(field.pk)
        return True
