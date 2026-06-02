from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.adapters.db.django.models import Event
    from ludamus.gates.web.django.entities import UserInfo
    from ludamus.pacts import (
        AgendaItemDTO,
        LocationData,
        SessionDTO,
        SessionFieldValueDTO,
        UserDTO,
    )


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
    displayed_field_rows: list[DisplayFieldRow] = field(default_factory=list)
    field_values: list[SessionFieldValueDTO] = field(default_factory=list)
    waiting_count: int = 0
    is_ongoing: bool = False  # True if session has already started
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
        """Comma-separated location from venue, area, space."""
        parts: list[str] = []
        venue = self.loc.get("venue")
        if venue and venue.name.strip():
            parts.append(venue.name)
        area = self.loc.get("area")
        if area and area.name.strip():
            parts.append(area.name)
        space = self.loc.get("space")
        if space and space.name.strip():
            parts.append(space.name)
        return ", ".join(parts)


@dataclass
class EventInfo:  # pylint: disable=too-many-instance-attributes
    cover_image_url: str
    description: str
    end_time: datetime
    is_ended: bool
    is_live: bool
    is_proposal_active: bool
    is_published: bool
    name: str
    session_count: int
    start_time: datetime
    slug: str

    @classmethod
    def from_event(
        cls, *, event: Event, session_count: int, cover_image_url: str
    ) -> Self:
        return cls(
            cover_image_url=cover_image_url,
            description=event.description,
            end_time=event.end_time,
            is_ended=event.is_ended,
            is_live=event.is_live,
            is_proposal_active=event.is_proposal_active,
            is_published=event.is_published,
            name=event.name,
            session_count=session_count,
            slug=event.slug,
            start_time=event.start_time,
        )


@dataclass
class SessionUserParticipationData:
    user: UserDTO
    user_enrolled: bool = False
    user_waiting: bool = False
    has_time_conflict: bool = False
