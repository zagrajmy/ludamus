import re
import string
import unicodedata
from datetime import UTC, datetime, timedelta
from html import escape as _escape
from html.parser import HTMLParser
from secrets import choice as _secret_choice
from secrets import token_urlsafe
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit

import markdown as _md

from ludamus.pacts import (
    AgendaItemData,
    AuthenticatedRequestContext,
    CacheProtocol,
    DateTimeRangeProtocol,
    EncounterDetailResult,
    EncounterDTO,
    EncounterIndexItem,
    EncounterIndexResult,
    EnrollmentConfigDTO,
    EnrollmentConfigRepositoryProtocol,
    EventDTO,
    EventStatsData,
    FacilitatorData,
    FacilitatorDTO,
    FacilitatorMergeError,
    HostPersonalDataEntry,
    MembershipAPIError,
    NotFoundError,
    PanelStatsDTO,
    PersonalFieldRequirementDTO,
    ProposalCategoryDTO,
    ProposeSessionResult,
    RequestContext,
    SessionData,
    SessionDTO,
    SessionFieldRequirementDTO,
    SessionFieldValueData,
    SessionStatus,
    SessionUpdateData,
    TicketAPIProtocol,
    TimeSlotRequirementDTO,
    TrackDTO,
    UnitOfWorkProtocol,
    UserData,
    UserDTO,
    UserEnrollmentConfigData,
    UserEnrollmentConfigDTO,
    UserRepositoryProtocol,
    UserType,
    VirtualEnrollmentConfig,
    WizardData,
)
from ludamus.specs.encounter import ENCOUNTER_DEFAULT_DURATION
from ludamus.specs.proposal import PROPOSAL_RATE_LIMIT_SECONDS

_BASE62_CHARS = string.ascii_letters + string.digits
_ALLOWED_MARKDOWN_TAGS = frozenset(
    {
        "a",
        "blockquote",
        "br",
        "code",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "strong",
        "ul",
    }
)
_VOID_MARKDOWN_TAGS = frozenset({"br", "hr"})
_ALLOWED_LINK_SCHEMES = frozenset({"", "http", "https", "mailto"})


def generate_share_code(length: int = 6) -> str:
    return "".join(_secret_choice(_BASE62_CHARS) for _ in range(length))


def _is_safe_markdown_url(url: str) -> bool:
    trimmed_url = "".join(char for char in url.strip() if char > " ")
    return urlsplit(trimmed_url).scheme.lower() in _ALLOWED_LINK_SCHEMES


def _sanitize_markdown_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    if tag != "a":
        return ""

    rendered_attrs = []
    for name, value in attrs:
        normalized_name = name.lower()
        if value is None or normalized_name not in {"href", "title"}:
            continue
        if normalized_name == "href" and not _is_safe_markdown_url(value):
            continue
        rendered_attrs.append(f'{normalized_name}="{_escape(value, quote=True)}"')

    if not rendered_attrs:
        return ""
    return f" {' '.join(rendered_attrs)}"


class _MarkdownSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in _ALLOWED_MARKDOWN_TAGS:
            return
        if normalized_tag in _VOID_MARKDOWN_TAGS:
            self._parts.append(f"<{normalized_tag}>")
            return

        rendered_attrs = _sanitize_markdown_attrs(normalized_tag, attrs)
        self._parts.append(f"<{normalized_tag}{rendered_attrs}>")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in _ALLOWED_MARKDOWN_TAGS - _VOID_MARKDOWN_TAGS:
            self._parts.append(f"</{normalized_tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in _ALLOWED_MARKDOWN_TAGS:
            return
        if normalized_tag in _VOID_MARKDOWN_TAGS:
            self._parts.append(f"<{normalized_tag}>")
            return

        rendered_attrs = _sanitize_markdown_attrs(normalized_tag, attrs)
        self._parts.append(f"<{normalized_tag}{rendered_attrs}></{normalized_tag}>")

    def handle_data(self, data: str) -> None:
        self._parts.append(_escape(data, quote=False))

    def html(self) -> str:
        return "".join(self._parts)


def _sanitize_markdown_html(value: str) -> str:
    sanitizer = _MarkdownSanitizer()
    sanitizer.feed(value)
    sanitizer.close()
    return sanitizer.html()


def render_markdown(text: str) -> str:
    result: str = _md.markdown(  # type: ignore [misc]
        text, extensions=["nl2br", "fenced_code"]
    )
    return _sanitize_markdown_html(result)


def generate_ics_content(encounter: EncounterDTO, url: str) -> str:
    def _ics_dt(dt: datetime) -> str:
        utc = dt.astimezone(UTC)
        return utc.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ludamus//Encounters//EN",
        "BEGIN:VEVENT",
        f"DTSTART:{_ics_dt(encounter.start_time)}",
    ]
    if encounter.end_time:
        lines.append(f"DTEND:{_ics_dt(encounter.end_time)}")
    lines.append(f"SUMMARY:{encounter.title}")
    if encounter.place:
        lines.append(f"LOCATION:{encounter.place}")
    if encounter.description:
        escaped = encounter.description.replace("\\", "\\\\").replace("\n", "\\n")
        lines.append(f"DESCRIPTION:{escaped}")
    lines.extend(
        [
            f"URL:{url}",
            f"UID:{encounter.share_code}@ludamus",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return "\r\n".join(lines)


def _gcal_dt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def google_calendar_url(encounter: EncounterDTO, url: str) -> str:
    end = encounter.end_time or (encounter.start_time + ENCOUNTER_DEFAULT_DURATION)
    params = {
        "action": "TEMPLATE",
        "text": encounter.title,
        "dates": f"{_gcal_dt(encounter.start_time)}/{_gcal_dt(end)}",
        "details": (
            f"{encounter.description}\n\n{url}" if encounter.description else url
        ),
    }
    if encounter.place:
        params["location"] = encounter.place
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"


def outlook_calendar_url(encounter: EncounterDTO, url: str) -> str:
    end = encounter.end_time or (encounter.start_time + ENCOUNTER_DEFAULT_DURATION)
    params = {
        "rru": "addevent",
        "subject": encounter.title,
        "startdt": encounter.start_time.astimezone(UTC).isoformat(),
        "enddt": end.astimezone(UTC).isoformat(),
        "body": f"{encounter.description}\n\n{url}" if encounter.description else url,
    }
    if encounter.place:
        params["location"] = encounter.place
    return f"https://outlook.live.com/calendar/0/action/compose?{urlencode(params)}"


class EncounterService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def build_detail(
        self, share_code: str, current_user_id: int | None
    ) -> EncounterDetailResult:
        encounter = self._uow.encounters.read_by_share_code(share_code)
        creator = self._uow.active_users.read_by_id(encounter.creator_id)
        rsvps = self._uow.encounter_rsvps.list_by_encounter(encounter.pk)
        rsvp_count = len(rsvps)
        is_full = (
            encounter.max_participants > 0 and rsvp_count >= encounter.max_participants
        )
        spots_remaining = (
            max(0, encounter.max_participants - rsvp_count)
            if encounter.max_participants > 0
            else None
        )
        user_has_rsvpd = (
            current_user_id is not None
            and self._uow.encounter_rsvps.user_has_rsvpd(encounter.pk, current_user_id)
        )
        return EncounterDetailResult(
            encounter=encounter,
            creator=creator,
            rsvps=rsvps,
            rsvp_count=rsvp_count,
            is_full=is_full,
            spots_remaining=spots_remaining,
            is_creator=current_user_id == encounter.creator_id,
            user_has_rsvpd=user_has_rsvpd,
        )

    def _resolve_creator_name(self, creator_id: int) -> str:
        try:
            user = self._uow.active_users.read_by_id(creator_id)
        except NotFoundError:
            return ""
        return user.full_name or user.name or user.username

    def build_index(self, sphere_id: int, user_id: int) -> EncounterIndexResult:
        my_upcoming = self._uow.encounters.list_upcoming_by_creator(sphere_id, user_id)
        rsvpd = self._uow.encounters.list_upcoming_rsvpd(sphere_id, user_id)
        my_ids = {e.pk for e in my_upcoming}

        upcoming = [
            EncounterIndexItem(
                encounter=e,
                rsvp_count=self._uow.encounter_rsvps.count_by_encounter(e.pk),
                is_mine=True,
                organizer_name="",
            )
            for e in my_upcoming
        ]
        upcoming.extend(
            EncounterIndexItem(
                encounter=e,
                rsvp_count=self._uow.encounter_rsvps.count_by_encounter(e.pk),
                is_mine=False,
                organizer_name=self._resolve_creator_name(e.creator_id),
            )
            for e in rsvpd
            if e.pk not in my_ids
        )
        upcoming.sort(key=lambda x: x.encounter.start_time)

        past_dtos = self._uow.encounters.list_past(sphere_id, user_id)
        past = [
            EncounterIndexItem(
                encounter=e,
                rsvp_count=self._uow.encounter_rsvps.count_by_encounter(e.pk),
                is_mine=e.creator_id == user_id,
                organizer_name=(
                    ""
                    if e.creator_id == user_id
                    else self._resolve_creator_name(e.creator_id)
                ),
            )
            for e in past_dtos
        ]

        return EncounterIndexResult(upcoming=upcoming, past=past)


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def is_proposal_active(event: EventDTO) -> bool:
    """Check if proposals are currently open for an event.

    Returns:
        True if the event is published and current time is within
        the proposal submission window.
        False if the event is unpublished or proposal times are not set.
    """
    now = datetime.now(tz=UTC)
    if event.publication_time is None or event.publication_time > now:
        return False
    if event.proposal_start_time is None or event.proposal_end_time is None:
        return False
    return event.proposal_start_time <= now <= event.proposal_end_time


def get_days_to_event(event: EventDTO) -> int:
    """Calculate days remaining until the event starts.

    Returns:
        Number of days until event start, minimum 0.
    """
    now = datetime.now(tz=UTC)
    delta = event.start_time - now
    return max(0, delta.days)


class ProposeSessionService:
    def __init__(self, uow: UnitOfWorkProtocol, context: RequestContext) -> None:
        self._uow = uow
        self._context = context

    @staticmethod
    def _generate_unique_slug(title: str, exists: Callable[[str], bool]) -> str:
        value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
        base_slug = re.sub(r"[^\w\s-]", "", value.lower())
        base_slug = re.sub(r"[-\s]+", "-", base_slug).strip("-")
        slug = base_slug
        for _ in range(4):
            if not exists(slug):
                break
            slug = f"{base_slug}-{token_urlsafe(3)}"
        return slug

    def get_event(self, slug: str) -> EventDTO:
        return self._uow.events.read_by_slug(slug, self._context.current_sphere_id)

    def get_categories(self, event_id: int) -> list[ProposalCategoryDTO]:
        return self._uow.proposal_categories.list_by_event(event_id)

    def get_category(self, pk: int, event_id: int) -> ProposalCategoryDTO:
        return self._uow.proposal_categories.read(pk, event_id)

    def get_personal_requirements(
        self, category_id: int
    ) -> list[PersonalFieldRequirementDTO]:
        return self._uow.proposal_categories.list_personal_field_requirements(
            category_id
        )

    def get_session_requirements(
        self, category_id: int
    ) -> list[SessionFieldRequirementDTO]:
        return self._uow.proposal_categories.list_session_field_requirements(
            category_id
        )

    def get_timeslot_requirements(
        self, category_id: int
    ) -> list[TimeSlotRequirementDTO]:
        return self._uow.proposal_categories.list_time_slot_requirements(category_id)

    def get_public_tracks(self, event_id: int) -> list[TrackDTO]:
        return self._uow.tracks.list_public_by_event(event_id)

    def get_saved_personal_data(
        self, event_id: int
    ) -> dict[str, str | list[str] | bool]:
        if (user_id := self._context.current_user_id) is None:
            return {}
        try:
            facilitator = self._uow.facilitators.read_by_user_and_event(
                user_id, event_id
            )
        except NotFoundError:
            return {}
        return self._uow.host_personal_data.read_for_facilitator_event(
            facilitator.pk, event_id
        )

    def _find_or_create_facilitator(
        self, event: EventDTO, display_name: str
    ) -> FacilitatorDTO:
        if (user_id := self._context.current_user_id) is not None:
            try:
                return self._uow.facilitators.read_by_user_and_event(user_id, event.pk)
            except NotFoundError:
                pass
        # Anonymous submissions are never merged: each submit creates a fresh
        # Facilitator row. Organizers reconcile later if needed.
        slug = self._generate_unique_slug(
            display_name, lambda s: self._uow.facilitators.slug_exists(event.pk, s)
        )
        return self._uow.facilitators.create(
            FacilitatorData(
                event_id=event.pk, user_id=user_id, display_name=display_name, slug=slug
            )
        )

    def submit(self, event: EventDTO, wizard_data: WizardData) -> ProposeSessionResult:
        session_data = wizard_data.get("session_data", {})
        if "title" not in session_data:
            msg = "session_data must contain 'title'"
            raise ValueError(msg)
        title = str(session_data["title"])
        description = str(session_data.get("description", ""))
        raw_limit = session_data.get("participants_limit") or 0
        participants_limit = int(str(raw_limit))
        category_id = wizard_data["category_id"]
        time_slot_ids = wizard_data.get("time_slot_ids", [])

        if (
            self._context.current_user_id is not None
            and self._context.current_user_slug is not None
        ):
            current_user = self._uow.active_users.read(self._context.current_user_slug)
            default_display_name = current_user.name
            presenter_id = current_user.pk
        else:
            default_display_name = ""
            presenter_id = None

        display_name = str(session_data.get("display_name", default_display_name))
        slug = self._generate_unique_slug(
            title, lambda s: self._uow.sessions.slug_exists(event.sphere_id, s)
        )

        with self._uow.atomic():
            facilitator = self._find_or_create_facilitator(event, display_name)

            create_data = SessionData(
                sphere_id=event.sphere_id,
                presenter_id=presenter_id,
                display_name=display_name,
                category_id=category_id,
                title=title,
                slug=slug,
                description=description,
                requirements="",
                needs="",
                duration=str(session_data.get("duration") or ""),
                participants_limit=participants_limit,
                min_age=int(str(session_data.get("min_age") or 0)),
                contact_email=wizard_data.get("contact_email", ""),
                status=SessionStatus.PENDING,
            )

            session_id = self._uow.sessions.create(
                create_data,
                tag_ids=[],
                time_slot_ids=time_slot_ids,
                facilitator_ids=[facilitator.pk],
            )

            self._save_session_field_values(session_id, event.pk, session_data)

            if personal_data := wizard_data.get("personal_data", {}):
                self._save_personal_data(event.pk, personal_data, facilitator)

            if track_pks := wizard_data.get("track_pks", []):
                self._uow.sessions.set_session_tracks(session_id, track_pks)

        return ProposeSessionResult(session_id=session_id, title=title)

    def _save_session_field_values(
        self, session_id: int, event_id: int, session_data: object
    ) -> None:
        data = session_data if isinstance(session_data, dict) else {}  # type: ignore [misc]
        values: list[SessionFieldValueData] = []
        for key, value in data.items():
            if not isinstance(key, str) or not key.startswith("session_"):
                continue
            slug = key.removeprefix("session_")
            if slug.endswith("_custom"):
                continue
            try:
                field_dto = self._uow.session_fields.read_by_slug(event_id, slug)
            except NotFoundError:
                continue
            values.append(
                SessionFieldValueData(
                    session_id=session_id, field_id=field_dto.pk, value=value
                )
            )
        if values:
            self._uow.sessions.save_field_values(session_id, values)

    def _save_personal_data(
        self, event_id: int, personal_data: dict[str, str], facilitator: FacilitatorDTO
    ) -> None:
        entries: list[HostPersonalDataEntry] = []
        for key, value in personal_data.items():
            if not key.startswith("personal_"):
                continue
            slug = key.removeprefix("personal_")
            if slug.endswith("_custom"):
                continue
            try:
                field_dto = self._uow.personal_data_fields.read_by_slug(event_id, slug)
            except NotFoundError:
                continue
            entries.append(
                HostPersonalDataEntry(
                    facilitator_id=facilitator.pk,
                    event_id=event_id,
                    field_id=field_dto.pk,
                    value=value,
                )
            )
        if entries:
            self._uow.host_personal_data.save(entries)


def check_proposal_rate_limit(cache: CacheProtocol, ip: str, event_id: int) -> bool:
    """Check if an IP is rate-limited for proposal submission on an event.

    Returns:
        True if the submission is allowed, False if rate-limited.
    """
    key = f"proposal_rate:{event_id}:{ip}"
    if cache.get(key) is not None:
        return False
    cache.set(key, 1, timeout=PROPOSAL_RATE_LIMIT_SECONDS)
    return True


class AnonymousEnrollmentService:
    SLUG_TEMPLATE = "code_{code}"

    def __init__(self, user_repository: UserRepositoryProtocol) -> None:
        self._user_repository = user_repository

    def get_user_by_code(self, code: str) -> UserDTO:
        slug = self.SLUG_TEMPLATE.format(code=code)
        user = self._user_repository.read(slug)
        return UserDTO.model_validate(user)

    def build_user(self, code: str) -> UserData:
        return UserData(
            username=f"anon_{token_urlsafe(8).lower()}",
            slug=self.SLUG_TEMPLATE.format(code=code),
            user_type=UserType.ANONYMOUS,
            is_active=False,
        )


class AcceptProposalService:
    def __init__(
        self, uow: UnitOfWorkProtocol, context: AuthenticatedRequestContext
    ) -> None:
        self._uow = uow
        self._context = context

    def can_accept_proposals(self) -> bool:
        user = self._uow.active_users.read(self._context.current_user_slug)
        if user.is_superuser or user.is_staff:
            return True

        return self._uow.spheres.is_manager(
            self._context.current_sphere_id, self._context.current_user_slug
        )

    def accept_session(
        self,
        *,
        session: SessionDTO,
        slugifier: Callable[[str], str],
        space_id: int,
        time_slot_id: int,
    ) -> None:
        time_slot = self._uow.sessions.read_time_slot(session.pk, time_slot_id)

        with self._uow.atomic():
            self._uow.sessions.update(
                session.pk,
                SessionUpdateData(
                    status=SessionStatus.SCHEDULED,
                    display_name=session.display_name,
                    slug=slugifier(session.title),
                ),
            )

            self._uow.agenda_items.create(
                AgendaItemData(
                    space_id=space_id,
                    session_id=session.pk,
                    session_confirmed=True,
                    start_time=time_slot.start_time,
                    end_time=time_slot.end_time,
                )
            )


class PanelService:
    """Service for backoffice panel business logic."""

    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def delete_category(self, category_pk: int) -> bool:
        """Delete a proposal category if it has no proposals.

        Args:
            category_pk: The category primary key.

        Returns:
            True if deleted, False if category has proposals.
        """
        if self._uow.proposal_categories.has_proposals(category_pk):
            return False
        self._uow.proposal_categories.delete(category_pk)
        return True

    def delete_session_field(self, field_pk: int) -> bool:
        """Delete a session field if not used by session types.

        Args:
            field_pk: The field primary key.

        Returns:
            True if deleted, False if field has requirements.
        """
        if self._uow.session_fields.has_requirements(field_pk):
            return False
        self._uow.session_fields.delete(field_pk)
        return True

    def delete_venue(self, venue_pk: int) -> bool:
        """Delete a venue if it has no scheduled sessions.

        Args:
            venue_pk: The venue primary key.

        Returns:
            True if deleted, False if venue has sessions.
        """
        if self._uow.venues.has_sessions(venue_pk):
            return False
        self._uow.venues.delete(venue_pk)
        return True

    def delete_area(self, area_pk: int) -> bool:
        """Delete an area if it has no scheduled sessions in any space.

        Args:
            area_pk: The area primary key.

        Returns:
            True if deleted, False if area has sessions.
        """
        if self._uow.areas.has_sessions(area_pk):
            return False
        self._uow.areas.delete(area_pk)
        return True

    def delete_time_slot(self, time_slot_pk: int) -> bool:
        """Delete a time slot if not used in any proposals.

        Args:
            time_slot_pk: The time slot primary key.

        Returns:
            True if deleted, False if time slot has proposals.
        """
        if self._uow.time_slots.has_proposals(time_slot_pk):
            return False
        self._uow.time_slots.delete(time_slot_pk)
        return True

    def delete_space(self, space_pk: int) -> bool:
        """Delete a space if it has no scheduled sessions.

        Args:
            space_pk: The space primary key.

        Returns:
            True if deleted, False if space has sessions.
        """
        if self._uow.spaces.has_sessions(space_pk):
            return False
        self._uow.spaces.delete(space_pk)
        return True

    def get_event_stats(self, event_id: int) -> PanelStatsDTO:
        """Calculate panel statistics for an event.

        Args:
            event_id: The event ID to get stats for.

        Returns:
            PanelStatsDTO with computed statistics.
        """
        stats_data: EventStatsData = self._uow.events.get_stats_data(event_id)

        # Business logic: total sessions = pending + scheduled
        total_sessions = stats_data.pending_proposals + stats_data.scheduled_sessions

        return PanelStatsDTO(
            total_sessions=total_sessions,
            scheduled_sessions=stats_data.scheduled_sessions,
            pending_proposals=stats_data.pending_proposals,
            hosts_count=len(stats_data.unique_host_ids),
            rooms_count=stats_data.rooms_count,
            total_proposals=stats_data.total_proposals,
        )

    @staticmethod
    def validate_time_slot(
        start: datetime,
        end: datetime,
        event: EventDTO,
        existing_slots: Sequence[DateTimeRangeProtocol],
    ) -> list[str]:
        errors: list[str] = []

        if start >= end:
            errors.append("Start must be before end.")

        if start < event.start_time or end > event.end_time:
            errors.append("Time slot must be within event dates.")

        for slot in existing_slots:
            if start < slot.end_time and end > slot.start_time:
                errors.append("Time slot overlaps with an existing slot.")
                break

        return errors


def _refresh_user_config_from_api(
    *,
    user_config: UserEnrollmentConfigDTO,
    ticket_api: TicketAPIProtocol,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
) -> UserEnrollmentConfigDTO | None:
    try:
        membership_count = ticket_api.fetch_membership_count(user_config.user_email)
    except MembershipAPIError:
        return user_config

    current_time = datetime.now(tz=UTC)

    # Update config with fresh data
    if membership_count == 0:
        user_config.allowed_slots = 0
        user_config.last_check = current_time
        enrollment_config_repo.update_user_config(user_config)
        return None  # Return None since user has no slots

    user_config.allowed_slots = membership_count
    user_config.last_check = current_time
    enrollment_config_repo.update_user_config(user_config)
    return user_config


def _create_user_config_from_api(
    *,
    enrollment_config: EnrollmentConfigDTO,
    user_email: str,
    ticket_api: TicketAPIProtocol,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
) -> UserEnrollmentConfigDTO | None:

    try:
        membership_count = ticket_api.fetch_membership_count(user_email)
    except MembershipAPIError:
        return None

    current_time = datetime.now(tz=UTC)
    # User has membership - create config with slots based on membership count
    # You can customize this logic based on your business rules
    return enrollment_config_repo.create_user_config(
        UserEnrollmentConfigData(
            enrollment_config_id=enrollment_config.pk,
            user_email=user_email,
            allowed_slots=membership_count,
            fetched_from_api=True,
            last_check=current_time,
        )
    )


def get_or_create_user_enrollment_config(  # noqa: PLR0913
    *,
    enrollment_config: EnrollmentConfigDTO,
    user_email: str,
    ticket_api: TicketAPIProtocol,
    check_interval_minutes: int,
    existing_user_config: UserEnrollmentConfigDTO | None,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
) -> UserEnrollmentConfigDTO | None:
    if existing_user_config:
        # If config has slots > 0, it's final - no need to refresh
        if existing_user_config.allowed_slots > 0:
            return existing_user_config

        # Only refresh configs with 0 slots, and only if enough time has passed
        time_threshold = datetime.now(tz=UTC) - timedelta(
            minutes=check_interval_minutes
        )

        if (
            not existing_user_config.last_check
            or existing_user_config.last_check < time_threshold
        ):
            # Update the existing config with fresh API data
            return _refresh_user_config_from_api(
                user_config=existing_user_config,
                ticket_api=ticket_api,
                enrollment_config_repo=enrollment_config_repo,
            )

        # Config has 0 slots
        return None

    return _create_user_config_from_api(
        enrollment_config=enrollment_config,
        user_email=user_email,
        ticket_api=ticket_api,
        enrollment_config_repo=enrollment_config_repo,
    )


def get_user_enrollment_config(
    *,
    event: EventDTO,
    user_email: str,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
    ticket_api: TicketAPIProtocol,
    check_interval_minutes: int,
) -> VirtualEnrollmentConfig | None:
    virtual_config = VirtualEnrollmentConfig()

    now = datetime.now(tz=UTC)
    for config in enrollment_config_repo.read_list(
        event.pk, max_start_time=now, min_end_time=now
    ):
        existing_user_config = enrollment_config_repo.read_user_config(
            config, user_email
        )
        # Check for explicit user config
        if api_user_config := get_or_create_user_enrollment_config(
            enrollment_config=config,
            user_email=user_email,
            ticket_api=ticket_api,
            check_interval_minutes=check_interval_minutes,
            existing_user_config=existing_user_config,
            enrollment_config_repo=enrollment_config_repo,
        ):
            # Try to fetch from API if not found locally
            virtual_config.allowed_slots += api_user_config.allowed_slots
            virtual_config.has_user_config = True
        elif existing_user_config:
            virtual_config.allowed_slots += existing_user_config.allowed_slots
            virtual_config.has_user_config = True

        # Always check for domain-based access regardless of individual config
        email_domain = (
            user_email.split("@")[1] if (user_email and "@" in user_email) else ""
        )
        if email_domain and (
            domain_config := enrollment_config_repo.read_domain_config(
                config, email_domain
            )
        ):
            virtual_config.allowed_slots += domain_config.allowed_slots_per_user
            virtual_config.has_domain_config = True

    return (
        virtual_config
        if (virtual_config.has_user_config or virtual_config.has_domain_config)
        else None
    )


class FacilitatorMergeService:
    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def merge(self, target_id: int, source_ids: list[int]) -> None:
        if not source_ids:
            msg = "At least one source facilitator is required"
            raise FacilitatorMergeError(msg)
        if target_id in source_ids:
            msg = "Target cannot be among source facilitators"
            raise FacilitatorMergeError(msg)

        all_ids = [target_id, *source_ids]
        linked_count = sum(
            1 for fid in all_ids if self._uow.facilitators.read(fid).user_id is not None
        )
        if linked_count > 1:
            msg = "Cannot merge facilitators that each have a linked user account."
            raise FacilitatorMergeError(msg)

        with self._uow.atomic():
            self._uow.sessions.replace_facilitators_in_sessions(source_ids, target_id)
            self._uow.host_personal_data.delete_by_facilitators(source_ids)
            for source_id in source_ids:
                self._uow.facilitators.delete(source_id)
