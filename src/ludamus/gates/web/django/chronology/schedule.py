from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import TYPE_CHECKING

from django.utils import timezone

from ludamus.mills.timeslots import local_day_windows

if TYPE_CHECKING:
    from ludamus.gates.web.django.chronology.event_presentation import SessionData


@dataclass
class ScheduleHour:
    start: datetime
    sessions: list[SessionData]


@dataclass
class ScheduleTile:
    # One session as it appears on one local date, already clipped to it. Night
    # program belongs to both sides of midnight, so a session crossing it makes
    # two tiles; every consumer reads the clipped window instead of redoing it.
    data: SessionData
    start: datetime
    end: datetime


@dataclass
class ScheduleDay:
    day_start: datetime
    hours: list[ScheduleHour]
    tiles: list[ScheduleTile]


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
    day_start: datetime
    rooms: list[str]
    hour_marks: list[RoomLaneHourMark]
    tiles: list[RoomLaneTile]


def build_schedule_days(sessions_data: dict[int, SessionData]) -> list[ScheduleDay]:
    tz = timezone.get_current_timezone()
    # Sorted once, on the pair: the item carries the sort key and the narrowing
    # to a scheduled item, so nothing downstream re-sorts or re-checks for None.
    scheduled = sorted(
        (
            (data.agenda_item, data)
            for data in sessions_data.values()
            if data.agenda_item is not None
        ),
        key=lambda pair: pair[0].start_time,
    )
    tiles_by_date: dict[date, list[ScheduleTile]] = defaultdict(list)
    for item, data in scheduled:
        for window_start, window_end in local_day_windows(
            item.start_time, item.end_time, tz
        ):
            tiles_by_date[window_start.date()].append(
                ScheduleTile(data=data, start=window_start, end=window_end)
            )

    days: list[ScheduleDay] = []
    for day in sorted(tiles_by_date):
        tiles = tiles_by_date[day]
        by_hour: dict[datetime, list[SessionData]] = defaultdict(list)
        for tile in tiles:
            by_hour[tile.start.replace(minute=0, second=0, microsecond=0)].append(
                tile.data
            )
        hours = [
            ScheduleHour(start=start, sessions=by_hour[start])
            for start in sorted(by_hour)
        ]
        days.append(ScheduleDay(day_start=hours[0].start, hours=hours, tiles=tiles))
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
                    tile.data.loc["space_name"],
                    tile.data.loc["parent_slug"],
                    tile.data.loc["parent_name"],
                )
                for tile in day.tiles
            }
        )
        name_counts = Counter(name for name, _, _ in keys)
        rooms = [
            f"{name} ({parent})" if name_counts[name] > 1 and parent else name
            for name, _, parent in keys
        ]
        col_index = {key: index + 1 for index, key in enumerate(keys)}

        day_start = day.day_start
        day_end = max(tile.end for tile in day.tiles)
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
        for tile in day.tiles:
            key = (
                tile.data.loc["space_name"],
                tile.data.loc["parent_slug"],
                tile.data.loc["parent_name"],
            )
            start_hour = int((tile.start - day_start).total_seconds() // 3600)
            end_offset = (tile.end - day_start).total_seconds() / 3600
            tiles.append(
                RoomLaneTile(
                    data=tile.data,
                    slot_hour=tile.start.replace(minute=0, second=0, microsecond=0),
                    col=col_index[key],
                    row_start=start_hour + 1,
                    row_span=max(1, ceil(end_offset) - start_hour),
                )
            )
        lane_days.append(
            RoomLaneDay(
                day_start=day_start, rooms=rooms, hour_marks=hour_marks, tiles=tiles
            )
        )
    return lane_days
