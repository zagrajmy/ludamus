from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import TYPE_CHECKING, NamedTuple

from django.utils import timezone

from ludamus.mills.timeslots import interval_windows

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
class RoomLane:
    # One room column. `group` is the parent space it hangs under, printed once
    # above the first column of the run (`starts_group`) so the header reads as
    # the space tree rather than a flat row of room names. `group_key` is that
    # parent's identity, which the client needs to reprint the label when
    # filtering collapses the column that carried it.
    name: str
    group: str
    group_key: str
    starts_group: bool


@dataclass
class RoomLaneDay:
    day_start: datetime
    rooms: list[RoomLane]
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
        for window_start, window_end in interval_windows(
            start=item.start_time, end=item.end_time, tz=tz
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
        elif data.availability == "unavailable" and start > now:
            future_unavailable[start].append(data)
        else:
            current[start].append(data)
    return dict(ended), dict(current), dict(future_unavailable)


class _RoomKey(NamedTuple):
    # sort_key first, and alone enough to order the columns: it carries the
    # whole ancestor chain's panel ordering, so sorting on it lays the columns
    # out in tree order and puts every room of a parent space side by side. The
    # rest of the fields ride along as labels.
    sort_key: str
    parent_key: str
    name: str
    parent_name: str


def _room_key(data: SessionData) -> _RoomKey:
    sort_key = data.loc["sort_key"]
    return _RoomKey(
        sort_key=sort_key,
        # The parent's identity, not its name: Space enforces slug uniqueness
        # only per parent, so two branches can carry the same parent name and
        # must not merge into one header run. The chain minus the space's own
        # three segments is exactly the parent's key, and "" at the root.
        parent_key="|".join(sort_key.split("|")[:-3]),
        name=data.loc["space_name"],
        parent_name=data.loc["parent_name"],
    )


def _room_lanes(keys: list[_RoomKey]) -> list[RoomLane]:
    lanes: list[RoomLane] = []
    # None, not "": a root-level room's parent key is "", and that run still
    # opens a group of its own rather than continuing the previous parent's.
    previous_group: str | None = None
    for key in keys:
        lanes.append(
            RoomLane(
                name=key.name,
                group=key.parent_name,
                group_key=key.parent_key,
                starts_group=key.parent_key != previous_group,
            )
        )
        previous_group = key.parent_key
    return lanes


def build_room_lanes(schedule_days: list[ScheduleDay]) -> list[RoomLaneDay]:
    lane_days: list[RoomLaneDay] = []
    for day in schedule_days:
        keys = sorted({_room_key(tile.data) for tile in day.tiles})
        rooms = _room_lanes(keys)
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

        tiles: list[RoomLaneTile] = []
        for tile in day.tiles:
            start_hour = int((tile.start - day_start).total_seconds() // 3600)
            end_offset = (tile.end - day_start).total_seconds() / 3600
            tiles.append(
                RoomLaneTile(
                    data=tile.data,
                    slot_hour=tile.start.replace(minute=0, second=0, microsecond=0),
                    col=col_index[_room_key(tile.data)],
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
