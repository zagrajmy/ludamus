import string
from datetime import UTC, datetime
from secrets import choice as _secret_choice
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import markdown as _md
import nh3

from ludamus.mills.submissions.mapping import generate_unique_slug
from ludamus.pacts import (
    CacheProtocol,
    DateTimeRangeProtocol,
    EncounterDetailResult,
    EncounterDTO,
    EncounterIndexItem,
    EncounterIndexResult,
    EventDTO,
    EventStatsData,
    FacilitatorData,
    FacilitatorDTO,
    FacilitatorMergeError,
    NotFoundError,
    PanelStatsDTO,
    PersonalDataFieldValueData,
    PersonalFieldRequirementDTO,
    ProposalCategoryDTO,
    ProposeSessionResult,
    RequestContext,
    ReusableSessionDTO,
    SessionData,
    SessionFieldRequirementDTO,
    SessionFieldValueData,
    SessionStatus,
    TimeSlotRequirementDTO,
    TrackDTO,
    UnitOfWorkProtocol,
    UploadedFileProtocol,
    WizardData,
)
from ludamus.specs.encounter import ENCOUNTER_DEFAULT_DURATION
from ludamus.specs.proposal import PROPOSAL_RATE_LIMIT_SECONDS

_BASE62_CHARS = string.ascii_letters + string.digits


def generate_share_code(length: int = 6) -> str:
    return "".join(_secret_choice(_BASE62_CHARS) for _ in range(length))


_MARKDOWN_ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
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
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
_MARKDOWN_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "abbr": {"title"}}


def render_markdown(text: str) -> str:
    result: str = _md.markdown(  # type: ignore [misc]
        text, extensions=["nl2br", "fenced_code"]
    )
    return nh3.clean(
        result, tags=_MARKDOWN_ALLOWED_TAGS, attributes=_MARKDOWN_ALLOWED_ATTRIBUTES
    )


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


class ProposeSessionService:
    def __init__(self, uow: UnitOfWorkProtocol, context: RequestContext) -> None:
        self._uow = uow
        self._context = context

    @staticmethod
    def _generate_unique_slug(title: str, exists: Callable[[str], bool]) -> str:
        return generate_unique_slug(title, exists)

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
        return self._uow.personal_data_field_values.read_for_facilitator_event(
            facilitator.pk, event_id
        )

    def list_reusable_sessions(self, event_id: int) -> list[ReusableSessionDTO]:
        if (user_id := self._context.current_user_id) is None:
            return []
        return self._uow.sessions.list_reusable_for_user(
            user_id=user_id, exclude_event_id=event_id
        )

    def get_session_prefill(
        self, source_session_id: int, category: ProposalCategoryDTO
    ) -> dict[str, object] | None:
        # Prefill the details step from a session the current user proposed
        # before. Only content that survives a move to a different event is
        # carried: the free-text/limits, plus dynamic answers whose field slug
        # the target category actually asks for. Duration is kept only if this
        # category offers it as a choice.
        if (user_id := self._context.current_user_id) is None:
            return None
        try:
            session = self._uow.sessions.read(source_session_id)
        except NotFoundError:
            return None
        if session.presenter_id != user_id:
            return None
        data: dict[str, object] = {
            "title": session.title,
            "description": session.description,
            "display_name": session.display_name,
            "participants_limit": session.participants_limit,
            "min_age": session.min_age,
        }
        if session.duration and session.duration in category.durations:
            data["duration"] = session.duration
        requirement_slugs = {
            req.field.slug
            for req in self._uow.proposal_categories.list_session_field_requirements(
                category.pk
            )
        }
        for value in self._uow.sessions.read_field_values(source_session_id):
            if value.field_slug in requirement_slugs:
                data[f"session_{value.field_slug}"] = value.value
        return data

    def _find_or_create_facilitator(
        self, event: EventDTO, display_name: str
    ) -> FacilitatorDTO:
        if (user_id := self._context.current_user_id) is not None:
            try:
                return self._uow.facilitators.read_by_user_and_event(user_id, event.pk)
            except NotFoundError:
                pass
        slug = self._generate_unique_slug(
            display_name, lambda s: self._uow.facilitators.slug_exists(event.pk, s)
        )
        return self._uow.facilitators.create(
            FacilitatorData(
                event_id=event.pk, user_id=user_id, display_name=display_name, slug=slug
            )
        )

    def submit(
        self,
        event: EventDTO,
        wizard_data: WizardData,
        *,
        cover_image: UploadedFileProtocol | None = None,
    ) -> ProposeSessionResult:
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
            title, lambda s: self._uow.sessions.slug_exists(event.pk, s)
        )

        with self._uow.atomic():
            facilitator = self._find_or_create_facilitator(event, display_name)

            create_data = SessionData(
                event_id=event.pk,
                presenter_id=presenter_id,
                display_name=display_name,
                category_id=category_id,
                title=title,
                slug=slug,
                description=description,
                duration=str(session_data.get("duration") or ""),
                participants_limit=participants_limit,
                min_age=int(str(session_data.get("min_age") or 0)),
                contact_email=wizard_data.get("contact_email", ""),
                status=SessionStatus.PENDING,
            )
            if cover_image:
                create_data["cover_image"] = cover_image

            session_id = self._uow.sessions.create(
                create_data,
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
        entries: list[PersonalDataFieldValueData] = []
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
                PersonalDataFieldValueData(
                    facilitator_id=facilitator.pk,
                    event_id=event_id,
                    field_id=field_dto.pk,
                    value=value,
                )
            )
        if entries:
            self._uow.personal_data_field_values.save(entries)


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

    def get_event_stats(self, event_id: int) -> PanelStatsDTO:
        """Calculate panel statistics for an event.

        Args:
            event_id: The event ID to get stats for.

        Returns:
            PanelStatsDTO with computed statistics.
        """
        stats_data: EventStatsData = self._uow.events.get_stats_data(event_id)

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
            self._uow.personal_data_field_values.delete_by_facilitators(source_ids)
            for source_id in source_ids:
                self._uow.facilitators.delete(source_id)
