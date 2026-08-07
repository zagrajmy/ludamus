from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from math import ceil
from operator import itemgetter
from typing import TYPE_CHECKING

from django.utils.timezone import get_current_timezone

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
    windows: dict[int, SlotWindow] = field(default_factory=dict)


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


def build_schedule_days(
    sessions_data: dict[int, SessionData], *, tz: tzinfo | None = None
) -> list[ScheduleDay]:
    zone = get_current_timezone() if tz is None else tz
    by_hour: dict[datetime, list[tuple[datetime, SessionData, SlotWindow, int]]] = (
        defaultdict(list)
    )
    for data in sessions_data.values():
        if (item := data.agenda_item) is None:
            continue
        for window in interval_windows(
            start=item.start_time, end=item.end_time, tz=zone
        ):
            hour = window[0].replace(minute=0, second=0, microsecond=0)
            by_hour[hour].append((item.start_time, data, window, item.pk))

    days: list[ScheduleDay] = []
    for hour in sorted(by_hour):
        entries = sorted(by_hour[hour], key=itemgetter(0))
        if not days or days[-1].first_start.date() != hour.date():
            days.append(ScheduleDay(first_start=hour, hours=[]))
        day = days[-1]
        day.windows.update((pk, window) for _, _, window, pk in entries)
        day.hours.append(
            ScheduleHour(start=hour, sessions=[data for _, data, _, _ in entries])
        )
    return days


def group_sessions_by_state(
    sessions_data: dict[int, SessionData],
) -> tuple[
    dict[datetime, list[SessionData]],
    dict[datetime, list[SessionData]],
    dict[datetime, list[SessionData]],
]:
    now = datetime.now(tz=UTC)
    ended: dict[datetime, list[SessionData]] = defaultdict(list)
    current: dict[datetime, list[SessionData]] = defaultdict(list)
    future_unavailable: dict[datetime, list[SessionData]] = defaultdict(list)
    for data in sessions_data.values():
        if data.agenda_item is None:
            continue
        start = data.agenda_item.start_time
        if data.agenda_item.end_time <= now:
            ended[start].append(data)
        elif not data.is_enrollment_available and start > now:
            future_unavailable[start].append(data)
        else:
            current[start].append(data)
    return dict(ended), dict(current), dict(future_unavailable)


def _room_key(data: SessionData) -> tuple[str, str, str]:
    return data.loc["space_name"], data.loc["parent_slug"], data.loc["parent_name"]


def build_room_lanes(schedule_days: list[ScheduleDay]) -> list[RoomLaneDay]:
    lane_days: list[RoomLaneDay] = []
    for day in schedule_days:
        keys = sorted({_room_key(data) for hour in day.hours for data in hour.sessions})
        name_counts = Counter(name for name, _, _ in keys)
        rooms = [
            f"{name} ({parent})" if name_counts[name] > 1 and parent else name
            for name, _, parent in keys
        ]
        col_index = {key: index + 1 for index, key in enumerate(keys)}
        day_start = day.hours[0].start
        session_hours = {hour.start for hour in day.hours}
        tiles: list[RoomLaneTile] = []
        day_end = day_start
        for hour in day.hours:
            for data in hour.sessions:
                if data.agenda_item is None:
                    continue
                visible_start, visible_end = day.windows[data.agenda_item.pk]
                day_end = max(day_end, visible_end)
                start_hour = int((visible_start - day_start).total_seconds() // 3600)
                span = max(
                    1,
                    ceil((visible_end - day_start).total_seconds() / 3600) - start_hour,
                )
                tiles.append(
                    RoomLaneTile(
                        data=data,
                        slot_hour=hour.start,
                        col=col_index[_room_key(data)],
                        row_start=start_hour + 1,
                        row_span=span,
                    )
                )
        marks = [
            RoomLaneHourMark(
                start=(mark := day_start + timedelta(hours=offset)),
                row=offset + 1,
                has_sessions=mark in session_hours,
            )
            for offset in range(ceil((day_end - day_start).total_seconds() / 3600))
        ]
        lane_days.append(
            RoomLaneDay(
                first_start=day.first_start, rooms=rooms, hour_marks=marks, tiles=tiles
            )
        )
    return lane_days
