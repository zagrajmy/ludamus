import json
import re
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Literal, cast  # pylint: disable=unused-import

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.text import slugify

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Area,
    Connection,
    DomainEnrollmentConfig,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    EventProposalSettings,
    EventSettings,
    Facilitator,
    HostPersonalData,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    SessionFieldValue,
    Space,
    Sphere,
    Tag,
    TimeSlot,
    TimeSlotRequirement,
    Track,
    UserEnrollmentConfig,
    Venue,
)
from ludamus.pacts import (
    UNSCHEDULED_LIST_LIMIT,
    AreaDTO,
    AreaRepositoryProtocol,
    CategoryStats,
    ConnectedUserRepositoryProtocol,
    DomainEnrollmentConfigDTO,
    EncounterData,
    EncounterDTO,
    EncounterRepositoryProtocol,
    EncounterRSVPDTO,
    EncounterRSVPRepositoryProtocol,
    EnrollmentConfigDTO,
    EnrollmentConfigRepositoryProtocol,
    EventDTO,
    EventProposalSettingsDTO,
    EventProposalSettingsRepositoryProtocol,
    EventRepositoryProtocol,
    EventSettingsDTO,
    EventSettingsRepositoryProtocol,
    EventStatsData,
    EventUpdateData,
    FacilitatorData,
    FacilitatorDTO,
    FacilitatorListItemDTO,
    FacilitatorRepositoryProtocol,
    FacilitatorUpdateData,
    HostPersonalDataEntry,
    HostPersonalDataRepositoryProtocol,
    NotFoundError,
    PendingSessionDTO,
    PendingSessionTagDTO,
    PendingSessionTimeSlotDTO,
    PersonalDataFieldCreateData,
    PersonalDataFieldDTO,
    PersonalDataFieldOptionDTO,
    PersonalDataFieldRepositoryProtocol,
    PersonalDataFieldUpdateData,
    PersonalFieldRequirementDTO,
    ProposalCategoryData,
    ProposalCategoryDTO,
    ProposalCategoryRepositoryProtocol,
    SessionData,
    SessionDTO,
    SessionFieldCreateData,
    SessionFieldDTO,
    SessionFieldOptionDTO,
    SessionFieldRepositoryProtocol,
    SessionFieldRequirementDTO,
    SessionFieldUpdateData,
    SessionFieldValueData,
    SessionFieldValueDTO,
    SessionListItemDTO,
    SessionRepositoryProtocol,
    SessionStatus,
    SessionUpdateData,
    SiteDTO,
    SpaceDTO,
    SpaceRepositoryProtocol,
    SphereDTO,
    SphereRepositoryProtocol,
    TagCategoryDTO,
    TagDTO,
    TimeSlotDTO,
    TimeSlotRepositoryProtocol,
    TimeSlotRequirementDTO,
    TrackCreateData,
    TrackDTO,
    TrackRepositoryProtocol,
    TrackUpdateData,
    UnscheduledSessionDTO,
    UserData,
    UserDTO,
    UserEnrollmentConfigData,
    UserEnrollmentConfigDTO,
    UserRepositoryProtocol,
    UserType,
    VenueDTO,
    VenueRepositoryProtocol,
)
from ludamus.pacts.multiverse import (
    CheckResult,
    ConnectionDTO,
    ConnectionsRepositoryProtocol,
    ConnectionWriteDict,
    DuplicateConnectionDisplayNameError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()

_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")


def _parse_iso8601_duration_minutes(duration: str) -> int:
    if not (m := _ISO8601_DURATION_RE.match(duration)):
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


class SphereRepository(SphereRepositoryProtocol):
    @staticmethod
    def read_by_domain(domain: str) -> SphereDTO:
        try:
            sphere = Sphere.objects.get(site__domain=domain)
        except Sphere.DoesNotExist as exception:
            raise NotFoundError from exception

        return SphereDTO.model_validate(sphere)

    @staticmethod
    def read(pk: int) -> SphereDTO:
        try:
            sphere = Sphere.objects.select_related("site").get(id=pk)
        except Sphere.DoesNotExist as exception:
            raise NotFoundError from exception

        return SphereDTO.model_validate(sphere)

    @staticmethod
    def read_site(sphere_id: int) -> SiteDTO:
        sphere = Sphere.objects.select_related("site").get(id=sphere_id)
        return SiteDTO.model_validate(sphere.site)

    @staticmethod
    def is_manager(sphere_id: int, user_slug: str) -> bool:
        return Sphere.objects.filter(id=sphere_id, managers__slug=user_slug).exists()

    @staticmethod
    def list_managers(sphere_id: int) -> list[UserDTO]:
        try:
            sphere = Sphere.objects.get(pk=sphere_id)
        except Sphere.DoesNotExist as err:
            raise NotFoundError from err
        return [UserDTO.model_validate(u) for u in sphere.managers.order_by("name")]


class UserRepository(UserRepositoryProtocol):
    def __init__(self, user_type: UserType) -> None:
        self._user_type = user_type

    @staticmethod
    def create(user_data: UserData) -> None:
        User.objects.create(**user_data)

    def read(self, slug: str) -> UserDTO:
        try:
            user = User.objects.get(slug=slug, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception

        return UserDTO.model_validate(user)

    def read_by_id(self, pk: int) -> UserDTO:
        try:
            user = User.objects.get(pk=pk, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(user)

    def read_by_username(self, username: str) -> UserDTO:
        try:
            user = User.objects.get(username=username, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(user)

    @staticmethod
    def update(user_slug: str, user_data: UserData) -> None:
        User.objects.filter(slug=user_slug).update(**user_data)

    @staticmethod
    def email_exists(email: str, exclude_slug: str | None = None) -> bool:
        if not email:
            return False

        query = User.objects.filter(email__iexact=email)
        if exclude_slug:
            query = query.exclude(slug=exclude_slug)

        return query.exists()


class SessionRepository(SessionRepositoryProtocol):  # noqa: PLR0904
    @staticmethod
    def create(
        session_data: SessionData,
        tag_ids: Iterable[int],
        time_slot_ids: Iterable[int] = (),
        facilitator_ids: Iterable[int] = (),
    ) -> int:
        session = Session.objects.create(**session_data)
        session.tags.set(tag_ids)
        if time_slot_ids:
            session.time_slots.set(time_slot_ids)
        if facilitator_ids:
            session.facilitators.set(facilitator_ids)
        return session.pk

    @staticmethod
    def read(pk: int) -> SessionDTO:
        try:
            session = Session.objects.select_related("category").get(id=pk)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        return SessionDTO.model_validate(session)

    @staticmethod
    def update(pk: int, data: SessionUpdateData) -> None:
        Session.objects.filter(id=pk).update(**data)

    @staticmethod
    def read_event(session_id: int) -> EventDTO:
        try:
            event = Event.objects.select_related("proposal_settings").get(
                proposal_categories__sessions__id=session_id
            )
        except Event.DoesNotExist as exception:
            raise NotFoundError from exception
        return _event_dto(event)

    @staticmethod
    def read_spaces(session_id: int) -> list[SpaceDTO]:
        spaces = Space.objects.filter(
            area__venue__event__proposal_categories__sessions__id=session_id
        )
        return [SpaceDTO.model_validate(space) for space in spaces]

    @staticmethod
    def read_time_slots(session_id: int) -> list[TimeSlotDTO]:
        time_slots = TimeSlot.objects.filter(
            event__proposal_categories__sessions__id=session_id
        )
        return [TimeSlotDTO.model_validate(ts) for ts in time_slots]

    @staticmethod
    def read_time_slot(session_id: int, time_slot_id: int) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(
                id=time_slot_id, event__proposal_categories__sessions__id=session_id
            )
        except TimeSlot.DoesNotExist as exception:
            raise NotFoundError from exception
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def read_tag_ids(session_id: int) -> list[int]:
        return list(
            Tag.objects.filter(session__id=session_id).values_list("id", flat=True)
        )

    @staticmethod
    def read_tags(session_id: int) -> list[TagDTO]:
        session = Session.objects.get(id=session_id)
        return [TagDTO.model_validate(tag) for tag in session.tags.all()]

    @staticmethod
    def read_tag_categories(session_id: int) -> list[TagCategoryDTO]:
        try:
            session = Session.objects.select_related("category").get(id=session_id)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        if session.category is None:
            return []
        return [
            TagCategoryDTO.model_validate(tc)
            for tc in session.category.tag_categories.all()
        ]

    @staticmethod
    def count_by_category(category_id: int) -> int:
        return Session.objects.filter(category_id=category_id).count()

    @staticmethod
    def read_pending_by_event(event_id: int) -> list[PendingSessionDTO]:
        sessions = (
            Session.objects.filter(
                category__event_id=event_id, status=SessionStatus.PENDING
            )
            .prefetch_related("tags", "time_slots")
            .order_by("-creation_time")
        )
        return [
            PendingSessionDTO(
                contact_email=s.contact_email,
                creation_time=s.creation_time,
                description=s.description,
                needs=s.needs,
                participants_limit=s.participants_limit,
                pk=s.pk,
                display_name=s.display_name,
                requirements=s.requirements,
                tags=[PendingSessionTagDTO.model_validate(t) for t in s.tags.all()],
                time_slots=[
                    PendingSessionTimeSlotDTO.model_validate(ts)
                    for ts in s.time_slots.all()
                ],
                title=s.title,
            )
            for s in sessions
        ]

    @staticmethod
    def read_pending_by_event_for_user(
        event_id: int, presenter_id: int
    ) -> list[PendingSessionDTO]:
        sessions = (
            Session.objects.filter(
                category__event_id=event_id,
                status=SessionStatus.PENDING,
                presenter_id=presenter_id,
            )
            .prefetch_related("tags", "time_slots")
            .order_by("-creation_time")
        )
        return [
            PendingSessionDTO(
                contact_email=s.contact_email,
                creation_time=s.creation_time,
                description=s.description,
                needs=s.needs,
                participants_limit=s.participants_limit,
                pk=s.pk,
                display_name=s.display_name,
                requirements=s.requirements,
                tags=[PendingSessionTagDTO.model_validate(t) for t in s.tags.all()],
                time_slots=[
                    PendingSessionTimeSlotDTO.model_validate(ts)
                    for ts in s.time_slots.all()
                ],
                title=s.title,
            )
            for s in sessions
        ]

    @staticmethod
    def read_preferred_time_slot_ids(session_id: int) -> list[int]:
        return list(
            TimeSlot.objects.filter(session__id=session_id).values_list("id", flat=True)
        )

    @staticmethod
    def read_preferred_time_slots(session_id: int) -> list[TimeSlotDTO]:
        time_slots = TimeSlot.objects.filter(session__id=session_id)
        return [TimeSlotDTO.model_validate(ts) for ts in time_slots]

    @staticmethod
    def read_preferred_time_slots_by_sessions(
        session_ids: Iterable[int],
    ) -> dict[int, list[TimeSlotDTO]]:
        if not (ids := list(session_ids)):
            return {}
        rows = (
            Session.time_slots.through.objects.filter(session_id__in=ids)
            .select_related("timeslot")
            .values(
                "session_id",
                "timeslot__id",
                "timeslot__start_time",
                "timeslot__end_time",
            )
        )
        result: dict[int, list[TimeSlotDTO]] = {sid: [] for sid in ids}
        for row in rows:
            result[row["session_id"]].append(
                TimeSlotDTO(
                    pk=row["timeslot__id"],
                    start_time=row["timeslot__start_time"],
                    end_time=row["timeslot__end_time"],
                )
            )
        return result

    @staticmethod
    def slug_exists(sphere_id: int, slug: str) -> bool:
        return Session.objects.filter(sphere_id=sphere_id, slug=slug).exists()

    @staticmethod
    def save_field_values(session_id: int, values: list[SessionFieldValueData]) -> None:
        SessionFieldValue.objects.bulk_create(
            [
                SessionFieldValue(
                    session_id=session_id, field_id=v["field_id"], value=v["value"]
                )
                for v in values
            ]
        )

    @staticmethod
    def read_field_values(session_id: int) -> list[SessionFieldValueDTO]:
        values = (
            SessionFieldValue.objects.filter(session_id=session_id)
            .select_related("field")
            .order_by("field__order", "field__name")
        )
        return [
            SessionFieldValueDTO(
                allow_custom=v.field.allow_custom,
                field_icon=v.field.icon,
                field_id=v.field_id,
                field_name=v.field.name,
                field_order=v.field.order,
                field_question=v.field.question,
                field_slug=v.field.slug,
                field_type=v.field.field_type,
                is_public=v.field.is_public,
                value=v.value,
            )
            for v in values
        ]

    @staticmethod
    def list_sessions_by_event(
        event_id: int,
        *,
        field_filters: dict[int, str] | None = None,
        search: str | None = None,
        track_pk: int | None = None,
    ) -> list[SessionListItemDTO]:
        qs = Session.objects.filter(category__event_id=event_id).select_related(
            "presenter", "category"
        )

        if field_filters:
            for field_id, value in field_filters.items():
                qs = qs.filter(
                    field_values__field_id=field_id, field_values__value=value
                )

        if search:
            # SessionFieldValue.value is a JSONField. SQLite stores strings
            # JSON-encoded with ensure_ascii=True, so non-ASCII chars are
            # escaped (e.g. "przekleństwa"); Postgres jsonb cast to text keeps
            # literal Unicode. OR both forms so the lookup works on both.
            encoded = json.dumps(search)[1:-1]
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(presenter__name__icontains=search)
                | Q(field_values__value__icontains=search)
                | Q(field_values__value__icontains=encoded)
            ).distinct()

        if track_pk is not None:
            qs = qs.filter(tracks__pk=track_pk)

        return [
            SessionListItemDTO(
                pk=s.pk,
                title=s.title,
                display_name=s.display_name,
                category_name=s.category.name if s.category else "",
                status=SessionStatus(s.status),
                creation_time=s.creation_time,
            )
            for s in qs.order_by("-creation_time")
        ]

    @staticmethod
    def set_session_tracks(session_pk: int, track_pks: list[int]) -> None:
        try:
            session = Session.objects.get(pk=session_pk)
        except Session.DoesNotExist as err:
            msg = f"Session with pk '{session_pk}' not found"
            raise NotFoundError(msg) from err
        session.tracks.set(track_pks)

    @staticmethod
    def read_facilitators(session_id: int) -> list[FacilitatorDTO]:
        try:
            session = Session.objects.get(pk=session_id)
        except Session.DoesNotExist as err:
            msg = f"Session with pk '{session_id}' not found"
            raise NotFoundError(msg) from err
        return [FacilitatorDTO.model_validate(f) for f in session.facilitators.all()]

    @staticmethod
    def set_facilitators(session_id: int, facilitator_ids: list[int]) -> None:
        try:
            session = Session.objects.get(pk=session_id)
        except Session.DoesNotExist as err:
            msg = f"Session with pk '{session_id}' not found"
            raise NotFoundError(msg) from err
        session.facilitators.set(facilitator_ids)

    @staticmethod
    def replace_facilitators_in_sessions(source_ids: list[int], target_id: int) -> None:
        for session in Session.objects.filter(facilitators__in=source_ids).distinct():
            session.facilitators.add(target_id)
            session.facilitators.remove(*source_ids)

    @staticmethod
    def list_unscheduled_by_event(
        event_pk: int,
        *,
        track_pk: int | None = None,
        search: str | None = None,
        max_duration_minutes: int | None = None,
        category_pk: int | None = None,
    ) -> tuple[list[UnscheduledSessionDTO], bool]:
        qs = (
            Session.objects.filter(category__event_id=event_pk)
            .exclude(status=SessionStatus.REJECTED)
            .filter(agenda_item__isnull=True)
            .select_related("category")
        )
        if track_pk is not None:
            qs = qs.filter(tracks__pk=track_pk)
        if category_pk is not None:
            qs = qs.filter(category__pk=category_pk)
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(display_name__icontains=search)
            ).distinct()
        results: list[UnscheduledSessionDTO] = []
        has_more = False
        for s in qs.order_by("title").iterator():
            duration_minutes = _parse_iso8601_duration_minutes(s.duration)
            if (
                max_duration_minutes is not None
                and duration_minutes > max_duration_minutes
            ):
                continue
            if len(results) >= UNSCHEDULED_LIST_LIMIT:
                has_more = True
                break
            results.append(
                UnscheduledSessionDTO(
                    pk=s.pk,
                    title=s.title,
                    display_name=s.display_name,
                    category_name=s.category.name if s.category else "",
                    category_pk=s.category_id,
                    duration_minutes=duration_minutes,
                    participants_limit=s.participants_limit,
                )
            )
        return results, has_more


class ConnectedUserRepository(ConnectedUserRepositoryProtocol):
    @staticmethod
    def read_all(manager_slug: str) -> list[UserDTO]:
        try:
            manager = User.objects.get(user_type=UserType.ACTIVE, slug=manager_slug)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception

        return [
            UserDTO.model_validate(connected_user)
            for connected_user in manager.connected.all()
        ]

    @staticmethod
    def create(manager_slug: str, user_data: UserData) -> None:
        manager = User.objects.get(user_type=UserType.ACTIVE, slug=manager_slug)
        User.objects.create(manager=manager, **user_data)

    @staticmethod
    def read(manager_slug: str, user_slug: str) -> UserDTO:
        try:
            connected_user = User.objects.get(
                slug=user_slug, manager__slug=manager_slug
            )
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(connected_user)

    @staticmethod
    def update(manager_slug: str, user_slug: str, user_data: UserData) -> None:
        User.objects.filter(slug=user_slug, manager__slug=manager_slug).update(
            **user_data
        )

    @staticmethod
    def delete(manager_slug: str, user_slug: str) -> None:
        try:
            user = User.objects.get(slug=user_slug, manager__slug=manager_slug)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        user.delete()


def _event_dto(event: Event) -> EventDTO:
    settings = getattr(event, "proposal_settings", None)
    description = settings.description if settings is not None else ""
    dto = EventDTO.model_validate(event)
    return dto.model_copy(update={"proposal_description": description})


class EventRepository(EventRepositoryProtocol):
    @staticmethod
    def list_by_sphere(sphere_id: int) -> list[EventDTO]:
        """List all events for a sphere, ordered by start time descending.

        Returns:
            List of EventDTO objects for the sphere.
        """
        events = (
            Event.objects.filter(sphere_id=sphere_id)
            .select_related("proposal_settings")
            .order_by("-start_time")
        )
        return [_event_dto(event) for event in events]

    @staticmethod
    def read(pk: int) -> EventDTO:
        """Read an event by primary key.

        Returns:
            EventDTO for the requested event.

        Raises:
            NotFoundError: If the event does not exist.
        """
        try:
            event = Event.objects.select_related("proposal_settings").get(id=pk)
        except Event.DoesNotExist as exception:
            raise NotFoundError from exception
        return _event_dto(event)

    @staticmethod
    def read_by_slug(slug: str, sphere_id: int) -> EventDTO:
        """Read an event by slug within a sphere.

        Returns:
            EventDTO for the requested event.

        Raises:
            NotFoundError: If the event does not exist.
        """
        try:
            event = Event.objects.select_related("proposal_settings").get(
                slug=slug, sphere_id=sphere_id
            )
        except Event.DoesNotExist as exception:
            raise NotFoundError from exception
        return _event_dto(event)

    @staticmethod
    def get_stats_data(event_id: int) -> EventStatsData:
        """Get raw statistics data for an event.

        Returns:
            EventStatsData with raw counts and IDs for business logic processing.
        """
        # Ensure event is cached in storage
        sessions = Session.objects.filter(category__event_id=event_id)
        scheduled = Session.objects.filter(
            agenda_item__space__area__venue__event_id=event_id
        )
        spaces = Space.objects.filter(area__venue__event_id=event_id)

        return EventStatsData(
            pending_proposals=sessions.filter(status=SessionStatus.PENDING).count(),
            scheduled_sessions=scheduled.count(),
            total_proposals=sessions.count(),
            unique_host_ids=set(
                sessions.exclude(presenter_id__isnull=True).values_list(
                    "presenter_id", flat=True
                )
            ),
            rooms_count=spaces.count(),
        )

    @staticmethod
    def update(event_id: int, data: EventUpdateData) -> None:
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist as exception:
            raise NotFoundError from exception

        for key, value in data.items():
            setattr(event, key, value)
        event.save(update_fields=list(data.keys()))

    @staticmethod
    def update_proposal_description(event_id: int, description: str) -> None:
        EventProposalSettings.objects.update_or_create(
            event_id=event_id, defaults={"description": description}
        )


class EventProposalSettingsRepository(EventProposalSettingsRepositoryProtocol):
    @staticmethod
    def read_or_create_by_event(event_id: int) -> EventProposalSettingsDTO:
        settings, _ = EventProposalSettings.objects.get_or_create(event_id=event_id)
        return EventProposalSettingsDTO.model_validate(settings)


class EventSettingsRepository(EventSettingsRepositoryProtocol):
    @staticmethod
    def read_or_create(event_id: int) -> EventSettingsDTO:
        settings, _ = EventSettings.objects.get_or_create(event_id=event_id)
        return EventSettingsDTO(
            pk=settings.pk,
            displayed_session_field_ids=list(
                settings.displayed_session_fields.values_list("pk", flat=True)
            ),
        )

    @staticmethod
    def update_displayed_fields(event_id: int, field_ids: list[int]) -> None:
        settings, _ = EventSettings.objects.get_or_create(event_id=event_id)
        settings.displayed_session_fields.set(field_ids)


class VenueRepository(VenueRepositoryProtocol):
    @transaction.atomic
    def create(self, event_id: int, name: str, address: str = "") -> VenueDTO:
        """Create a new venue for an event.

        Args:
            event_id: The event to create the venue for.
            name: The venue name.
            address: The venue address (optional).

        Returns:
            VenueDTO of the created venue.
        """
        # Lock event to serialize slug generation
        Event.objects.select_for_update().get(pk=event_id)

        base_slug = slugify(name)
        slug = self.generate_unique_slug(event_id, base_slug)

        max_order = (
            Venue.objects.filter(event_id=event_id).aggregate(max_order=Max("order"))[
                "max_order"
            ]
            or -1
        )

        venue = Venue.objects.create(
            event_id=event_id,
            name=name,
            slug=slug,
            address=address,
            order=max_order + 1,
        )

        return VenueDTO.model_validate(venue)

    @staticmethod
    def delete(pk: int) -> None:
        """Delete a venue.

        Args:
            pk: The venue primary key.
        """
        try:
            venue = Venue.objects.get(pk=pk)
        except Venue.DoesNotExist:
            return

        venue.delete()

    @staticmethod
    def has_sessions(pk: int) -> bool:
        """Check if any space in any area of the venue has scheduled sessions.

        Args:
            pk: The venue primary key.

        Returns:
            True if any space in the venue has sessions, False otherwise.
        """
        return AgendaItem.objects.filter(space__area__venue_id=pk).exists()

    @staticmethod
    def list_by_event(event_pk: int) -> list[VenueDTO]:
        """List all venues for an event, ordered by order then name.

        Returns:
            List of VenueDTO objects for the event.
        """
        venues = (
            Venue.objects.filter(event_id=event_pk)
            .annotate(areas_count=Count("areas"))
            .order_by("order", "name")
        )

        return [VenueDTO.model_validate(venue) for venue in venues]

    @staticmethod
    def read_by_slug(event_pk: int, slug: str) -> VenueDTO:
        """Read a venue by slug.

        Args:
            event_pk: The event primary key.
            slug: The venue slug.

        Returns:
            VenueDTO of the venue.

        Raises:
            NotFoundError: If the venue is not found.
        """
        try:
            venue = Venue.objects.get(event_id=event_pk, slug=slug)
        except Venue.DoesNotExist as err:
            msg = f"Venue with slug '{slug}' not found"
            raise NotFoundError(msg) from err

        return VenueDTO.model_validate(venue)

    @staticmethod
    def reorder(event_id: int, venue_pks: list[int]) -> None:
        """Reorder venues for an event.

        Args:
            event_id: The event primary key.
            venue_pks: List of venue PKs in the desired order.
        """
        # Filter to only venues belonging to this event
        venues = Venue.objects.filter(event_id=event_id, pk__in=venue_pks)
        venue_map = {v.pk: v for v in venues}

        # Filter venue_pks to only include valid venues for this event
        valid_pks = [pk for pk in venue_pks if pk in venue_map]

        # Update order based on position in the filtered list
        for order, pk in enumerate(valid_pks):
            venue = venue_map[pk]
            if venue.order != order:
                venue.order = order
                venue.save(update_fields=["order"])

    @transaction.atomic
    def update(self, pk: int, name: str, address: str = "") -> VenueDTO:
        """Update a venue.

        Args:
            pk: The venue primary key.
            name: The new venue name.
            address: The new venue address.

        Returns:
            VenueDTO of the updated venue.

        Raises:
            NotFoundError: If the venue is not found.
        """
        try:
            # Lock venue and its event to serialize slug generation
            venue = Venue.objects.select_for_update().select_related("event").get(pk=pk)
            Event.objects.select_for_update().get(pk=venue.event_id)
        except Venue.DoesNotExist as err:
            msg = f"Venue with pk '{pk}' not found"
            raise NotFoundError(msg) from err

        needs_save = False

        if venue.name != name:
            base_slug = slugify(name)
            slug = self.generate_unique_slug(venue.event_id, base_slug, exclude_pk=pk)
            venue.name = name
            venue.slug = slug
            needs_save = True

        if venue.address != address:
            venue.address = address
            needs_save = True

        if needs_save:
            venue.save()

        return VenueDTO.model_validate(venue)

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug

        for _ in range(4):
            query = Venue.objects.filter(event_id=event_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"

        return slug

    @transaction.atomic
    def duplicate(self, pk: int, new_name: str) -> VenueDTO:
        """Duplicate a venue within the same event.

        Copies the venue with all its areas and spaces.

        Args:
            pk: The venue primary key to duplicate.
            new_name: The name for the new venue.

        Returns:
            VenueDTO of the new venue.

        Raises:
            NotFoundError: If the venue is not found.
        """
        try:
            venue = Venue.objects.select_for_update().get(pk=pk)
        except Venue.DoesNotExist as err:
            msg = f"Venue with pk '{pk}' not found"
            raise NotFoundError(msg) from err

        # Lock event to serialize slug generation for all new entities
        Event.objects.select_for_update().get(pk=venue.event_id)

        # Create new venue
        base_slug = slugify(new_name)
        new_slug = self.generate_unique_slug(venue.event_id, base_slug)

        max_order = (
            Venue.objects.filter(event_id=venue.event_id).aggregate(
                max_order=Max("order")
            )["max_order"]
            or -1
        )

        new_venue = Venue.objects.create(
            event_id=venue.event_id,
            name=new_name,
            slug=new_slug,
            address=venue.address,
            order=max_order + 1,
        )

        # Copy areas and spaces (event lock serializes all slug generation)
        areas = Area.objects.filter(venue_id=pk).order_by("order")
        for area in areas:
            area_slug = AreaRepository.generate_unique_slug(new_venue.pk, area.slug)
            new_area = Area.objects.create(
                venue_id=new_venue.pk,
                name=area.name,
                slug=area_slug,
                description=area.description,
                order=area.order,
            )

            # Copy spaces for this area
            spaces = Space.objects.filter(area_id=area.pk).order_by("order")
            for space in spaces:
                space_slug = SpaceRepository.generate_unique_slug(
                    new_area.pk, space.slug
                )
                Space.objects.create(
                    area_id=new_area.pk,
                    name=space.name,
                    slug=space_slug,
                    capacity=space.capacity,
                    order=space.order,
                )

        return VenueDTO.model_validate(new_venue)

    @transaction.atomic
    def copy_to_event(self, pk: int, target_event_id: int) -> VenueDTO:
        """Copy a venue to another event.

        Copies the venue with all its areas and spaces.

        Args:
            pk: The venue primary key to copy.
            target_event_id: The target event ID.

        Returns:
            VenueDTO of the new venue.

        Raises:
            NotFoundError: If the venue is not found.
        """
        try:
            venue = Venue.objects.select_for_update().get(pk=pk)
        except Venue.DoesNotExist as err:
            msg = f"Venue with pk '{pk}' not found"
            raise NotFoundError(msg) from err

        # Lock target event to serialize slug generation for all new entities
        Event.objects.select_for_update().get(pk=target_event_id)

        # Create new venue in target event
        base_slug = slugify(venue.name)
        new_slug = self.generate_unique_slug(target_event_id, base_slug)

        max_order = (
            Venue.objects.filter(event_id=target_event_id).aggregate(
                max_order=Max("order")
            )["max_order"]
            or -1
        )

        new_venue = Venue.objects.create(
            event_id=target_event_id,
            name=venue.name,
            slug=new_slug,
            address=venue.address,
            order=max_order + 1,
        )

        # Copy areas and spaces (event lock serializes all slug generation)
        areas = Area.objects.filter(venue_id=pk).order_by("order")
        for area in areas:
            area_slug = AreaRepository.generate_unique_slug(new_venue.pk, area.slug)
            new_area = Area.objects.create(
                venue_id=new_venue.pk,
                name=area.name,
                slug=area_slug,
                description=area.description,
                order=area.order,
            )

            # Copy spaces for this area
            spaces = Space.objects.filter(area_id=area.pk).order_by("order")
            for space in spaces:
                space_slug = SpaceRepository.generate_unique_slug(
                    new_area.pk, space.slug
                )
                Space.objects.create(
                    area_id=new_area.pk,
                    name=space.name,
                    slug=space_slug,
                    capacity=space.capacity,
                    order=space.order,
                )

        return VenueDTO.model_validate(new_venue)


class AreaRepository(AreaRepositoryProtocol):
    @transaction.atomic
    def create(self, venue_id: int, name: str, description: str = "") -> AreaDTO:
        """Create a new area for a venue.

        Args:
            venue_id: The venue to create the area for.
            name: The area name.
            description: The area description (optional).

        Returns:
            AreaDTO of the created area.
        """
        # Lock venue to serialize slug generation
        Venue.objects.select_for_update().get(pk=venue_id)

        base_slug = slugify(name)
        slug = self.generate_unique_slug(venue_id, base_slug)

        max_order = (
            Area.objects.filter(venue_id=venue_id).aggregate(max_order=Max("order"))[
                "max_order"
            ]
            or -1
        )

        area = Area.objects.create(
            venue_id=venue_id,
            name=name,
            slug=slug,
            description=description,
            order=max_order + 1,
        )

        return AreaDTO.model_validate(area)

    @staticmethod
    def delete(pk: int) -> None:
        """Delete an area.

        Args:
            pk: The area primary key.
        """
        try:
            area = Area.objects.get(pk=pk)
        except Area.DoesNotExist:
            return

        area.delete()

    @staticmethod
    def has_sessions(pk: int) -> bool:
        """Check if any space in the area has scheduled sessions.

        Args:
            pk: The area primary key.

        Returns:
            True if any space in the area has sessions, False otherwise.
        """
        return AgendaItem.objects.filter(space__area_id=pk).exists()

    @staticmethod
    def list_by_venue(venue_pk: int) -> list[AreaDTO]:
        """List all areas for a venue, ordered by order then name.

        Returns:
            List of AreaDTO objects for the venue.
        """
        areas = (
            Area.objects.filter(venue_id=venue_pk)
            .annotate(spaces_count=Count("spaces"))
            .order_by("order", "name")
        )

        return [AreaDTO.model_validate(area) for area in areas]

    @staticmethod
    def read_by_slug(venue_pk: int, slug: str) -> AreaDTO:
        """Read an area by slug.

        Args:
            venue_pk: The venue primary key.
            slug: The area slug.

        Returns:
            AreaDTO of the area.

        Raises:
            NotFoundError: If the area is not found.
        """
        try:
            area = Area.objects.get(venue_id=venue_pk, slug=slug)
        except Area.DoesNotExist as err:
            msg = f"Area with slug '{slug}' not found"
            raise NotFoundError(msg) from err

        return AreaDTO.model_validate(area)

    @staticmethod
    def reorder(venue_id: int, area_pks: list[int]) -> None:
        """Reorder areas for a venue.

        Args:
            venue_id: The venue primary key.
            area_pks: List of area PKs in the desired order.
        """
        # Filter to only areas belonging to this venue
        areas = Area.objects.filter(venue_id=venue_id, pk__in=area_pks)
        area_map = {a.pk: a for a in areas}

        # Filter area_pks to only include valid areas for this venue
        valid_pks = [pk for pk in area_pks if pk in area_map]

        # Update order based on position in the filtered list
        for order, pk in enumerate(valid_pks):
            area = area_map[pk]
            if area.order != order:
                area.order = order
                area.save(update_fields=["order"])

    @transaction.atomic
    def update(self, pk: int, name: str, description: str = "") -> AreaDTO:
        """Update an area.

        Args:
            pk: The area primary key.
            name: The new area name.
            description: The new area description.

        Returns:
            AreaDTO of the updated area.

        Raises:
            NotFoundError: If the area is not found.
        """
        try:
            # Lock area and its venue to serialize slug generation
            area = Area.objects.select_for_update().select_related("venue").get(pk=pk)
            Venue.objects.select_for_update().get(pk=area.venue_id)
        except Area.DoesNotExist as err:
            msg = f"Area with pk '{pk}' not found"
            raise NotFoundError(msg) from err

        needs_save = False

        if area.name != name:
            base_slug = slugify(name)
            slug = self.generate_unique_slug(area.venue_id, base_slug, exclude_pk=pk)
            area.name = name
            area.slug = slug
            needs_save = True

        if area.description != description:
            area.description = description
            needs_save = True

        if needs_save:
            area.save()

        return AreaDTO.model_validate(area)

    @staticmethod
    def generate_unique_slug(
        venue_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug

        for _ in range(4):
            query = Area.objects.filter(venue_id=venue_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"

        return slug


class SpaceRepository(SpaceRepositoryProtocol):
    @transaction.atomic
    def create(self, area_id: int, name: str, capacity: int | None = None) -> SpaceDTO:
        """Create a new space for an area.

        Args:
            area_id: The area to create the space for.
            name: The space name.
            capacity: The space capacity (optional).

        Returns:
            SpaceDTO of the created space.
        """
        # Lock area to serialize slug generation
        Area.objects.select_for_update().get(pk=area_id)

        base_slug = slugify(name)
        slug = self.generate_unique_slug(area_id, base_slug)

        max_order = (
            Space.objects.filter(area_id=area_id).aggregate(max_order=Max("order"))[
                "max_order"
            ]
            or -1
        )

        space = Space.objects.create(
            area_id=area_id,
            name=name,
            slug=slug,
            capacity=capacity,
            order=max_order + 1,
        )

        return SpaceDTO.model_validate(space)

    @staticmethod
    def read(pk: int) -> SpaceDTO:
        try:
            space = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        return SpaceDTO.model_validate(space)

    @staticmethod
    def delete(pk: int) -> None:
        """Delete a space.

        Args:
            pk: The space primary key.
        """
        try:
            space = Space.objects.get(pk=pk)
        except Space.DoesNotExist:
            return

        space.delete()

    @staticmethod
    def has_sessions(pk: int) -> bool:
        """Check if a space has any scheduled sessions.

        Args:
            pk: The space primary key.

        Returns:
            True if the space has sessions, False otherwise.
        """
        return AgendaItem.objects.filter(space_id=pk).exists()

    @staticmethod
    def list_by_area(area_pk: int) -> list[SpaceDTO]:
        """List all spaces for an area, ordered by order then name.

        Returns:
            List of SpaceDTO objects for the area.
        """
        spaces = Space.objects.filter(area_id=area_pk).order_by("order", "name")

        return [SpaceDTO.model_validate(space) for space in spaces]

    @staticmethod
    def list_by_event(event_pk: int) -> list[SpaceDTO]:
        """List all spaces for an event, ordered by name.

        Returns:
            List of SpaceDTO objects for the event.
        """
        spaces = Space.objects.filter(area__venue__event_id=event_pk).order_by(
            *Space.HIERARCHICAL_ORDER
        )

        return [SpaceDTO.model_validate(space) for space in spaces]

    @staticmethod
    def read_by_slug(area_pk: int, slug: str) -> SpaceDTO:
        """Read a space by slug.

        Args:
            area_pk: The area primary key.
            slug: The space slug.

        Returns:
            SpaceDTO of the space.

        Raises:
            NotFoundError: If the space is not found.
        """
        try:
            space = Space.objects.get(area_id=area_pk, slug=slug)
        except Space.DoesNotExist as err:
            msg = f"Space with slug '{slug}' not found"
            raise NotFoundError(msg) from err

        return SpaceDTO.model_validate(space)

    @staticmethod
    def reorder(area_id: int, space_pks: list[int]) -> None:
        """Reorder spaces for an area.

        Args:
            area_id: The area primary key.
            space_pks: List of space PKs in the desired order.
        """
        # Filter to only spaces belonging to this area
        spaces = Space.objects.filter(area_id=area_id, pk__in=space_pks)
        space_map = {s.pk: s for s in spaces}

        # Filter space_pks to only include valid spaces for this area
        valid_pks = [pk for pk in space_pks if pk in space_map]

        # Update order based on position in the filtered list
        for order, pk in enumerate(valid_pks):
            space = space_map[pk]
            if space.order != order:
                space.order = order
                space.save(update_fields=["order"])

    @transaction.atomic
    def update(self, pk: int, name: str, capacity: int | None = None) -> SpaceDTO:
        """Update a space.

        Args:
            pk: The space primary key.
            name: The new space name.
            capacity: The new space capacity.

        Returns:
            SpaceDTO of the updated space.

        Raises:
            NotFoundError: If the space is not found.
        """
        try:
            # Lock space and its area to serialize slug generation
            space = Space.objects.select_for_update().select_related("area").get(pk=pk)
            Area.objects.select_for_update().get(pk=space.area_id)
        except Space.DoesNotExist as err:
            msg = f"Space with pk '{pk}' not found"
            raise NotFoundError(msg) from err

        needs_save = False

        if space.name != name:
            base_slug = slugify(name)
            slug = self.generate_unique_slug(space.area_id, base_slug, exclude_pk=pk)
            space.name = name
            space.slug = slug
            needs_save = True

        if space.capacity != capacity:
            space.capacity = capacity
            needs_save = True

        if needs_save:
            space.save()

        return SpaceDTO.model_validate(space)

    @staticmethod
    def generate_unique_slug(
        area_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug

        for _ in range(4):
            query = Space.objects.filter(area_id=area_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"

        return slug


class ProposalCategoryRepository(ProposalCategoryRepositoryProtocol):  # noqa: PLR0904
    def create(self, event_id: int, name: str) -> ProposalCategoryDTO:
        base_slug = slugify(name)
        slug = self.generate_unique_slug(event_id, base_slug)

        category = ProposalCategory.objects.create(
            event_id=event_id, name=name, slug=slug
        )

        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def read_by_slug(event_id: int, slug: str) -> ProposalCategoryDTO:
        try:
            category = ProposalCategory.objects.get(event_id=event_id, slug=slug)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception

        return ProposalCategoryDTO.model_validate(category)

    _SIMPLE_UPDATE_FIELDS = (
        "description",
        "start_time",
        "end_time",
        "durations",
        "min_participants_limit",
        "max_participants_limit",
    )

    def update(self, pk: int, data: ProposalCategoryData) -> ProposalCategoryDTO:
        try:
            category = ProposalCategory.objects.get(id=pk)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception

        needs_save = False

        if "name" in data and category.name != data["name"]:
            name = data["name"]
            category.name = name
            category.slug = self.generate_unique_slug(
                category.event_id, slugify(name), exclude_pk=pk
            )
            needs_save = True

        data_dict = cast("dict[str, object]", data)
        for field in self._SIMPLE_UPDATE_FIELDS:
            if field in data_dict and getattr(category, field) != data_dict[field]:
                setattr(category, field, data_dict[field])
                needs_save = True

        if needs_save:
            category.save()

        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def delete(pk: int) -> None:
        try:
            category = ProposalCategory.objects.get(id=pk)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception

        category.delete()

    @staticmethod
    def get_category_stats(event_id: int) -> dict[int, CategoryStats]:
        """Get proposal statistics for all categories of an event.

        Returns:
            Dict mapping category ID to CategoryStats with proposals_count
            and accepted_count.
        """
        categories = ProposalCategory.objects.filter(event_id=event_id).annotate(
            proposals_count=Count("sessions"),
            accepted_count=Count(
                "sessions", filter=~Q(sessions__status=SessionStatus.PENDING)
            ),
        )

        return {
            category.pk: CategoryStats(
                proposals_count=category.proposals_count,
                accepted_count=category.accepted_count,
            )
            for category in categories
        }

    @staticmethod
    def has_proposals(pk: int) -> bool:
        return Session.objects.filter(category_id=pk).exists()

    @staticmethod
    def list_by_event(event_id: int) -> list[ProposalCategoryDTO]:
        categories = ProposalCategory.objects.filter(event_id=event_id).order_by("name")
        return [ProposalCategoryDTO.model_validate(c) for c in categories]

    @staticmethod
    def get_field_requirements(category_id: int) -> dict[int, bool]:
        """Get field requirements for a category.

        Returns:
            Dict mapping field_id to is_required boolean.
        """
        requirements = PersonalDataFieldRequirement.objects.filter(
            category_id=category_id
        )
        return {req.field_id: req.is_required for req in requirements}

    @staticmethod
    def get_field_order(category_id: int) -> list[int]:
        """Get ordered list of field IDs for a category.

        Returns:
            List of field IDs ordered by their order field.
        """
        requirements = PersonalDataFieldRequirement.objects.filter(
            category_id=category_id
        ).order_by("order")
        return [req.field_id for req in requirements]

    @staticmethod
    def set_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None:
        """Set field requirements for a category.

        Replaces all existing requirements with the provided ones.

        Args:
            category_id: The category to set requirements for.
            requirements: Dict mapping field_id to is_required boolean.
            order: Optional list of field IDs defining the order.
        """
        # Delete existing requirements
        PersonalDataFieldRequirement.objects.filter(category_id=category_id).delete()

        # Build order mapping
        order_map = {fid: idx for idx, fid in enumerate(order or [])}

        # Create new requirements
        for field_id, is_required in requirements.items():
            PersonalDataFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=order_map.get(field_id, 0),
            )

    @staticmethod
    def get_session_field_requirements(category_id: int) -> dict[int, bool]:
        """Get session field requirements for a category.

        Returns:
            Dict mapping field_id to is_required boolean.
        """
        requirements = SessionFieldRequirement.objects.filter(category_id=category_id)
        return {req.field_id: req.is_required for req in requirements}

    @staticmethod
    def get_session_field_order(category_id: int) -> list[int]:
        """Get ordered list of session field IDs for a category.

        Returns:
            List of field IDs ordered by their order field.
        """
        requirements = SessionFieldRequirement.objects.filter(
            category_id=category_id
        ).order_by("order")
        return [req.field_id for req in requirements]

    @staticmethod
    def set_session_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None:
        """Set session field requirements for a category.

        Replaces all existing requirements with the provided ones.

        Args:
            category_id: The category to set requirements for.
            requirements: Dict mapping field_id to is_required boolean.
            order: Optional list of field IDs defining the order.
        """
        # Delete existing requirements
        SessionFieldRequirement.objects.filter(category_id=category_id).delete()

        # Build order mapping
        order_map = {fid: idx for idx, fid in enumerate(order or [])}

        # Create new requirements
        for field_id, is_required in requirements.items():
            SessionFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=order_map.get(field_id, 0),
            )

    @staticmethod
    def add_field_to_categories(field_id: int, categories: dict[int, bool]) -> None:
        """Add a personal data field to multiple categories.

        Args:
            field_id: The field to add.
            categories: Dict mapping category_id to is_required boolean.
        """
        for category_id, is_required in categories.items():
            max_order = (
                PersonalDataFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            PersonalDataFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def add_session_field_to_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None:
        """Add a session field to multiple categories.

        Args:
            field_id: The field to add.
            categories: Dict mapping category_id to is_required boolean.
        """
        for category_id, is_required in categories.items():
            max_order = (
                SessionFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            SessionFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def get_personal_field_categories(field_id: int) -> dict[int, bool]:
        reqs = PersonalDataFieldRequirement.objects.filter(field_id=field_id)
        return {req.category_id: req.is_required for req in reqs}

    @staticmethod
    def set_personal_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None:
        PersonalDataFieldRequirement.objects.filter(field_id=field_id).delete()
        for category_id, is_required in categories.items():
            max_order = (
                PersonalDataFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            PersonalDataFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def get_session_field_categories(field_id: int) -> dict[int, bool]:
        reqs = SessionFieldRequirement.objects.filter(field_id=field_id)
        return {req.category_id: req.is_required for req in reqs}

    @staticmethod
    def set_session_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None:
        SessionFieldRequirement.objects.filter(field_id=field_id).delete()
        for category_id, is_required in categories.items():
            max_order = (
                SessionFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            SessionFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def get_time_slot_requirements(category_id: int) -> dict[int, bool]:
        """Get time slot requirements for a category.

        Returns:
            Dict mapping time_slot_id to is_required boolean.
        """
        requirements = TimeSlotRequirement.objects.filter(category_id=category_id)
        return {req.time_slot_id: req.is_required for req in requirements}

    @staticmethod
    def get_time_slot_order(category_id: int) -> list[int]:
        """Get ordered list of time slot IDs for a category.

        Returns:
            List of time slot IDs ordered by their order field.
        """
        requirements = TimeSlotRequirement.objects.filter(
            category_id=category_id
        ).order_by("order")
        return [req.time_slot_id for req in requirements]

    @staticmethod
    def set_time_slot_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None:
        """Set time slot requirements for a category.

        Replaces all existing requirements with the provided ones.

        Args:
            category_id: The category to set requirements for.
            requirements: Dict mapping time_slot_id to is_required boolean.
            order: Optional list of time slot IDs defining the order.
        """
        TimeSlotRequirement.objects.filter(category_id=category_id).delete()

        order_map = {ts_id: idx for idx, ts_id in enumerate(order or [])}

        for time_slot_id, is_required in requirements.items():
            TimeSlotRequirement.objects.create(
                category_id=category_id,
                time_slot_id=time_slot_id,
                is_required=is_required,
                order=order_map.get(time_slot_id, 0),
            )

    @staticmethod
    def read(pk: int, event_id: int) -> ProposalCategoryDTO:
        try:
            category = ProposalCategory.objects.get(pk=pk, event_id=event_id)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception
        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def list_personal_field_requirements(
        category_id: int,
    ) -> list[PersonalFieldRequirementDTO]:
        requirements = (
            PersonalDataFieldRequirement.objects.filter(category_id=category_id)
            .select_related("field")
            .prefetch_related("field__options")
            .order_by("order", "field__name")
        )
        result = []
        for req in requirements:
            field = req.field
            options = [
                PersonalDataFieldOptionDTO.model_validate(o)
                for o in field.options.all().order_by("order", "label")
            ]
            field_dto = PersonalDataFieldDTO(
                allow_custom=field.allow_custom,
                field_type=cast(
                    "Literal['text', 'select', 'checkbox']", field.field_type
                ),
                help_text=field.help_text,
                is_multiple=field.is_multiple,
                is_public=field.is_public,
                name=field.name,
                options=options,
                order=field.order,
                pk=field.pk,
                question=field.question,
                slug=field.slug,
            )
            result.append(
                PersonalFieldRequirementDTO(
                    field=field_dto, is_required=req.is_required
                )
            )
        return result

    @staticmethod
    def list_session_field_requirements(
        category_id: int,
    ) -> list[SessionFieldRequirementDTO]:
        requirements = (
            SessionFieldRequirement.objects.filter(category_id=category_id)
            .select_related("field")
            .prefetch_related("field__options")
            .order_by("order", "field__name")
        )
        result = []
        for req in requirements:
            field = req.field
            options = [
                SessionFieldOptionDTO.model_validate(o)
                for o in field.options.all().order_by("order", "label")
            ]
            field_dto = SessionFieldDTO(
                allow_custom=field.allow_custom,
                field_type=cast(
                    "Literal['text', 'select', 'checkbox']", field.field_type
                ),
                help_text=field.help_text,
                icon=field.icon,
                is_multiple=field.is_multiple,
                is_public=field.is_public,
                name=field.name,
                options=options,
                order=field.order,
                pk=field.pk,
                question=field.question,
                slug=field.slug,
            )
            result.append(
                SessionFieldRequirementDTO(field=field_dto, is_required=req.is_required)
            )
        return result

    @staticmethod
    def list_time_slot_requirements(category_id: int) -> list[TimeSlotRequirementDTO]:
        requirements = (
            TimeSlotRequirement.objects.filter(category_id=category_id)
            .select_related("time_slot")
            .order_by("order", "time_slot__start_time")
        )
        return [
            TimeSlotRequirementDTO(
                time_slot=TimeSlotDTO.model_validate(req.time_slot),
                time_slot_id=req.time_slot_id,
                is_required=req.is_required,
            )
            for req in requirements
        ]

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug

        for _ in range(4):
            query = ProposalCategory.objects.filter(event_id=event_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"

        return slug


class PersonalDataFieldRepository(PersonalDataFieldRepositoryProtocol):
    def create(
        self, event_id: int, data: PersonalDataFieldCreateData
    ) -> PersonalDataFieldDTO:
        field_type = data["field_type"]
        options = data["options"]
        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(event_id, base_slug)

        # is_multiple and allow_custom only apply to select fields
        actual_is_multiple = data["is_multiple"] if field_type == "select" else False
        actual_allow_custom = data["allow_custom"] if field_type == "select" else False

        field = PersonalDataField.objects.create(
            event_id=event_id,
            name=data["name"],
            question=data["question"],
            slug=slug,
            field_type=field_type,
            is_multiple=actual_is_multiple,
            allow_custom=actual_allow_custom,
            max_length=data["max_length"],
            help_text=data["help_text"],
            is_public=data["is_public"],
        )

        if field_type == "select" and options:
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    PersonalDataFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def delete(pk: int) -> None:
        PersonalDataField.objects.filter(pk=pk).delete()

    @staticmethod
    def has_requirements(pk: int) -> bool:
        """Check if a personal data field is used in any category requirements.

        Returns:
            True if the field is used in at least one category requirement.
        """
        return PersonalDataFieldRequirement.objects.filter(field_id=pk).exists()

    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]:
        rows = (
            PersonalDataFieldRequirement.objects.filter(field__event_id=event_id)
            .values("field_id")
            .annotate(
                required=Count("pk", filter=Q(is_required=True)),
                optional=Count("pk", filter=Q(is_required=False)),
            )
        )
        return {
            row["field_id"]: {"required": row["required"], "optional": row["optional"]}
            for row in rows
        }

    def list_by_event(self, event_id: int) -> list[PersonalDataFieldDTO]:
        fields = PersonalDataField.objects.filter(event_id=event_id).prefetch_related(
            "options"
        )
        return [self._to_dto(f) for f in fields]

    def read_by_slug(self, event_id: int, slug: str) -> PersonalDataFieldDTO:
        try:
            field = PersonalDataField.objects.prefetch_related("options").get(
                event_id=event_id, slug=slug
            )
        except PersonalDataField.DoesNotExist as exc:
            raise NotFoundError from exc

        return self._to_dto(field)

    def update(
        self, pk: int, data: PersonalDataFieldUpdateData
    ) -> PersonalDataFieldDTO:
        try:
            field = PersonalDataField.objects.prefetch_related("options").get(pk=pk)
        except PersonalDataField.DoesNotExist as exc:
            raise NotFoundError from exc

        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(field.event_id, base_slug, exclude_pk=pk)

        field.name = data["name"]
        field.question = data["question"]
        field.slug = slug
        field.max_length = data["max_length"]
        field.help_text = data["help_text"]
        field.is_public = data["is_public"]
        field.save()

        options = data["options"]
        if options is not None and field.field_type == "select":
            field.options.all().delete()
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    PersonalDataFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug

        for _ in range(4):
            query = PersonalDataField.objects.filter(event_id=event_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"

        return slug

    @staticmethod
    def _to_dto(field: PersonalDataField) -> PersonalDataFieldDTO:
        options = [
            PersonalDataFieldOptionDTO.model_validate(o) for o in field.options.all()
        ]
        return PersonalDataFieldDTO(
            allow_custom=field.allow_custom,
            field_type=cast("Literal['text', 'select', 'checkbox']", field.field_type),
            help_text=field.help_text,
            is_multiple=field.is_multiple,
            is_public=field.is_public,
            max_length=field.max_length,
            name=field.name,
            options=options,
            order=field.order,
            pk=field.pk,
            question=field.question,
            slug=field.slug,
        )


class SessionFieldRepository(SessionFieldRepositoryProtocol):
    def create(self, event_id: int, data: SessionFieldCreateData) -> SessionFieldDTO:
        field_type = data["field_type"]
        options = data["options"]
        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(event_id, base_slug)

        # is_multiple and allow_custom only apply to select fields
        actual_is_multiple = data["is_multiple"] if field_type == "select" else False
        actual_allow_custom = data["allow_custom"] if field_type == "select" else False

        field = SessionField.objects.create(
            event_id=event_id,
            name=data["name"],
            question=data["question"],
            slug=slug,
            field_type=field_type,
            is_multiple=actual_is_multiple,
            allow_custom=actual_allow_custom,
            max_length=data["max_length"],
            help_text=data["help_text"],
            icon=data["icon"],
            is_public=data["is_public"],
        )

        if field_type == "select" and options:
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    SessionFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def delete(pk: int) -> None:
        SessionField.objects.filter(pk=pk).delete()

    @staticmethod
    def has_requirements(pk: int) -> bool:
        """Check if a session field is used in any category requirements.

        Returns:
            True if the field is used in at least one category requirement.
        """
        return SessionFieldRequirement.objects.filter(field_id=pk).exists()

    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]:
        rows = (
            SessionFieldRequirement.objects.filter(field__event_id=event_id)
            .values("field_id")
            .annotate(
                required=Count("pk", filter=Q(is_required=True)),
                optional=Count("pk", filter=Q(is_required=False)),
            )
        )
        return {
            row["field_id"]: {"required": row["required"], "optional": row["optional"]}
            for row in rows
        }

    def list_by_event(self, event_id: int) -> list[SessionFieldDTO]:
        fields = SessionField.objects.filter(event_id=event_id).prefetch_related(
            "options"
        )
        return [self._to_dto(f) for f in fields]

    def read_by_slug(self, event_id: int, slug: str) -> SessionFieldDTO:
        try:
            field = SessionField.objects.prefetch_related("options").get(
                event_id=event_id, slug=slug
            )
        except SessionField.DoesNotExist as exc:
            raise NotFoundError from exc

        return self._to_dto(field)

    def update(self, pk: int, data: SessionFieldUpdateData) -> SessionFieldDTO:
        try:
            field = SessionField.objects.prefetch_related("options").get(pk=pk)
        except SessionField.DoesNotExist as exc:
            raise NotFoundError from exc

        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(field.event_id, base_slug, exclude_pk=pk)

        field.name = data["name"]
        field.question = data["question"]
        field.slug = slug
        field.max_length = data["max_length"]
        field.help_text = data["help_text"]
        field.icon = data["icon"]
        field.is_public = data["is_public"]
        field.save()

        options = data["options"]
        if options is not None and field.field_type == "select":
            field.options.all().delete()
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    SessionFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug

        for _ in range(4):
            query = SessionField.objects.filter(event_id=event_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"

        return slug

    @staticmethod
    def _to_dto(field: SessionField) -> SessionFieldDTO:
        options = [SessionFieldOptionDTO.model_validate(o) for o in field.options.all()]
        return SessionFieldDTO(
            allow_custom=field.allow_custom,
            field_type=cast("Literal['text', 'select', 'checkbox']", field.field_type),
            help_text=field.help_text,
            icon=field.icon,
            is_multiple=field.is_multiple,
            is_public=field.is_public,
            max_length=field.max_length,
            name=field.name,
            options=options,
            order=field.order,
            pk=field.pk,
            question=field.question,
            slug=field.slug,
        )


class FacilitatorRepository(FacilitatorRepositoryProtocol):
    @staticmethod
    def create(data: FacilitatorData) -> FacilitatorDTO:
        facilitator = Facilitator.objects.create(**data)
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read(pk: int) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(pk=pk)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read_by_event_and_slug(event_id: int, slug: str) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(event_id=event_id, slug=slug)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read_by_user_and_event(user_id: int, event_id: int) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(user_id=user_id, event_id=event_id)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def update(pk: int, data: FacilitatorUpdateData) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(pk=pk)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        for field, value in data.items():
            setattr(facilitator, field, value)
        facilitator.save()
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def list_by_event(event_id: int) -> list[FacilitatorListItemDTO]:
        qs = Facilitator.objects.filter(event_id=event_id).annotate(
            session_count=Count("sessions")
        )
        return [FacilitatorListItemDTO.model_validate(f) for f in qs]

    @staticmethod
    def delete(pk: int) -> None:
        Facilitator.objects.filter(pk=pk).delete()

    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool:
        return Facilitator.objects.filter(event_id=event_id, slug=slug).exists()


class HostPersonalDataRepository(HostPersonalDataRepositoryProtocol):
    @staticmethod
    def save(entries: list[HostPersonalDataEntry]) -> None:
        for entry in entries:
            HostPersonalData.objects.update_or_create(
                facilitator_id=entry["facilitator_id"],
                event_id=entry["event_id"],
                field_id=entry["field_id"],
                defaults={"value": entry["value"]},
            )

    @staticmethod
    def read_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> dict[str, str | list[str] | bool]:
        records = HostPersonalData.objects.filter(
            facilitator_id=facilitator_id, event_id=event_id
        ).select_related("field")
        return {hpd.field.slug: hpd.value for hpd in records}

    @staticmethod
    def delete_by_facilitators(facilitator_ids: list[int]) -> None:
        HostPersonalData.objects.filter(facilitator_id__in=facilitator_ids).delete()


class EnrollmentConfigRepository(EnrollmentConfigRepositoryProtocol):
    @staticmethod
    def read_list(
        event_id: int, max_start_time: datetime, min_end_time: datetime
    ) -> list[EnrollmentConfigDTO]:
        return [
            EnrollmentConfigDTO.model_validate(config)
            for config in EnrollmentConfig.objects.filter(
                event_id=event_id,
                start_time__lte=max_start_time,
                end_time__gte=min_end_time,
            ).all()
        ]

    @staticmethod
    def create_user_config(
        user_enrollment_config: UserEnrollmentConfigData,
    ) -> UserEnrollmentConfigDTO:
        return UserEnrollmentConfigDTO.model_validate(
            UserEnrollmentConfig.objects.create(**user_enrollment_config)
        )

    @staticmethod
    def read_user_config(
        config: EnrollmentConfigDTO, user_email: str
    ) -> UserEnrollmentConfigDTO | None:
        user_config = UserEnrollmentConfig.objects.filter(
            enrollment_config_id=config.pk, user_email=user_email
        ).first()
        return (
            UserEnrollmentConfigDTO.model_validate(user_config) if user_config else None
        )

    @staticmethod
    def update_user_config(user_enrollment_config: UserEnrollmentConfigDTO) -> None:
        update_dict = user_enrollment_config.model_dump()
        del update_dict["pk"]
        UserEnrollmentConfig.objects.filter(id=user_enrollment_config.pk).update(
            **update_dict
        )

    @staticmethod
    def read_domain_config(
        enrollment_config: EnrollmentConfigDTO, domain: str
    ) -> DomainEnrollmentConfigDTO | None:
        config = DomainEnrollmentConfig.objects.filter(
            enrollment_config_id=enrollment_config.pk, domain=domain
        ).first()

        return DomainEnrollmentConfigDTO.model_validate(config) if config else None


class TimeSlotRepository(TimeSlotRepositoryProtocol):
    @staticmethod
    def create(event_id: int, start_time: datetime, end_time: datetime) -> TimeSlotDTO:
        time_slot = TimeSlot.objects.create(
            event_id=event_id, start_time=start_time, end_time=end_time
        )
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def delete(pk: int) -> None:
        try:
            time_slot = TimeSlot.objects.get(pk=pk)
        except TimeSlot.DoesNotExist:
            return
        time_slot.delete()

    @staticmethod
    def has_proposals(pk: int) -> bool:
        return Session.objects.filter(time_slots=pk).exists()

    @staticmethod
    def list_by_event(event_id: int) -> list[TimeSlotDTO]:
        time_slots = TimeSlot.objects.filter(event_id=event_id).order_by("start_time")
        return [TimeSlotDTO.model_validate(ts) for ts in time_slots]

    @staticmethod
    def read(pk: int) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(pk=pk)
        except TimeSlot.DoesNotExist as exc:
            raise NotFoundError from exc
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def read_by_event(event_id: int, pk: int) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(pk=pk, event_id=event_id)
        except TimeSlot.DoesNotExist as exc:
            raise NotFoundError from exc
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def update(pk: int, start_time: datetime, end_time: datetime) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(pk=pk)
        except TimeSlot.DoesNotExist as exc:
            raise NotFoundError from exc
        time_slot.start_time = start_time
        time_slot.end_time = end_time
        time_slot.save()
        return TimeSlotDTO.model_validate(time_slot)


class EncounterRepository(EncounterRepositoryProtocol):
    @staticmethod
    def create(data: EncounterData) -> EncounterDTO:
        encounter = Encounter.objects.create(**data)
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def read(pk: int) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(pk=pk)
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def read_by_share_code(share_code: str) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(share_code=share_code)
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def list_by_creator(sphere_id: int, creator_id: int) -> list[EncounterDTO]:
        encounters = Encounter.objects.filter(
            sphere_id=sphere_id, creator_id=creator_id
        ).order_by("-start_time")
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_upcoming_by_creator(sphere_id: int, creator_id: int) -> list[EncounterDTO]:
        now = datetime.now(tz=UTC)
        encounters = Encounter.objects.filter(
            sphere_id=sphere_id, creator_id=creator_id, start_time__gte=now
        ).order_by("start_time")
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_upcoming_rsvpd(sphere_id: int, user_id: int) -> list[EncounterDTO]:
        now = datetime.now(tz=UTC)
        encounters = (
            Encounter.objects.filter(
                sphere_id=sphere_id, rsvps__user_id=user_id, start_time__gte=now
            )
            .exclude(creator_id=user_id)
            .order_by("start_time")
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_past(sphere_id: int, user_id: int) -> list[EncounterDTO]:
        now = datetime.now(tz=UTC)
        encounters = (
            Encounter.objects.filter(
                Q(creator_id=user_id) | Q(rsvps__user_id=user_id),
                sphere_id=sphere_id,
                start_time__lt=now,
            )
            .distinct()
            .order_by("-start_time")
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def update(pk: int, data: EncounterData) -> None:
        encounter = Encounter.objects.get(pk=pk)
        for key, value in data.items():
            setattr(encounter, key, value)
        encounter.save()

    @staticmethod
    def delete(pk: int) -> None:
        Encounter.objects.filter(pk=pk).delete()


class EncounterRSVPRepository(EncounterRSVPRepositoryProtocol):
    @staticmethod
    def create(encounter_id: int, ip_address: str, user_id: int) -> EncounterRSVPDTO:
        rsvp = EncounterRSVP.objects.create(
            encounter_id=encounter_id, ip_address=ip_address, user_id=user_id
        )
        return EncounterRSVPDTO.model_validate(rsvp)

    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterRSVPDTO]:
        rsvps = EncounterRSVP.objects.filter(encounter_id=encounter_id).order_by(
            "creation_time"
        )
        return [EncounterRSVPDTO.model_validate(r) for r in rsvps]

    @staticmethod
    def count_by_encounter(encounter_id: int) -> int:
        return EncounterRSVP.objects.filter(encounter_id=encounter_id).count()

    @staticmethod
    def recent_rsvp_exists(ip_address: str, seconds: int = 60) -> bool:
        cutoff = datetime.now(tz=UTC) - timedelta(seconds=seconds)
        return EncounterRSVP.objects.filter(
            ip_address=ip_address, creation_time__gte=cutoff
        ).exists()

    @staticmethod
    def user_has_rsvpd(encounter_id: int, user_id: int) -> bool:
        return EncounterRSVP.objects.filter(
            encounter_id=encounter_id, user_id=user_id
        ).exists()

    @staticmethod
    def delete_by_user(encounter_id: int, user_id: int) -> None:
        EncounterRSVP.objects.filter(
            encounter_id=encounter_id, user_id=user_id
        ).delete()


class TrackRepository(TrackRepositoryProtocol):
    @transaction.atomic
    def create(self, data: TrackCreateData) -> TrackDTO:
        Event.objects.select_for_update().get(pk=data["event_pk"])
        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(data["event_pk"], base_slug)
        track = Track.objects.create(
            event_id=data["event_pk"],
            name=data["name"],
            slug=slug,
            is_public=data["is_public"],
        )
        track.spaces.set(data["space_pks"])
        track.managers.set(data["manager_pks"])
        return TrackDTO.model_validate(track)

    @staticmethod
    def read(pk: int) -> TrackDTO:
        try:
            track = Track.objects.get(pk=pk)
        except Track.DoesNotExist as err:
            msg = f"Track with pk '{pk}' not found"
            raise NotFoundError(msg) from err
        return TrackDTO.model_validate(track)

    @staticmethod
    def read_by_slug(event_pk: int, slug: str) -> TrackDTO:
        try:
            track = Track.objects.get(event_id=event_pk, slug=slug)
        except Track.DoesNotExist as err:
            msg = f"Track with slug '{slug}' not found"
            raise NotFoundError(msg) from err
        return TrackDTO.model_validate(track)

    @transaction.atomic
    def update(self, pk: int, data: TrackUpdateData) -> TrackDTO:
        try:
            track = Track.objects.select_for_update().get(pk=pk)
            Event.objects.select_for_update().get(pk=track.event_id)
        except Track.DoesNotExist as err:
            msg = f"Track with pk '{pk}' not found"
            raise NotFoundError(msg) from err
        needs_save = False
        if track.name != data["name"]:
            base_slug = slugify(data["name"])
            track.slug = self.generate_unique_slug(
                track.event_id, base_slug, exclude_pk=pk
            )
            track.name = data["name"]
            needs_save = True
        if track.is_public != data["is_public"]:
            track.is_public = data["is_public"]
            needs_save = True
        if needs_save:
            track.save()
        track.spaces.set(data["space_pks"])
        track.managers.set(data["manager_pks"])
        return TrackDTO.model_validate(track)

    @staticmethod
    def delete(pk: int) -> None:
        Track.objects.filter(pk=pk).delete()

    @staticmethod
    def list_by_event(event_pk: int) -> list[TrackDTO]:
        tracks = Track.objects.filter(event_id=event_pk).order_by("name")
        return [TrackDTO.model_validate(t) for t in tracks]

    @staticmethod
    def list_public_by_event(event_pk: int) -> list[TrackDTO]:
        tracks = Track.objects.filter(event_id=event_pk, is_public=True).order_by(
            "name"
        )
        return [TrackDTO.model_validate(t) for t in tracks]

    @staticmethod
    def list_by_manager(user_pk: int, event_pk: int | None = None) -> list[TrackDTO]:
        qs = Track.objects.filter(managers__pk=user_pk)
        if event_pk is not None:
            qs = qs.filter(event_id=event_pk)
        return [TrackDTO.model_validate(t) for t in qs.order_by("name")]

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        slug = base_slug
        for _ in range(4):
            query = Track.objects.filter(event_id=event_id, slug=slug)
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"
        return slug

    @staticmethod
    def list_space_pks(pk: int) -> list[int]:
        return list(Space.objects.filter(tracks__pk=pk).values_list("pk", flat=True))

    @staticmethod
    def list_manager_pks(pk: int) -> list[int]:
        return list(
            User.objects.filter(managed_tracks__pk=pk).values_list("pk", flat=True)
        )

    @staticmethod
    def list_by_session(session_pk: int) -> list[TrackDTO]:
        tracks = Track.objects.filter(sessions__pk=session_pk).order_by("name")
        return [TrackDTO.model_validate(t) for t in tracks]

    @staticmethod
    def list_manager_names(track_pk: int) -> list[str]:
        return list(
            User.objects.filter(managed_tracks__pk=track_pk)
            .order_by("name")
            .values_list("name", flat=True)
        )


_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT = (
    "connection_unique_display_name_per_sphere"
)
_SQLITE_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT = (
    "UNIQUE constraint failed: connection.sphere_id, connection.display_name"
)


def _is_connection_display_name_conflict(exc: IntegrityError) -> bool:
    diag = getattr(exc.__cause__, "diag", None)
    if (
        getattr(diag, "constraint_name", None)
        == _CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT
    ):
        return True
    message = str(exc)
    return (
        _CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT in message
        or _SQLITE_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT in message
    )


class ConnectionsRepository(ConnectionsRepositoryProtocol):
    @staticmethod
    def list_for_sphere(sphere_id: int) -> list[ConnectionDTO]:
        return [
            ConnectionDTO.model_validate(c)
            for c in Connection.objects.filter(sphere_id=sphere_id).order_by(
                "display_name"
            )
        ]

    @staticmethod
    def get(sphere_id: int, pk: int) -> ConnectionDTO:
        try:
            connection = Connection.objects.get(pk=pk, sphere_id=sphere_id)
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def create(sphere_id: int, data: ConnectionWriteDict) -> ConnectionDTO:
        try:
            connection = Connection.objects.create(
                sphere_id=sphere_id,
                service=data["service"],
                display_name=data["display_name"],
            )
        except IntegrityError as exc:
            if _is_connection_display_name_conflict(exc):
                raise DuplicateConnectionDisplayNameError from exc
            raise
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def update(sphere_id: int, pk: int, data: ConnectionWriteDict) -> ConnectionDTO:
        try:
            connection = Connection.objects.get(pk=pk, sphere_id=sphere_id)
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        connection.service = data["service"]
        connection.display_name = data["display_name"]
        try:
            connection.save()
        except IntegrityError as exc:
            if _is_connection_display_name_conflict(exc):
                raise DuplicateConnectionDisplayNameError from exc
            raise
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def update_credentials(sphere_id: int, pk: int, blob: bytes) -> None:
        # Write-only: overwrite the encrypted blob. The repo surface
        # exposes no read for these bytes — decrypt is owned by the
        # import-execution slice with separate key handling.
        updated = Connection.objects.filter(pk=pk, sphere_id=sphere_id).update(
            credentials=blob
        )
        if not updated:
            raise NotFoundError

    @staticmethod
    def update_last_check(sphere_id: int, pk: int, result: CheckResult) -> None:
        updated = Connection.objects.filter(pk=pk, sphere_id=sphere_id).update(
            last_check_status=result.status,
            last_check_detail=result.detail,
            last_check_at=timezone.now(),
        )
        if not updated:
            raise NotFoundError

    @staticmethod
    def delete(sphere_id: int, pk: int) -> None:
        deleted, _ = Connection.objects.filter(pk=pk, sphere_id=sphere_id).delete()
        if not deleted:
            raise NotFoundError
