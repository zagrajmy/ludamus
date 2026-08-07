from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from math import ceil
from operator import itemgetter
from typing import TYPE_CHECKING

from ludamus.mills.timeslots import SlotWindow, interval_windows

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


def _window_on_date(
    *, start: datetime, end: datetime, tz: tzinfo, day: date
) -> SlotWindow:
    for window in interval_windows(start=start, end=end, tz=tz):
        if window[0].date() == day:
            return window
    msg = f"interval {start}..{end} has no window on {day}"
    raise ValueError(msg)


def build_schedule_days(
    sessions_data: dict[int, SessionData], *, tz: tzinfo
) -> list[ScheduleDay]:
    by_hour: dict[datetime, list[tuple[datetime, SessionData]]] = defaultdict(list)
    for data in sessions_data.values():
        if data.agenda_item is None:
            continue
        item = data.agenda_item
        for window_start, _window_end in interval_windows(
            start=item.start_time, end=item.end_time, tz=tz
        ):
            hour_start = window_start.replace(minute=0, second=0, microsecond=0)
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


def build_room_lanes(
    schedule_days: list[ScheduleDay], *, tz: tzinfo
) -> list[RoomLaneDay]:
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
        day_date = day_start.date()
        session_hours = {hour.start for hour in day.hours}
        tiles: list[RoomLaneTile] = []
        day_end = day_start
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
                visible_start, visible_end = _window_on_date(
                    start=item.start_time, end=item.end_time, tz=tz, day=day_date
                )
                day_end = max(day_end, visible_end)
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

        hour_count = ceil((day_end - day_start).total_seconds() / 3600)
        hour_marks = [
            RoomLaneHourMark(
                start=(mark := day_start + timedelta(hours=offset)),
                row=offset + 1,
                has_sessions=mark in session_hours,
            )
            for offset in range(hour_count)
        ]
        lane_days.append(
            RoomLaneDay(
                first_start=day.first_start,
                rooms=rooms,
                hour_marks=hour_marks,
                tiles=tiles,
            )
        )
    return lane_days
