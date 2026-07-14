from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from ludamus.gates.web.django.chronology.event_presentation import SessionData


@dataclass
class ScheduleHour:
    start: datetime
    sessions: list[SessionData]


@dataclass
class ScheduleDay:
    first_start: datetime
    hours: list[ScheduleHour]


@dataclass
class RoomLaneTile:
    data: SessionData
    slot_hour: datetime
    col: int
    row_start: int
    row_span: int


@dataclass
class RoomLaneHourMark:
    start: datetime
    row: int
    has_sessions: bool


@dataclass
class RoomLaneDay:
    first_start: datetime
    rooms: list[str]
    hour_marks: list[RoomLaneHourMark]
    tiles: list[RoomLaneTile]


def build_schedule_days(sessions_data: dict[int, SessionData]) -> list[ScheduleDay]:
    days: list[ScheduleDay] = []
    for data in sessions_data.values():
        if data.agenda_item is None:
            continue
        start = data.agenda_item.start_time
        local_start = timezone.localtime(start)
        if not days or timezone.localtime(days[-1].first_start).date() != (
            local_start.date()
        ):
            days.append(ScheduleDay(first_start=start, hours=[]))
        hours = days[-1].hours
        hour_start = local_start.replace(minute=0, second=0, microsecond=0)
        if not hours or hours[-1].start != hour_start:
            hours.append(ScheduleHour(start=hour_start, sessions=[]))
        hours[-1].sessions.append(data)
    return days


def group_sessions_by_state(
    sessions_data: dict[int, SessionData],
) -> tuple[
    dict[datetime, list[SessionData]],
    dict[datetime, list[SessionData]],
    dict[datetime, list[SessionData]],
]:
    current_time = datetime.now(tz=UTC)
    ended: dict[datetime, list[SessionData]] = defaultdict(list)
    current: dict[datetime, list[SessionData]] = defaultdict(list)
    future_unavailable: dict[datetime, list[SessionData]] = defaultdict(list)
    for session_data in sessions_data.values():
        if session_data.agenda_item is None:
            continue
        session_start_time = session_data.agenda_item.start_time
        if session_data.agenda_item.end_time <= current_time:
            ended[session_start_time].append(session_data)
        elif (
            not session_data.is_enrollment_available
            and session_start_time > current_time
        ):
            future_unavailable[session_start_time].append(session_data)
        else:
            current[session_start_time].append(session_data)
    return dict(ended), dict(current), dict(future_unavailable)


def build_room_lanes(schedule_days: list[ScheduleDay]) -> list[RoomLaneDay]:
    lane_days: list[RoomLaneDay] = []
    for day in schedule_days:
        keys = sorted(
            {
                (
                    data.loc["space_name"],
                    data.loc["parent_slug"],
                    data.loc["parent_name"],
                )
                for hour in day.hours
                for data in hour.sessions
            }
        )
        name_counts = Counter(name for name, _, _ in keys)
        rooms = [
            f"{name} ({parent})" if name_counts[name] > 1 and parent else name
            for name, _, parent in keys
        ]
        col_index = {key: index + 1 for index, key in enumerate(keys)}

        day_start = day.hours[0].start
        day_end = max(
            data.agenda_item.end_time
            for hour in day.hours
            for data in hour.sessions
            if data.agenda_item is not None
        )
        hour_count = ceil((day_end - day_start).total_seconds() / 3600)
        session_hours = {hour.start for hour in day.hours}
        hour_marks = [
            RoomLaneHourMark(
                start=(mark := day_start + timedelta(hours=offset)),
                row=offset + 1,
                has_sessions=mark in session_hours,
            )
            for offset in range(hour_count)
        ]

        tiles = []
        for hour in day.hours:
            for data in hour.sessions:
                if data.agenda_item is None:
                    continue
                item = data.agenda_item
                key = (
                    data.loc["space_name"],
                    data.loc["parent_slug"],
                    data.loc["parent_name"],
                )
                start_hour = int((item.start_time - day_start).total_seconds() // 3600)
                end_offset = (item.end_time - day_start).total_seconds() / 3600
                span = max(1, ceil(end_offset) - start_hour)
                tiles.append(
                    RoomLaneTile(
                        data=data,
                        slot_hour=hour.start,
                        col=col_index[key],
                        row_start=start_hour + 1,
                        row_span=span,
                    )
                )
        lane_days.append(
            RoomLaneDay(
                first_start=day.first_start,
                rooms=rooms,
                hour_marks=hour_marks,
                tiles=tiles,
            )
        )
    return lane_days
