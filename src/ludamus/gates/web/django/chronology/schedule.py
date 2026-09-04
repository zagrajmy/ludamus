from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from itertools import groupby, pairwise
from typing import TYPE_CHECKING, Literal, NamedTuple

from django.utils import timezone

from ludamus.mills.timeslots import PROGRAMME_DAYS, Window

if TYPE_CHECKING:
    from ludamus.gates.web.django.chronology.event_presentation import SessionData

# A stretch of a day in which nothing starts or ends, this long or longer,
# folds into one thin row of the rooms grid. Shorter lulls stay whole: an idle
# hour or two inside the programme is the shape of the day, not dead space to
# pan across.
FOLD_MIN_MINUTES = 180


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
    # One session as it appears on one programme day, already clipped to it.
    # Days turn over in the small hours (PROGRAMME_DAY_STARTS_AT_HOUR), so a night
    # session is one tile under the evening it belongs to; a session running
    # through the turnover makes two. The ledger reads the clipped windows; the
    # rooms grid, whose axis runs straight through a day break, joins them back
    # into one booking (_bookings).
    data: SessionData
    start: datetime
    end: datetime


def _day_panel_id(day_start: datetime) -> str:
    # The fold toggle names this in aria-controls; the day section renders it
    # as the panel's id.
    return f"schedule-day-{day_start:%Y-%m-%d}"


@dataclass
class ScheduleDay:
    # `day_start` is the instant the programme day opens — its date and weekday
    # are the day's name — not the first hour with anything in it, which is
    # `hours[0].start`.
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
    # One row of the grid. A row with no `window` is the seam that opens a day;
    # every other row spans a stretch of clock time — a whole hour, a piece of
    # one where `_row_windows` cut it, in which case `hour_mark` is still the
    # hour it belongs to, or a fold: hours of lull drawn as one thin band
    # (`is_fold`). Row numbers are positions in the row list, so nothing counts
    # them by hand.
    # `opens_slot` marks the one row per hour that anchors #slot-<hour> for the
    # scrubber and the filters; see build_room_lanes.
    day: int
    day_start: datetime
    hour_mark: datetime | None
    window: Window | None
    is_fold: bool = False
    starting_tiles: list[RoomLaneTile] = field(default_factory=list, repr=False)
    opens_slot: bool = field(default=False, compare=False)

    @property
    def start(self) -> datetime | None:
        return None if self.window is None else self.window[0]

    @property
    def end(self) -> datetime | None:
        return None if self.window is None else self.window[1]

    @property
    def minutes(self) -> int:
        # The row's length, and so its share of an hour of grid height. A seam
        # measures no time, and zero is what its grid track is keyed on.
        if self.window is None:
            return 0
        start, end = self.window
        return max(1, round((end.timestamp() - start.timestamp()) / 60))

    @property
    def track(self) -> str:
        # The grid track the row asks for, named once for the template and the
        # client alike: its length off the hour unit, or the one fold track.
        return "fold" if self.is_fold else str(self.minutes)

    @property
    def is_cut(self) -> bool:
        # Asked of the producer, not guessed from the wall clock: a zone whose
        # offset moves by a half hour puts every later hour mark on :30.
        if self.window is None or self.hour_mark is None:
            return False
        return self.window[0].timestamp() != self.hour_mark.timestamp()

    @property
    def is_repeated(self) -> bool:
        return self.window is not None and _is_ambiguous_local_hour(self.window[0])

    @property
    def slot_key(self) -> str | None:
        # The hour, never the cut: the scrubber's markers are whole hours
        # (_compact_schedule.html), and every row inside one answers to the same
        # key so a session that starts at 16:30 is still reachable under 16:00.
        return None if self.hour_mark is None else _instant_key(self.hour_mark)


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


class _RowWindow(NamedTuple):
    # A stretch of a day's axis before it becomes a grid row: the hour it
    # belongs to, its bounds, and whether it stands in for a lull.
    hour_mark: datetime
    start: datetime
    end: datetime
    is_fold: bool = False


def _row_windows(first_hour: datetime, tiles: list[ScheduleTile]) -> list[_RowWindow]:
    # The grid's rows, each as (the hour it belongs to, start, end): whole clock
    # hours, cut again wherever a tile starts or ends inside one. Rows are what
    # the grid stacks, so two tiles sharing a row must be laid side by side even
    # when they merely touch — a session ending at 16:30 and the next starting
    # at 16:30 both live in the 16:00 hour, and an hour-only ruler showed them
    # clashing. Cutting at the instants the programme changes makes "shares a
    # row" mean "overlaps in time" again, and _place_conflicting_tiles goes on
    # reading rows. The hour rides along because a cut row still answers to it
    # for the scrubber, and because "is this a cut?" is then a fact rather than
    # a reading of the wall clock.
    # Every instant is compared and keyed as a timestamp, never as a datetime:
    # PEP 495 has two same-zone datetimes that differ only in `fold` compare
    # equal and hash equal, so on the night the clocks go back a plain set or
    # sort silently folds 02:00 CEST and 02:00 CET — an hour apart — into one
    # edge, and the grid loses an hour of programme.
    day_end = max(tile.end.timestamp() for tile in tiles)
    # Stepped through UTC so an hour of grid is an hour of programme: a clock
    # change inside the day moves the marks with it instead of repeating or
    # skipping one.
    marks = [first_hour]
    while marks[-1].timestamp() < day_end:
        marks.append(
            (marks[-1].astimezone(UTC) + timedelta(hours=1)).astimezone(
                first_hour.tzinfo
            )
        )
    cuts = {
        instant.timestamp(): instant
        for tile in tiles
        for instant in (tile.start, tile.end)
    }
    windows: list[_RowWindow] = []
    for mark, next_mark in pairwise(marks):
        inside = sorted(
            key for key in cuts if mark.timestamp() < key < next_mark.timestamp()
        )
        edges = [mark, *(cuts[key] for key in inside), next_mark]
        windows.extend(
            _RowWindow(hour_mark=mark, start=start, end=end)
            for start, end in pairwise(edges)
        )
    return windows


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
    # The distinct row lengths in minutes, so the template can serve one grid
    # track per length off the hour unit in the stylesheet — the same service
    # `spans` does for the tile heights. Folds are not lengths: they take the
    # one fixed fold track whatever they stand in for.
    row_lengths: list[int]


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
        for window_start, window_end in PROGRAMME_DAYS.windows(
            start=item.start_time, end=item.end_time, tz=tz
        ):
            tiles_by_date[PROGRAMME_DAYS.date_of(window_start, tz)].append(
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
        days.append(
            ScheduleDay(
                day_start=PROGRAMME_DAYS.opening(day, tz), hours=hours, tiles=tiles
            )
        )
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
            PROGRAMME_DAYS.date_of(slot.hour, tz).toordinal(),
            kind_order[slot.kind],
            slot.hour.timestamp(),
        )
    )
    if first_current := next((slot for slot in slots if slot.kind == "current"), None):
        first_current.is_first_current = True
    days = [
        CardDay(day_start=PROGRAMME_DAYS.opening(day, tz), slots=list(group))
        for day, group in groupby(
            slots, key=lambda slot: PROGRAMME_DAYS.date_of(slot.hour, tz)
        )
    ]
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


class _Booking(NamedTuple):
    # A session as one span of the grid's continuous axis: the whole agenda
    # item, not the per-day pieces the ledger clips it into.
    data: SessionData
    start: datetime
    end: datetime


def _bookings(schedule_days: list[ScheduleDay]) -> list[_Booking]:
    # A session's tiles are the contiguous pieces of one span, days in order
    # and tiles in start order within a day, so the first opens the booking
    # and the last closes it.
    tiles_by_session: dict[int, list[ScheduleTile]] = defaultdict(list)
    for day in schedule_days:
        for tile in day.tiles:
            tiles_by_session[tile.data.session.pk].append(tile)
    return [
        _Booking(data=tiles[0].data, start=tiles[0].start, end=tiles[-1].end)
        for tiles in tiles_by_session.values()
    ]


def _fold_lulls(
    windows: list[_RowWindow], bookings: list[_Booking]
) -> list[_RowWindow]:
    # An hour is busy when a booking starts or ends in it — exactly on one of
    # its windows' edges, since _row_windows cuts the axis at every such
    # instant. Whole hours, not windows: a lull that ends at a :30 start must
    # leave that hour standing, labelled, with the cut inside it. Hours are
    # keyed as instants, never as datetimes, or the two 02:00 hours of an
    # autumn clock change would compare equal and merge. A run of quiet hours
    # long enough to fold becomes one window spanning the run: the night under
    # an all-night session costs one thin band, and the session still spans it
    # like any row.
    starts = {booking.start.timestamp() for booking in bookings}
    ends = {booking.end.timestamp() for booking in bookings}
    busy_hours = {
        window.hour_mark.timestamp()
        for window in windows
        if window.start.timestamp() in starts or window.end.timestamp() in ends
    }

    def minutes(window: _RowWindow) -> float:
        return (window.end.timestamp() - window.start.timestamp()) / 60

    folded: list[_RowWindow] = []
    for busy, group in groupby(
        windows, key=lambda window: window.hour_mark.timestamp() in busy_hours
    ):
        run = list(group)
        if busy or sum(minutes(window) for window in run) < FOLD_MIN_MINUTES:
            folded.extend(run)
        else:
            folded.append(run[0]._replace(end=run[-1].end, is_fold=True))
    return folded


def build_room_lanes(schedule_days: list[ScheduleDay]) -> RoomLanes:
    # One column set for the event, not one per day: per-day sets gave each day
    # its own column count and its own horizontal scroller, so the days drifted
    # out of step with each other as you panned.
    keys = sorted({_room_key(tile.data) for day in schedule_days for tile in day.tiles})
    col_index = {key: index + 1 for index, key in enumerate(keys)}
    bookings = _bookings(schedule_days)

    rows: list[RoomLaneRow] = []
    for index, day in enumerate(schedule_days):
        day_start = day.day_start
        if index:
            # The seam that opens a day. The first day has none: there is
            # nothing before it to break from, and a heading above the first
            # row is the header printed twice rather than a boundary.
            rows.append(
                RoomLaneRow(day=index, day_start=day_start, hour_mark=None, window=None)
            )
        rows.extend(
            RoomLaneRow(
                day=index,
                day_start=day_start,
                hour_mark=window.hour_mark,
                window=(window.start, window.end),
                is_fold=window.is_fold,
            )
            for window in _fold_lulls(
                _row_windows(day.hours[0].start, day.tiles), bookings
            )
        )

    # One axis for the whole event: a booking spans every row from the one
    # holding its start to the one holding its end, a day seam between them
    # included, so a night session is one tile rather than two halves.
    positioned: list[tuple[int, RoomLaneTile]] = []
    spans: set[int] = set()
    for booking in bookings:
        covered_rows = [
            offset
            for offset, row in enumerate(rows)
            if row.window is not None
            and row.window[0].timestamp() < booking.end.timestamp()
            and row.window[1].timestamp() > booking.start.timestamp()
        ]
        if not covered_rows:
            raise ValueError("scheduled booking does not overlap its rows")
        room_tile = RoomLaneTile(
            data=booking.data,
            start=booking.start,
            end=booking.end,
            col=col_index[_room_key(booking.data)],
            row_span=covered_rows[-1] - covered_rows[0] + 1,
        )
        spans.add(room_tile.row_span)
        positioned.append((covered_rows[0] + 1, room_tile))

    placed = _place_conflicting_tiles(positioned)
    for row_start, room_tile in placed:
        rows[row_start - 1].starting_tiles.append(room_tile)

    # One #slot-<hour> anchor per hour that starts anything, on the first of its
    # rows that does: the id has to stay unique, and the scrubber jumps to the
    # hour rather than to whichever cut inside it happens to hold a session.
    opened: set[str] = set()
    for row in rows:
        if row.starting_tiles and row.slot_key is not None:
            row.opens_slot = row.slot_key not in opened
            opened.add(row.slot_key)

    return RoomLanes(
        rooms=_room_lanes(keys),
        rows=rows,
        spans=sorted(spans),
        lane_indices=sorted({tile.lane_index for _, tile in placed}),
        lane_counts=sorted({tile.lane_count for _, tile in placed}),
        row_lengths=sorted(
            {row.minutes for row in rows if row.minutes and not row.is_fold}
        ),
    )
