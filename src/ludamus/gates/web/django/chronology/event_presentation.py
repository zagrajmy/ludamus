from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self, TypedDict

from django.utils.translation import ngettext

from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.helpers import placeholder_cover_url
from ludamus.pacts import EventListItemDTO
from ludamus.pacts.legacy import SessionParticipationStatus, TimeSlotDTO

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from ludamus.pacts import (
        AgendaItemDTO,
        LocationData,
        OrganizerFieldDTO,
        SessionDTO,
        SessionFieldValueDTO,
    )
    from ludamus.pacts.chronology import (
        PartyEventHistoryDTO,
        PartySessionHistoryDTO,
        SessionModalDTO,
    )
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.enrollment import EnrollmentAccessDTO
    from ludamus.pacts.guild import GuildMarkDTO
    from ludamus.pacts.ids import EventId, UserId


@dataclass(frozen=True)
class CloudPill:
    icon: str
    value: str


@dataclass(frozen=True)
class LocationCrumb:
    name: str
    space_filter: str | None


_VENUE_FILTER_PREFIX = "venue:"


@dataclass
class DisplayFieldRow:
    icon: str
    name: str
    visible_values: list[str]
    overflow_values: list[str]

    @property
    def overflow_count(self) -> int:
        return len(self.overflow_values)


def flatten_cloud_overflow(rows: list[DisplayFieldRow]) -> list[CloudPill]:
    return [
        CloudPill(icon=row.icon, value=value)
        for row in rows
        for value in row.overflow_values
    ]


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


def _seat_count(seats: int) -> str:
    return ngettext("%(counter)s seat", "%(counter)s seats", seats) % {"counter": seats}


def _seats_free(free: int) -> str:
    # NOTE: "free" does not inflect in English, so both forms read the same.
    # The plural is still declared, for the languages where it does — Polish
    # picks a different one of its four for 1, 2 and 5.
    return ngettext("%(counter)s free", "%(counter)s free", free) % {"counter": free}


@dataclass
class SessionData:  # pylint: disable=too-many-instance-attributes
    agenda_item: AgendaItemDTO | None
    is_enrollment_available: bool
    presenter: UserInfo
    session: SessionDTO
    is_full: bool
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
    track_names: list[str] = field(default_factory=list)
    category_name: str = ""
    waiting_count: int = 0
    is_ongoing: bool = False
    is_ended: bool = False
    should_show_as_inactive: bool = False
    pretend_full: bool = False
    # The person on the card's guild in this sphere, or None. The presenter
    # when the session has one; otherwise the first facilitator with a guild.
    # Defaults so the many equality assertions over this dataclass keep passing
    # for guild-less sessions, which is the overwhelming majority.
    guild: GuildMarkDTO | None = None
    # True when the *viewer* shadowbanned the presenter — viewer-relative, like
    # ParticipationInfo.is_shadowbanned, never global moderation state. Drives
    # the avatar's warning badge, which decides the guild mark's corner. Set
    # from a pk, and a presenter-less session's stand-in pk 0 never matches.
    presenter_is_shadowbanned: bool = False
    # Slots the author would accept, earliest first. Only ever populated for a
    # pending proposal: a scheduled session states its real time via
    # agenda_item, and reading the m2m for one would cost a query per card.
    preferred_time_slots: list[TimeSlotDTO] = field(default_factory=list)

    @property
    def cloud_overflow(self) -> list[CloudPill]:
        return flatten_cloud_overflow(self.displayed_field_rows)

    @property
    def is_unscheduled(self) -> bool:
        # Not "is a proposal": status and scheduling are separate axes, and a
        # PENDING session that already holds an agenda item is scheduled.
        return self.agenda_item is None

    @property
    def takes_enrollment(self) -> bool:
        # The session's own limit, not the effective one: a 0% seating window
        # zeroes the effective limit without making the session sign-up-free.
        # An unscheduled proposal has no seat to take yet whatever its limit
        # says, and this answer reaches the enrollment filters as
        # data-takes-enrollment.
        return not self.is_unscheduled and self.session.participants_limit > 0

    @property
    def availability(self) -> str:
        """Name the one availability state every layout and label dispatches on."""
        # Order matters: a session that takes no sign-up is not "unavailable"
        # (its window never opens) and not "full" (it never had a seat), so it
        # leaves the ladder before either term is asked. A proposal leaves
        # first of all: every term below is about a seat it does not have yet,
        # and this string reaches the DOM as data-status, where answering
        # "unavailable" would put proposals behind the enrollment filters.
        if self.is_unscheduled:
            return "proposal"
        if self.is_ended:
            return "ended"
        if self.should_show_as_inactive:
            return "in-progress"
        if not self.takes_enrollment:
            return "no-enrollment"
        if not self.is_enrollment_available:
            return "unavailable"
        if self.is_full:
            return "full"
        return "available"

    @property
    def spots_left(self) -> int:
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
    def seats_label(self) -> str:
        """State this session's seats, where sign-up is not on offer.

        Returns:
            The muted label: a cap, or what is free of one.
        """
        # Never "N spots left": that one is teal, and neither state reaching
        # here has an invitation to make.
        if self.is_unscheduled:
            # No window can seat an unscheduled session, so none has halved
            # the room its author asked for, and nobody holds a seat in it.
            return _seat_count(self.session.participants_limit)
        if self.enrolled_count:
            # The cap has stopped answering "how much room is there".
            return _seats_free(self.spots_left)
        return _seat_count(self.effective_participants_limit)

    def public_select_answers(self) -> Iterator[tuple[str, str]]:
        """Yield every (field slug, value) a public select field carries.

        Yields:
            One pair per selected value, in field order.
        """
        for field_value in self.field_values:
            if (
                field_value.field_type == "select"
                and field_value.is_public
                and isinstance(field_value.value, list)
            ):
                for value in field_value.value:
                    yield field_value.field_slug, str(value)

    @property
    def public_tags(self) -> str:
        return ",".join(value for _slug, value in self.public_select_answers())

    @property
    def public_tag_categories(self) -> str:
        return ";".join(
            f"{slug}:{value}" for slug, value in self.public_select_answers()
        )

    @property
    def filter_categories(self) -> str:
        # Extends the public-tag-category channel (slug:value;...) that
        # session-filters.ts already parses, so track and proposal category
        # ride the same client-side filter mechanism with no new JS. The
        # __track / __category keys can't be a real SessionField slug in
        # practice.
        # ponytail: names with ':' or ';' would break parsing, same as the
        # existing tag values; track/category names never contain them.
        parts = [self.public_tag_categories] if self.public_tag_categories else []
        parts.extend(f"__track:{name}" for name in self.track_names)
        if self.category_name:
            parts.append(f"__category:{self.category_name}")
        return ";".join(parts)

    @property
    def location_label(self) -> str:
        return self.loc.get("path", "")

    @property
    def location_crumbs(self) -> list[LocationCrumb]:
        if not (path := self.loc["sort_path"]):
            return []
        space_id = self.loc["space_id"]
        parent_id = self.loc["parent_id"]
        crumbs: list[LocationCrumb] = []
        for _order, name, pk in path:
            if pk == space_id:
                space_filter = str(pk)
            elif pk == parent_id:
                space_filter = f"{_VENUE_FILTER_PREFIX}{pk}"
            else:
                space_filter = None
            crumbs.append(LocationCrumb(name=name, space_filter=space_filter))
        return crumbs


class FilterAvailability(TypedDict):
    track_filter_names: list[str]
    category_filter_names: list[str]


# A dropdown is only worth showing when there's more than one value to pick
# between, matching how Venue/Day/Hour reveal themselves. Every filter on the
# event page clears this same bar; the two helpers below only differ in where
# they read the values from.
def filter_availability(cards: Iterable[SessionData]) -> FilterAvailability:
    # The names, not a flag: the template renders these two dropdowns' options
    # itself, so the client follows one rule for every filter — drop the
    # options no card uses — instead of filling these two from the cards and
    # the rest from the server. Empty below the bar, so the same list says both
    # whether to draw the filter and what goes in it.
    card_list = list(cards)
    tracks = sorted({name for c in card_list for name in c.track_names})
    categories = sorted({c.category_name for c in card_list if c.category_name})
    return {
        "track_filter_names": tracks if len(tracks) > 1 else [],
        "category_filter_names": categories if len(categories) > 1 else [],
    }


def filterable_tag_fields(
    fields: Sequence[OrganizerFieldDTO], cards: Iterable[SessionData]
) -> list[OrganizerFieldDTO]:
    """Keep the organizer-defined select fields worth offering as a filter.

    Returns:
        The fields whose answers split the schedule more than one way, in the
        order given. A field nobody answered, or one every session answers the
        same way, is left out rather than drawn as a label above an "All ..."
        box.
    """
    # Only answers that are a defined choice count: the dropdown offers the
    # field's choices, so a value written into an allow_custom field would
    # otherwise clear the bar for a field that ends up with nothing to pick.
    answers: dict[str, set[str]] = defaultdict(set)
    for card in cards:
        for slug, value in card.public_select_answers():
            answers[slug].add(value)
    return [
        field
        for field in fields
        if len(answers[field.slug] & {option.value for option in field.options}) > 1
    ]


class EventInfo(EventListItemDTO):
    cover_image_url: str

    @classmethod
    def from_list_item(cls, item: EventListItemDTO, *, cover_image_url: str) -> Self:
        return cls(**{**item.model_dump(), "cover_image_url": cover_image_url})


def with_covers(items: list[EventListItemDTO]) -> list[EventInfo]:
    # Uploaded cover when present, otherwise a placeholder cycled by position.
    # Position-keyed, so callers sort before calling: see split_events.
    return [
        EventInfo.from_list_item(
            item, cover_image_url=item.cover_image_url or placeholder_cover_url(i)
        )
        for i, item in enumerate(items)
    ]


@dataclass(frozen=True)
class EventSplit:
    upcoming: list[EventInfo]
    past: list[EventInfo]


def split_events(items: Iterable[EventListItemDTO]) -> EventSplit:
    """Split a sphere's events into the two lists every event listing renders.

    Returns:
        Upcoming soonest-first and past most-recent-first, both with covers.
    """
    # Sorted before with_covers, not after: placeholder art is keyed by
    # position, so an unsorted list would give the same coverless event a
    # different placeholder on each page that lists it.
    listed = list(items)
    return EventSplit(
        upcoming=with_covers(
            sorted(
                (item for item in listed if not item.is_ended),
                key=lambda item: item.start_time,
            )
        ),
        past=with_covers(
            sorted(
                (item for item in listed if item.is_ended),
                key=lambda item: item.start_time,
                reverse=True,
            )
        ),
    )


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
    # Assumes a scheduled card. An unscheduled proposal leaves both availability
    # and takes_enrollment before any faked field is read, so the mask would be
    # a silent no-op on one — nothing routes a proposal here today, and nothing
    # should start without revisiting that.
    fill = session_data.effective_participants_limit or _SIMULACRA_FILL
    return replace(
        session_data,
        # The mask has to be consistent with itself: left at 0 the session would
        # read as taking no enrollment, and the card would render that state
        # instead of the "Full" the mask exists to show.
        session=session_data.session.model_copy(update={"participants_limit": fill}),
        effective_participants_limit=fill,
        enrolled_count=fill,
        waiting_count=0,
        is_full=True,
        is_enrollment_available=True,
        user_enrolled=False,
        user_waiting=False,
        session_participations=_simulacra_participations(min(3, fill)),
        pretend_full=True,
    )


def mask_session_card(
    session_data: SessionData, *, event_banned: bool, banned_presenter_ids: set[UserId]
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
    banned_event_ids: set[EventId],
    banned_presenter_ids: set[UserId],
) -> list[PartyHistoryGroup]:
    # Nobody enrolls from a party's history: it is the seats the party holds,
    # across events whose windows this page never asked about. So its cards
    # state capacity and never "N spots left", which is a claim about a window
    # being open to the reader.

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
        is_enrollment_available=False,
        presenter=presenter,
        session=item.session,
        is_full=item.is_full,
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


def present_session_modal(
    dto: SessionModalDTO,
    *,
    event_banned: bool,
    banned_presenter_ids: set[UserId],
    shadowbanned_ids: frozenset[UserId],
    # The viewer's own windows. A window restricted to pass holders can seat
    # this session without being open to the person reading the page, so
    # availability is theirs, not the session's.
    access: EnrollmentAccessDTO,
    guild: GuildMarkDTO | None = None,
) -> SessionData:
    if dto.presenter is not None:
        presenter = _user_info(dto.presenter)
    else:
        name = dto.session.display_name
        presenter = UserInfo(
            avatar_url=None,
            discord_username="",
            full_name=name,
            name=name,
            pk=0,
            slug="",
            username=name,
        )
    card = SessionData(
        agenda_item=dto.agenda_item,
        is_enrollment_available=access.seats(dto.enrollment_window_ids),
        presenter=presenter,
        session=dto.session,
        is_full=dto.is_full,
        effective_participants_limit=dto.effective_participants_limit,
        enrolled_count=dto.enrolled_count,
        session_participations=[
            ParticipationInfo(
                user=_user_info(seat.user),
                status=seat.status,
                creation_time=seat.creation_time,
                is_shadowbanned=seat.user.pk in shadowbanned_ids,
            )
            for seat in dto.participations
        ],
        loc=dto.location,
        can_edit=dto.can_edit,
        user_enrolled=dto.viewer_enrolled,
        user_waiting=dto.viewer_waiting,
        field_values=dto.field_values,
        waiting_count=dto.waiting_count,
        is_ongoing=dto.is_ongoing,
        is_ended=dto.is_ended,
        guild=guild,
        presenter_is_shadowbanned=presenter.pk in shadowbanned_ids,
    )
    return mask_session_card(
        card, event_banned=event_banned, banned_presenter_ids=banned_presenter_ids
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
