from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

from django.utils import timezone

from ludamus.pacts import EventListItemDTO

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.gates.web.django.entities import UserInfo
    from ludamus.pacts import (
        AgendaItemDTO,
        LocationData,
        SessionDTO,
        SessionFieldValueDTO,
    )
    from ludamus.pacts.crowd import UserDTO


@dataclass
class DisplayFieldRow:
    """A field's values capped for card display."""

    icon: str
    name: str
    visible_values: list[str]
    overflow_values: list[str]

    @property
    def overflow_count(self) -> int:
        return len(self.overflow_values)


_MAX_VISIBLE_PILLS = 4


def build_display_field_row(fv: SessionFieldValueDTO) -> DisplayFieldRow:
    if isinstance(fv.value, list):
        str_values = [v for v in fv.value if isinstance(v, str)]
    elif isinstance(fv.value, str):
        str_values = [fv.value]
    else:
        str_values = []
    return DisplayFieldRow(
        icon=fv.field_icon,
        name=fv.field_name,
        visible_values=str_values[:_MAX_VISIBLE_PILLS],
        overflow_values=str_values[_MAX_VISIBLE_PILLS:],
    )


@dataclass
class ParticipationInfo:
    user: UserInfo
    status: str
    creation_time: datetime
    is_shadowbanned: bool = False


@dataclass
class SessionData:  # pylint: disable=too-many-instance-attributes
    agenda_item: AgendaItemDTO
    is_enrollment_available: bool
    presenter: UserInfo
    session: SessionDTO
    is_full: bool
    full_participant_info: str
    effective_participants_limit: int
    enrolled_count: int
    session_participations: list[ParticipationInfo]
    loc: LocationData
    has_any_enrollments: bool = False
    can_edit: bool = False
    user_enrolled: bool = False
    user_waiting: bool = False
    user_bookmarked: bool = False
    displayed_field_rows: list[DisplayFieldRow] = field(default_factory=list)
    field_values: list[SessionFieldValueDTO] = field(default_factory=list)
    waiting_count: int = 0
    is_ongoing: bool = False  # True if session has already started
    is_ended: bool = False  # True if the session's end time has passed
    should_show_as_inactive: bool = (
        False  # True if should be displayed as inactive due to limit_to_end_time
    )

    @property
    def is_unlimited(self) -> bool:
        return self.effective_participants_limit == 0

    @property
    def spots_left(self) -> int:
        if self.effective_participants_limit == 0:
            return sys.maxsize
        return max(0, self.effective_participants_limit - self.enrolled_count)

    _SCARCE_THRESHOLD = 0.2

    @property
    def spots_scarce(self) -> bool:
        """Check whether less than 20% of spots remain.

        Returns:
            Whether spots are running low.
        """
        if self.effective_participants_limit == 0:
            return False
        ratio = self.spots_left / self.effective_participants_limit
        return ratio < self._SCARCE_THRESHOLD

    @property
    def location_label(self) -> str:
        # Full "Root > ... > Leaf" tree path of the scheduled space.
        return self.loc.get("path", "")


class EventInfo(EventListItemDTO):
    cover_image_url: str

    @classmethod
    def from_list_item(cls, item: EventListItemDTO, *, cover_image_url: str) -> Self:
        return cls(**{**item.model_dump(), "cover_image_url": cover_image_url})


@dataclass
class ScheduleHour:
    """One local-clock hour of the compact schedule, with its sessions."""

    start: datetime
    sessions: list[SessionData]


@dataclass
class ScheduleDay:
    """A day's worth of compact-schedule hours, grouped for the hour scrubber."""

    first_start: datetime
    hours: list[ScheduleHour]


@dataclass
class RoomLaneRow:
    """One hour row of the rooms view: a cell of sessions per room."""

    start: datetime
    cells: list[list[SessionData]]


@dataclass
class RoomLaneDay:
    """A day of the rooms view: room columns and per-hour rows."""

    first_start: datetime
    rooms: list[str]
    rows: list[RoomLaneRow]


def build_schedule_days(sessions_data: dict[int, SessionData]) -> list[ScheduleDay]:
    # sessions_data preserves the queryset's chronological order, so a single
    # pass groups sessions into whole local-clock hours and hours into
    # local-calendar days. Hour buckets (not exact start times) keep the rail,
    # the section ids, and the hour headings one-to-one, so filtering can never
    # strand a heading or a rail marker on a hidden sub-slot.
    days: list[ScheduleDay] = []
    for data in sessions_data.values():
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


def build_room_lanes(schedule_days: list[ScheduleDay]) -> list[RoomLaneDay]:
    # Pivot each day's hours into a rooms grid: one column per scheduled leaf
    # space, one row per hour. Rooms are keyed by (name, parent) — leaf names
    # repeat across venues — and the label carries the parent only when the
    # bare name would be ambiguous.
    lane_days: list[RoomLaneDay] = []
    for day in schedule_days:
        keys = sorted(
            {
                (data.loc["space_name"], data.loc["parent_name"])
                for hour in day.hours
                for data in hour.sessions
            }
        )
        name_counts = Counter(name for name, _ in keys)
        rooms = [
            f"{name} ({parent})" if name_counts[name] > 1 and parent else name
            for name, parent in keys
        ]
        column = {key: index for index, key in enumerate(keys)}
        rows = []
        for hour in day.hours:
            cells: list[list[SessionData]] = [[] for _ in keys]
            for data in hour.sessions:
                cells[column[data.loc["space_name"], data.loc["parent_name"]]].append(
                    data
                )
            rows.append(RoomLaneRow(start=hour.start, cells=cells))
        lane_days.append(
            RoomLaneDay(first_start=day.first_start, rooms=rooms, rows=rows)
        )
    return lane_days


@dataclass
class SessionUserParticipationData:
    user: UserDTO
    user_enrolled: bool = False
    user_waiting: bool = False
    has_time_conflict: bool = False
