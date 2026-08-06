from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from operator import itemgetter
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


def _next_local_midnight(moment: datetime) -> datetime:
    return timezone.localtime(moment + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _local_day_segments(start: datetime, end: datetime) -> list[datetime]:
    # Where the session starts on each local date it covers: its own start on
    # the first date, midnight on every later one. Night program belongs to
    # both sides of midnight, so it shows up on both days.
    local_start = timezone.localtime(start)
    local_end = timezone.localtime(end)
    segments = [local_start]
    midnight = _next_local_midnight(local_start)
    while midnight < local_end:
        segments.append(midnight)
        midnight = _next_local_midnight(midnight)
    return segments


def build_schedule_days(sessions_data: dict[int, SessionData]) -> list[ScheduleDay]:
    by_hour: dict[datetime, list[tuple[datetime, SessionData]]] = defaultdict(list)
    for data in sessions_data.values():
        if data.agenda_item is None:
            continue
        item = data.agenda_item
        for segment_start in _local_day_segments(item.start_time, item.end_time):
            hour_start = segment_start.replace(minute=0, second=0, microsecond=0)
            by_hour[hour_start].append((item.start_time, data))

    days: list[ScheduleDay] = []
    for hour_start in sorted(by_hour):
        sessions = [data for _, data in sorted(by_hour[hour_start], key=itemgetter(0))]
        if not days or days[-1].first_start.date() != hour_start.date():
            days.append(ScheduleDay(first_start=hour_start, hours=[]))
        days[-1].hours.append(ScheduleHour(start=hour_start, sessions=sessions))
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
        # The day's lanes stop at midnight; the rest of a night session is
        # drawn again on the day it runs into.
        day_limit = _next_local_midnight(day_start)
        day_end = min(
            day_limit,
            max(
                data.agenda_item.end_time
                for hour in day.hours
                for data in hour.sessions
                if data.agenda_item is not None
            ),
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
                visible_start = max(item.start_time, day_start)
                visible_end = min(item.end_time, day_limit)
                start_hour = int((visible_start - day_start).total_seconds() // 3600)
                end_offset = (visible_end - day_start).total_seconds() / 3600
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
