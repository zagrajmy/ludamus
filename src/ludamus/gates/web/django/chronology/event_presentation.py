from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self, TypedDict

from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts import EventListItemDTO
from ludamus.pacts.legacy import SessionParticipationStatus

if TYPE_CHECKING:
    from ludamus.pacts import (
        AgendaItemDTO,
        LocationData,
        SessionDTO,
        SessionFieldValueDTO,
    )
    from ludamus.pacts.chronology import PartyEventHistoryDTO, PartySessionHistoryDTO
    from ludamus.pacts.crowd import UserDTO


@dataclass
class DisplayFieldRow:
    icon: str
    name: str
    visible_values: list[str]
    overflow_values: list[str]

    @property
    def overflow_count(self) -> int:
        return len(self.overflow_values)


_MAX_VISIBLE_PILLS = 4


def build_display_field_row(field_value: SessionFieldValueDTO) -> DisplayFieldRow:
    if isinstance(field_value.value, list):
        values = [value for value in field_value.value if isinstance(value, str)]
    elif isinstance(field_value.value, str):
        values = [field_value.value]
    else:
        values = []
    return DisplayFieldRow(
        icon=field_value.field_icon,
        name=field_value.field_name,
        visible_values=values[:_MAX_VISIBLE_PILLS],
        overflow_values=values[_MAX_VISIBLE_PILLS:],
    )


@dataclass
class ParticipationInfo:
    user: UserInfo
    status: str
    creation_time: datetime
    is_shadowbanned: bool = False


@dataclass
class SessionData:  # pylint: disable=too-many-instance-attributes
    agenda_item: AgendaItemDTO | None
    is_enrollment_available: bool
    presenter: UserInfo
    session: SessionDTO
    is_full: bool
    full_participant_info: str
    effective_participants_limit: int
    enrolled_count: int
    session_participations: list[ParticipationInfo]
    loc: LocationData
    can_edit: bool = False
    user_enrolled: bool = False
    user_waiting: bool = False
    user_bookmarked: bool = False
    bookmark_count: int = 0
    displayed_field_rows: list[DisplayFieldRow] = field(default_factory=list)
    field_values: list[SessionFieldValueDTO] = field(default_factory=list)
    waiting_count: int = 0
    is_ongoing: bool = False
    is_ended: bool = False
    should_show_as_inactive: bool = False
    pretend_full: bool = False

    @property
    def is_pending_proposal(self) -> bool:
        return self.agenda_item is None

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
        if self.effective_participants_limit == 0:
            return False
        return (
            self.spots_left / self.effective_participants_limit < self._SCARCE_THRESHOLD
        )

    @property
    def public_tags(self) -> str:
        return ",".join(
            str(value)
            for field_value in self.field_values
            if field_value.field_type == "select"
            and field_value.is_public
            and isinstance(field_value.value, list)
            for value in field_value.value
        )

    @property
    def public_tag_categories(self) -> str:
        return ";".join(
            f"{field_value.field_slug}:{value}"
            for field_value in self.field_values
            if field_value.field_type == "select"
            and field_value.is_public
            and isinstance(field_value.value, list)
            for value in field_value.value
        )

    @property
    def location_label(self) -> str:
        return self.loc.get("path", "")


class EventInfo(EventListItemDTO):
    cover_image_url: str

    @classmethod
    def from_list_item(cls, item: EventListItemDTO, *, cover_image_url: str) -> Self:
        return cls(**{**item.model_dump(), "cover_image_url": cover_image_url})


_SIMULACRA_FILL = 8
_SIMULACRA_NAMES = ("Aleksandra Nowak", "Piotr Kowalski", "Maria Wiśniewska")


def _simulacra_participations(count: int) -> list[ParticipationInfo]:
    now = datetime.now(tz=UTC)
    return [
        ParticipationInfo(
            user=UserInfo(
                avatar_url=None,
                discord_username="",
                full_name=name,
                name=name,
                pk=-index - 1,
                slug="",
                username="",
            ),
            status=SessionParticipationStatus.CONFIRMED.value,
            creation_time=now,
        )
        for index, name in enumerate(_SIMULACRA_NAMES[:count])
    ]


def fake_full_card(session_data: SessionData) -> SessionData:
    fill = session_data.effective_participants_limit or _SIMULACRA_FILL
    return replace(
        session_data,
        effective_participants_limit=fill,
        enrolled_count=fill,
        waiting_count=0,
        is_full=True,
        is_enrollment_available=True,
        full_participant_info=f"{fill}/{fill}",
        user_enrolled=False,
        user_waiting=False,
        session_participations=_simulacra_participations(min(3, fill)),
        pretend_full=True,
    )


def mask_session_card(
    session_data: SessionData, *, event_banned: bool, banned_presenter_ids: set[int]
) -> SessionData:
    if event_banned or session_data.presenter.pk in banned_presenter_ids:
        return fake_full_card(session_data)
    return session_data


class PartyHistoryGroup(TypedDict):
    event_name: str
    event_slug: str
    cards: list[SessionData]


def present_party_history(
    groups: list[PartyEventHistoryDTO],
    *,
    banned_event_ids: set[int],
    banned_presenter_ids: set[int],
) -> list[PartyHistoryGroup]:
    now = datetime.now(tz=UTC)
    return [
        PartyHistoryGroup(
            event_name=group.event_name,
            event_slug=group.event_slug,
            cards=[
                mask_session_card(
                    _party_history_card(item, now=now),
                    event_banned=group.event_pk in banned_event_ids,
                    banned_presenter_ids=banned_presenter_ids,
                )
                for item in group.sessions
            ],
        )
        for group in groups
    ]


def _party_history_card(item: PartySessionHistoryDTO, *, now: datetime) -> SessionData:
    if item.presenter is not None:
        presenter = _user_info(item.presenter)
    else:
        name = item.session.display_name
        presenter = UserInfo(
            avatar_url=None,
            discord_username="",
            full_name=name,
            name=name,
            pk=0,
            slug="",
            username=name,
        )
    return SessionData(
        agenda_item=item.agenda_item,
        is_enrollment_available=item.is_enrollment_available,
        presenter=presenter,
        session=item.session,
        is_full=item.is_full,
        full_participant_info=item.full_participant_info,
        effective_participants_limit=item.effective_participants_limit,
        enrolled_count=item.enrolled_count,
        session_participations=[
            ParticipationInfo(
                user=_user_info(seat.user),
                status=seat.status,
                creation_time=seat.creation_time,
            )
            for seat in item.participations
        ],
        loc=item.location,
        user_enrolled=item.viewer_enrolled,
        waiting_count=item.waiting_count,
        is_ongoing=item.agenda_item.start_time <= now < item.agenda_item.end_time,
        is_ended=item.agenda_item.end_time <= now,
    )


def _user_info(user: UserDTO) -> UserInfo:
    return UserInfo(
        avatar_url=user.avatar_url or None,
        discord_username=user.discord_username,
        full_name=user.full_name,
        name=user.name,
        pk=user.pk,
        slug=user.slug,
        username=user.username,
    )
