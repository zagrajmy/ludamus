from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal, NamedTuple

from django.utils import timezone

from ludamus.mills.timeslots import interval_windows

if TYPE_CHECKING:
    from ludamus.gates.web.django.chronology.event_presentation import SessionData


def _instant_key(instant: datetime) -> str:
    return str(int(instant.timestamp()))


def _is_ambiguous_local_hour(hour: datetime) -> bool:
    if (tz := hour.tzinfo) is None:
        return False
    wall_hour = hour.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    candidates = [wall_hour.replace(tzinfo=tz, fold=fold) for fold in (0, 1)]
    return candidates[0].utcoffset() != candidates[1].utcoffset() and all(
        candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == wall_hour
        for candidate in candidates
    )


@dataclass
class ScheduleHour:
    start: datetime
    tiles: list[ScheduleTile]
    is_repeated: bool = False
    slot_key: str = field(default="", compare=False)


@dataclass
class ScheduleTile:
    # One session as it appears on one local date, already clipped to it. Night
    # program belongs to both sides of midnight, so a session crossing it makes
    # two tiles; every consumer reads the clipped window instead of redoing it.
    data: SessionData
    start: datetime
    end: datetime


def _day_panel_id(day_start: datetime) -> str:
    # The fold toggle names this in aria-controls; the day section renders it
    # as the panel's id.
    return f"schedule-day-{day_start:%Y-%m-%d}"


@dataclass
class ScheduleDay:
    day_start: datetime
    hours: list[ScheduleHour]
    tiles: list[ScheduleTile]

    @property
    def panel_id(self) -> str:
        return _day_panel_id(self.day_start)


@dataclass
class RoomLaneTile:
    data: SessionData
    start: datetime
    end: datetime
    col: int
    row_span: int
    lane_index: int = 0
    lane_count: int = 1


@dataclass
class RoomLaneRow:
    # One row of the grid. A row with no `hour` is the seam that opens a day;
    # every other row is a whole clock hour. Row numbers are positions in the
    # row list, so nothing counts them by hand.
    day: int
    day_start: datetime
    hour: datetime | None
    hour_end: datetime | None
    is_repeated: bool = False
    starting_tiles: list[RoomLaneTile] = field(default_factory=list, repr=False)
    slot_key: str | None = field(default=None, compare=False)


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


def _place_conflicting_tiles(
    positioned: list[tuple[int, RoomLaneTile]],
) -> list[tuple[int, RoomLaneTile]]:
    by_column: dict[int, list[tuple[int, RoomLaneTile]]] = defaultdict(list)
    for row_start, tile in positioned:
        by_column[tile.col].append((row_start, tile))

    placed: list[tuple[int, RoomLaneTile]] = []
    for column_tiles in by_column.values():
        ordered = sorted(
            column_tiles,
            key=lambda item: (
                item[1].start.timestamp(),
                item[1].end.timestamp(),
                item[1].data.session.title.casefold(),
                item[1].data.session.pk,
            ),
        )
        components: list[list[tuple[int, RoomLaneTile]]] = []
        component: list[tuple[int, RoomLaneTile]] = []
        component_end = 0
        for item in ordered:
            row_start, tile = item
            if component and row_start >= component_end:
                components.append(component)
                component = []
            component.append(item)
            component_end = max(component_end, row_start + tile.row_span)
        if component:
            components.append(component)

        for conflict in components:
            lane_ends: list[int] = []
            assigned: list[tuple[int, RoomLaneTile, int]] = []
            for row_start, tile in conflict:
                lane_index = next(
                    (
                        index
                        for index, lane_end in enumerate(lane_ends)
                        if lane_end <= row_start
                    ),
                    len(lane_ends),
                )
                if lane_index == len(lane_ends):
                    lane_ends.append(0)
                lane_ends[lane_index] = row_start + tile.row_span
                assigned.append((row_start, tile, lane_index))
            lane_count = len(lane_ends)
            placed.extend(
                (row_start, replace(tile, lane_index=lane_index, lane_count=lane_count))
                for row_start, tile, lane_index in assigned
            )

    return sorted(
        placed,
        key=lambda item: (
            item[0],
            item[1].col,
            item[1].start.timestamp(),
            item[1].end.timestamp(),
            item[1].lane_index,
            item[1].data.session.title.casefold(),
            item[1].data.session.pk,
        ),
    )


@dataclass
class RoomLanes:
    # Rooms are the outer axis: one column set, one header, one scroller for
    # the whole event, with the days stacked into it. A room idle on a given
    # day keeps its column and shows the gap, which reads as programme
    # information rather than as a layout accident.
    # `spans` is the distinct tile heights: row positions and span lengths are
    # different quantities that happen to share the integers, and the template
    # needs a CSS rule per span length it actually uses.
    rooms: list[RoomLane]
    rows: list[RoomLaneRow]
    spans: list[int]
    lane_indices: list[int]
    lane_counts: list[int]


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
        by_hour: dict[float, ScheduleHour] = {}
        for tile in tiles:
            start = tile.start.replace(minute=0, second=0, microsecond=0)
            hour = by_hour.setdefault(
                start.timestamp(), ScheduleHour(start=start, tiles=[])
            )
            hour.tiles.append(tile)
        hours = [by_hour[instant] for instant in sorted(by_hour)]
        hours = [
            replace(
                hour,
                is_repeated=_is_ambiguous_local_hour(hour.start),
                slot_key=_instant_key(hour.start),
            )
            for hour in hours
        ]
        days.append(ScheduleDay(day_start=hours[0].start, hours=hours, tiles=tiles))
    return days


CardSlotKind = Literal["ended", "current", "future"]


@dataclass
class CardSlot:
    kind: CardSlotKind
    hour: datetime
    sessions: list[SessionData]
    # The first not-yet-ended slot page-wide: the one the "Now" pill belongs to
    # while the event is live.
    is_first_current: bool = False
    # The pill prints its own date only on a single-day schedule; under a day
    # heading the date would repeat what the heading already states.
    show_date: bool = False


@dataclass
class CardDay:
    day_start: datetime
    slots: list[CardSlot]

    @property
    def panel_id(self) -> str:
        return _day_panel_id(self.day_start)


def _card_slots(
    kind: CardSlotKind, data: dict[datetime, list[SessionData]]
) -> list[CardSlot]:
    return [
        CardSlot(kind=kind, hour=hour, sessions=sessions)
        for hour, sessions in data.items()
    ]


def build_card_days(
    *,
    ended: dict[datetime, list[SessionData]],
    current: dict[datetime, list[SessionData]],
    future_unavailable: dict[datetime, list[SessionData]],
) -> list[CardDay]:
    # Day-major for the card layout: each local day folds as one unit, and
    # within a day the ended / current / future groups keep their old order,
    # so a single-day event renders exactly as it always has.
    tz = timezone.get_current_timezone()
    kind_order = {"ended": 0, "current": 1, "future": 2}
    slots = (
        _card_slots("ended", ended)
        + _card_slots("current", current)
        + _card_slots("future", future_unavailable)
    )
    slots.sort(
        key=lambda slot: (
            slot.hour.astimezone(tz).date().toordinal(),
            kind_order[slot.kind],
            slot.hour.timestamp(),
        )
    )
    if first_current := next((slot for slot in slots if slot.kind == "current"), None):
        first_current.is_first_current = True
    days: list[CardDay] = []
    for slot in slots:
        local_hour = slot.hour.astimezone(tz)
        if not days or days[-1].day_start.date() != local_hour.date():
            days.append(CardDay(day_start=local_hour, slots=[]))
        days[-1].slots.append(slot)
    if len(days) == 1:
        for slot in days[0].slots:
            slot.show_date = True
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
    sort_path: tuple[tuple[int, str, int], ...]
    space_id: int
    parent_id: int
    name: str
    parent_name: str


def _room_key(data: SessionData) -> _RoomKey:
    return _RoomKey(
        sort_path=data.loc["sort_path"],
        space_id=data.loc["space_id"],
        parent_id=data.loc["parent_id"],
        name=data.loc["space_name"],
        parent_name=data.loc["parent_name"],
    )


def _room_lanes(keys: list[_RoomKey]) -> list[RoomLane]:
    lanes: list[RoomLane] = []
    previous_group: str | None = None
    for key in keys:
        group_key = str(key.parent_id) if key.parent_id else ""
        lanes.append(
            RoomLane(
                name=key.name,
                group=key.parent_name,
                group_key=group_key,
                starts_group=group_key != previous_group,
            )
        )
        previous_group = group_key
    return lanes


def build_room_lanes(schedule_days: list[ScheduleDay]) -> RoomLanes:
    # One column set for the event, not one per day: per-day sets gave each day
    # its own column count and its own horizontal scroller, so the days drifted
    # out of step with each other as you panned.
    keys = sorted({_room_key(tile.data) for day in schedule_days for tile in day.tiles})
    col_index = {key: index + 1 for index, key in enumerate(keys)}

    rows: list[RoomLaneRow] = []
    positioned: list[tuple[int, RoomLaneTile]] = []
    spans: set[int] = set()
    for index, day in enumerate(schedule_days):
        day_start = day.day_start
        if index:
            # The seam that opens a day. The first day has none: there is
            # nothing before it to break from, and a heading above the first
            # row is the header printed twice rather than a boundary.
            rows.append(
                RoomLaneRow(
                    day=index,
                    day_start=day_start,
                    hour=None,
                    hour_end=None,
                    slot_key=None,
                )
            )
        first_hour_row = len(rows) + 1

        day_end = max(day.tiles, key=lambda tile: tile.end.timestamp()).end
        hour_windows: list[tuple[datetime, datetime]] = []
        mark = day_start
        while mark.timestamp() < day_end.timestamp():
            next_mark = (mark.astimezone(UTC) + timedelta(hours=1)).astimezone(
                day_start.tzinfo
            )
            hour_windows.append((mark, next_mark))
            mark = next_mark

        rows.extend(
            RoomLaneRow(
                day=index,
                day_start=day_start,
                hour=start,
                hour_end=end,
                is_repeated=_is_ambiguous_local_hour(start),
                slot_key=_instant_key(start),
            )
            for start, end in hour_windows
        )

        for tile in day.tiles:
            covered_rows = [
                offset
                for offset, (start, end) in enumerate(hour_windows)
                if start.timestamp() < tile.end.timestamp()
                and end.timestamp() > tile.start.timestamp()
            ]
            if not covered_rows:
                raise ValueError("scheduled tile does not overlap its local-day rows")
            start_hour = covered_rows[0]
            room_tile = RoomLaneTile(
                data=tile.data,
                start=tile.start,
                end=tile.end,
                col=col_index[_room_key(tile.data)],
                row_span=len(covered_rows),
            )
            spans.add(room_tile.row_span)
            positioned.append((first_hour_row + start_hour, room_tile))

    placed = _place_conflicting_tiles(positioned)
    for row_start, room_tile in placed:
        rows[row_start - 1].starting_tiles.append(room_tile)

    return RoomLanes(
        rooms=_room_lanes(keys),
        rows=rows,
        spans=sorted(spans),
        lane_indices=sorted({tile.lane_index for _, tile in placed}),
        lane_counts=sorted({tile.lane_count for _, tile in placed}),
    )
