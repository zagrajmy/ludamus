import json
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Literal, cast  # pylint: disable=unused-import

from django.db import IntegrityError, transaction
from django.db.models import (
    Count,
    IntegerField,
    Max,
    OuterRef,
    ProtectedError,
    Q,
    Subquery,
)
from django.db.models.functions import Coalesce
from django.utils import timezone as django_timezone
from django.utils.text import slugify

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Announcement,
    Connection,
    Discount,
    DomainEnrollmentConfig,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    EventIntegration,
    EventProposalSettings,
    EventSettings,
    Facilitator,
    HostPersonalData,
    ImportLogEntry,
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
    TimeSlot,
    TimeSlotRequirement,
    Track,
    UserEnrollmentConfig,
)
from ludamus.pacts import (
    UNSCHEDULED_LIST_LIMIT,
    CategoryStats,
    DomainEnrollmentConfigDTO,
    EncounterData,
    EncounterDTO,
    EncounterRepositoryProtocol,
    EncounterRSVPDTO,
    EncounterRSVPRepositoryProtocol,
    EnrollmentConfigDTO,
    EnrollmentConfigRepositoryProtocol,
    EventDTO,
    EventListItemDTO,
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
    SphereUpdateData,
    TimeSlotDTO,
    TimeSlotRepositoryProtocol,
    TimeSlotRequirementDTO,
    TrackCreateData,
    TrackDTO,
    TrackRepositoryProtocol,
    TrackUpdateData,
    UnscheduledSessionDTO,
    UnscheduledSessionFilter,
    UserEnrollmentConfigData,
    UserEnrollmentConfigDTO,
)
from ludamus.pacts.chronology import (
    EventIntegrationCreateData,
    EventIntegrationDTO,
    EventIntegrationsRepositoryProtocol,
    EventIntegrationUpdateData,
    IntegrationImplementationId,
    IntegrationKind,
)
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountDTO,
    DiscountRepositoryProtocol,
)
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    AnnouncementsRepositoryProtocol,
    ConnectionDTO,
    ConnectionInUseError,
    ConnectionsRepositoryProtocol,
    DuplicateConnectionDisplayNameError,
    SphereDirectoryRepositoryProtocol,
    SphereListItemDTO,
)
from ludamus.pacts.submissions import (
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogEntryRepositoryProtocol,
    ImportLogStatus,
)
from ludamus.pacts.venues import SpaceNodeDTO, SpaceTreeRepositoryProtocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()

_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")

logger = logging.getLogger(__name__)


def delete_stored_file(field_file: object, old_name: str) -> None:
    if (storage := getattr(field_file, "storage", None)) is None:
        return
    try:
        storage.delete(old_name)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Best-effort cleanup of replaced file %r failed", old_name, exc_info=True
        )


def _parse_iso8601_duration_minutes(duration: str) -> int:
    if not (m := _ISO8601_DURATION_RE.match(duration)):
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


class SphereRepository(SphereRepositoryProtocol, SphereDirectoryRepositoryProtocol):
    @staticmethod
    def list_all() -> list[SphereListItemDTO]:
        return [
            SphereListItemDTO(pk=sphere.pk, name=sphere.name, domain=sphere.site.domain)
            for sphere in Sphere.objects.select_related("site").order_by("name")
        ]

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

    @staticmethod
    def update(sphere_id: int, data: SphereUpdateData) -> None:
        try:
            sphere = Sphere.objects.get(id=sphere_id)
        except Sphere.DoesNotExist as exception:
            raise NotFoundError from exception

        for key, value in data.items():
            setattr(sphere, key, value)
        sphere.save(update_fields=list(data.keys()))


class SessionRepository(SessionRepositoryProtocol):  # noqa: PLR0904
    @staticmethod
    def create(
        session_data: SessionData,
        tag_ids: Iterable[int],
        time_slot_ids: Iterable[int] = (),
        facilitator_ids: Iterable[int] = (),
        track_ids: Iterable[int] = (),
    ) -> int:
        session = Session.objects.create(**session_data)
        session.tags.set(tag_ids)
        if time_slot_ids:
            session.time_slots.set(time_slot_ids)
        if facilitator_ids:
            session.facilitators.set(facilitator_ids)
        if track_ids:
            session.tracks.set(track_ids)
        return session.pk

    @staticmethod
    def read(pk: int) -> SessionDTO:
        try:
            session = Session.objects.select_related("category").get(id=pk)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        return SessionDTO.model_validate(session)

    @staticmethod
    def read_presenter(session_id: int) -> UserDTO | None:
        try:
            session = Session.objects.select_related("presenter").get(id=session_id)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        if session.presenter is None:
            return None
        return UserDTO.model_validate(session.presenter)

    @staticmethod
    def lock(pk: int) -> None:
        try:
            Session.objects.select_for_update().get(pk=pk)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception

    @staticmethod
    def update(pk: int, data: SessionUpdateData) -> None:
        if "cover_image" not in data:
            Session.objects.filter(id=pk).update(**data)
            return
        try:
            session = Session.objects.get(id=pk)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        old_cover = session.cover_image.name
        for key, value in data.items():
            setattr(session, key, value)
        session.save(update_fields=list(data.keys()))
        if old_cover and old_cover != session.cover_image.name:
            delete_stored_file(session.cover_image, old_cover)

    @staticmethod
    def soft_delete(pk: int) -> None:
        # Reach through `all_objects` so an already-dead row raises NotFound
        # instead of silently re-stamping `deleted_at`.
        try:
            session = Session.all_objects.get(id=pk, deleted_at__isnull=True)
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        session.soft_delete()

    @staticmethod
    def restore(pk: int, event_pk: int) -> None:
        # Scope + existence in one query: a soft-deleted session in this event.
        # (The alive-manager service check can't see deleted rows, so event
        # scoping lives here.) Missing / wrong-event / already-alive -> NotFound.
        # `select_for_update` locks the row so concurrent restores serialize
        # (caller runs inside a transaction); the second sees it already alive.
        try:
            session = Session.all_objects.select_for_update().get(
                id=pk, category__event_id=event_pk, deleted_at__isnull=False
            )
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        session.restore()

    @staticmethod
    def list_deleted_by_event(event_pk: int) -> list[SessionListItemDTO]:
        qs = (
            Session.all_objects.filter(
                category__event_id=event_pk, deleted_at__isnull=False
            )
            .select_related("presenter", "category")
            .order_by("-creation_time")
        )
        return [
            SessionListItemDTO(
                pk=s.pk,
                title=s.title,
                display_name=s.display_name,
                category_name=s.category.name if s.category else "",
                status=SessionStatus(s.status),
                creation_time=s.creation_time,
            )
            for s in qs
        ]

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
            event__proposal_categories__sessions__id=session_id
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
    def slug_exists(event_id: int, slug: str) -> bool:
        return Session.objects.filter(event_id=event_id, slug=slug).exists()

    @staticmethod
    def find_id_by_slug(event_id: int, slug: str) -> int | None:
        return (
            Session.objects.filter(event_id=event_id, slug=slug)
            .values_list("id", flat=True)
            .first()
        )

    @staticmethod
    def save_field_values(session_id: int, values: list[SessionFieldValueData]) -> None:
        SessionFieldValue.objects.bulk_create(
            [
                SessionFieldValue(
                    session_id=session_id, field_id=v["field_id"], value=v["value"]
                )
                for v in values
            ],
            update_conflicts=True,
            unique_fields=["session", "field"],
            update_fields=["value"],
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
    def delete_field_values_for_fields(session_id: int, field_ids: list[int]) -> int:
        if not field_ids:
            return 0
        deleted, _ = SessionFieldValue.objects.filter(
            session_id=session_id, field_id__in=field_ids
        ).delete()
        return deleted

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
    def read_track_ids(session_id: int) -> list[int]:
        return list(
            Track.objects.filter(sessions__id=session_id).values_list("id", flat=True)
        )

    @staticmethod
    def set_session_tracks(session_pk: int, track_pks: list[int]) -> None:
        try:
            session = Session.objects.get(pk=session_pk)
        except Session.DoesNotExist as err:
            msg = f"Session with pk '{session_pk}' not found"
            raise NotFoundError(msg) from err
        session.tracks.set(track_pks)

    @staticmethod
    def set_time_slots(session_id: int, time_slot_ids: list[int]) -> None:
        try:
            session = Session.objects.get(pk=session_id)
        except Session.DoesNotExist as err:
            msg = f"Session with pk '{session_id}' not found"
            raise NotFoundError(msg) from err
        session.time_slots.set(time_slot_ids)

    @staticmethod
    def clear_field_values(session_id: int) -> None:
        SessionFieldValue.objects.filter(session_id=session_id).delete()

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
        event_pk: int, filters: UnscheduledSessionFilter
    ) -> tuple[list[UnscheduledSessionDTO], bool]:
        qs = (
            Session.objects.filter(category__event_id=event_pk)
            .exclude(status=SessionStatus.REJECTED)
            .filter(agenda_item__isnull=True)
            .select_related("category")
        )
        if filters.track_pk is not None:
            qs = qs.filter(tracks__pk=filters.track_pk)
        if filters.available_on is not None:
            qs = qs.filter(
                Q(time_slots__isnull=True)
                | Q(time_slots__start_time__date=filters.available_on)
            ).distinct()
        if filters.category_pk is not None:
            qs = qs.filter(category__pk=filters.category_pk)
        if filters.search:
            qs = qs.filter(
                Q(title__icontains=filters.search)
                | Q(display_name__icontains=filters.search)
            ).distinct()
        results: list[UnscheduledSessionDTO] = []
        has_more = False
        for s in qs.order_by("title").iterator():
            duration_minutes = _parse_iso8601_duration_minutes(s.duration)
            if (
                filters.max_duration_minutes is not None
                and duration_minutes > filters.max_duration_minutes
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
    def list_for_events_page(
        sphere_id: int, *, include_unpublished: bool
    ) -> list[EventListItemDTO]:
        agenda_item_count = (
            AgendaItem.objects.filter(session__event=OuterRef("pk"))
            .order_by()
            .values("session__event")
            .annotate(count=Count("pk"))
            .values("count")
        )
        events = Event.objects.filter(sphere_id=sphere_id).annotate(
            session_count=Coalesce(
                Subquery(agenda_item_count, output_field=IntegerField()), 0
            )
        )
        if not include_unpublished:
            events = events.filter(publication_time__lte=datetime.now(tz=UTC))
        return [
            EventListItemDTO.model_validate(event)
            for event in events.order_by("start_time")
        ]

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
        sessions = Session.objects.filter(category__event_id=event_id)
        scheduled = Session.objects.filter(event_id=event_id, agenda_item__isnull=False)
        spaces = Space.objects.filter(event_id=event_id)

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

        old_cover = event.cover_image.name if "cover_image" in data else None

        for key, value in data.items():
            setattr(event, key, value)
        event.save(update_fields=list(data.keys()))

        if old_cover and old_cover != event.cover_image.name:
            delete_stored_file(event.cover_image, old_cover)

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

    @staticmethod
    def update_allow_anonymous_proposals(event_id: int, *, allow: bool) -> None:
        settings, _ = EventProposalSettings.objects.get_or_create(event_id=event_id)
        settings.allow_anonymous_proposals = allow
        settings.save(update_fields=["allow_anonymous_proposals"])


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


class SpaceRepository(SpaceRepositoryProtocol):
    @staticmethod
    def read(pk: int) -> SpaceDTO:
        try:
            space = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        return SpaceDTO.model_validate(space)

    @staticmethod
    def delete(pk: int) -> None:
        Space.objects.filter(pk=pk).delete()

    @staticmethod
    def lock(pk: int) -> None:
        try:
            Space.objects.select_for_update().get(pk=pk)
        except Space.DoesNotExist as exception:
            raise NotFoundError from exception

    @staticmethod
    def list_by_event(event_pk: int) -> list[SpaceDTO]:
        spaces = Space.objects.filter(event_id=event_pk).order_by("order", "name")
        return [SpaceDTO.model_validate(space) for space in spaces]


class SpaceTreeRepository(SpaceTreeRepositoryProtocol):
    @staticmethod
    def list_tree(event_pk: int) -> list[SpaceNodeDTO]:
        # One query for the whole event; assemble the tree in Python.
        spaces = list(Space.objects.filter(event_id=event_pk).order_by("order", "name"))
        children_by_parent: dict[int | None, list[Space]] = defaultdict(list)
        for space in spaces:
            children_by_parent[space.parent_id].append(space)

        def build(space: Space, depth: int) -> SpaceNodeDTO:
            kids = children_by_parent.get(space.pk, [])
            return SpaceNodeDTO(
                pk=space.pk,
                event_id=space.event_id,
                parent_id=space.parent_id,
                name=space.name,
                slug=space.slug,
                capacity=space.capacity,
                description=space.description,
                order=space.order,
                depth=depth,
                is_leaf=not kids,
                children=[build(kid, depth + 1) for kid in kids],
            )

        return [build(root, 1) for root in children_by_parent.get(None, [])]

    def read(self, pk: int) -> SpaceNodeDTO:
        try:
            space = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        return self._node(space)

    @transaction.atomic
    def create(
        self,
        *,
        event_id: int,
        parent_id: int | None,
        name: str,
        capacity: int | None,
        description: str,
    ) -> SpaceNodeDTO:
        slug = self.generate_unique_slug(event_id, parent_id, slugify(name))
        max_order = Space.objects.filter(
            event_id=event_id, parent_id=parent_id
        ).aggregate(top=Max("order"))["top"]
        space = Space(
            event_id=event_id,
            parent_id=parent_id,
            name=name,
            slug=slug,
            capacity=capacity,
            description=description,
            order=(max_order if max_order is not None else -1) + 1,
        )
        space.full_clean()
        space.save()
        return self._node(space)

    @transaction.atomic
    def update(
        self,
        *,
        pk: int,
        name: str,
        capacity: int | None,
        description: str,
        parent_id: int | None,
    ) -> SpaceNodeDTO:
        try:
            space = Space.objects.select_for_update().get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        parent_changed = space.parent_id != parent_id
        # Re-derive the slug whenever the name or parent changes, so it stays
        # unique among the (new) siblings. full_clean() below is the backstop
        # for cycles, depth, and the leaf-with-session rule.
        if space.name != name or parent_changed:
            space.name = name
            space.parent_id = parent_id
            space.slug = self.generate_unique_slug(
                space.event_id, parent_id, slugify(name), exclude_pk=pk
            )
        if parent_changed:
            # Append to the end of the new parent's sibling list.
            max_order = (
                Space.objects.filter(event_id=space.event_id, parent_id=parent_id)
                .exclude(pk=pk)
                .aggregate(top=Max("order"))["top"]
            )
            space.order = (max_order if max_order is not None else -1) + 1
        space.capacity = capacity
        space.description = description
        space.full_clean()
        space.save()
        return self._node(space)

    @staticmethod
    def delete(pk: int) -> None:
        # FK parent on_delete=CASCADE removes the whole subtree.
        Space.objects.filter(pk=pk).delete()

    @staticmethod
    def reorder(parent_id: int | None, child_pks: list[int], event_id: int) -> None:
        # Constrain by event so a root-level reorder (parent_id=None) can only
        # touch spaces belonging to the caller's event, never another event's.
        space_map = {
            space.pk: space
            for space in Space.objects.filter(
                event_id=event_id, parent_id=parent_id, pk__in=child_pks
            )
        }
        for order, pk in enumerate(child_pks):
            space = space_map.get(pk)
            if space is not None and space.order != order:
                space.order = order
                space.save(update_fields=["order", "modification_time"])

    @staticmethod
    def subtree_has_sessions(pk: int) -> bool:
        event_pk = Space.objects.values_list("event_id", flat=True).get(pk=pk)
        children_by_parent: dict[int, list[int]] = defaultdict(list)
        for child_pk, parent_pk in Space.objects.filter(event_id=event_pk).values_list(
            "pk", "parent_id"
        ):
            children_by_parent[parent_pk].append(child_pk)

        subtree: list[int] = []

        def collect(node_pk: int) -> None:
            subtree.append(node_pk)
            for child_pk in children_by_parent.get(node_pk, []):
                collect(child_pk)

        collect(pk)
        # Lock the subtree's Space rows (deterministic pk order) so a concurrent
        # session assignment to any leaf below serialises behind this
        # check-then-delete — assign_session locks the same Space row first,
        # so its AgendaItem can't slip in before the cascade. Safe because the
        # sole caller runs inside delete_space's atomic() block.
        list(Space.objects.select_for_update().filter(pk__in=subtree).order_by("pk"))
        return AgendaItem.objects.filter(space_id__in=subtree).exists()

    @staticmethod
    def space_pks_with_sessions(event_id: int) -> frozenset[int]:
        # Spaces that directly hold a scheduled session — these can't become a
        # parent (a leaf-with-session can't turn into a branch). One query.
        return frozenset(
            AgendaItem.objects.filter(space__event_id=event_id)
            .values_list("space_id", flat=True)
            .distinct()
        )

    @staticmethod
    def generate_unique_slug(
        event_id: int,
        parent_id: int | None,
        base_slug: str,
        exclude_pk: int | None = None,
    ) -> str:
        slug = base_slug
        for _ in range(4):
            query = Space.objects.filter(
                event_id=event_id, parent_id=parent_id, slug=slug
            )
            if exclude_pk:
                query = query.exclude(pk=exclude_pk)
            if not query.exists():
                return slug
            slug = f"{base_slug}-{token_urlsafe(3)}"
        return slug

    @transaction.atomic
    def duplicate(self, pk: int, new_name: str) -> SpaceNodeDTO:
        try:
            source = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        clone = self._clone_subtree(
            source, event_id=source.event_id, parent_id=source.parent_id, name=new_name
        )
        return self._node(clone)

    @transaction.atomic
    def copy_to_event(self, pk: int, target_event_id: int) -> SpaceNodeDTO:
        try:
            source = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        # The copied subtree becomes a root in the target event.
        clone = self._clone_subtree(source, event_id=target_event_id, parent_id=None)
        return self._node(clone)

    def _clone_subtree(
        self,
        source: Space,
        *,
        event_id: int,
        parent_id: int | None,
        name: str | None = None,
    ) -> Space:
        clone_name = name if name is not None else source.name
        clone = Space.objects.create(
            event_id=event_id,
            parent_id=parent_id,
            name=clone_name,
            slug=self.generate_unique_slug(event_id, parent_id, slugify(clone_name)),
            capacity=source.capacity,
            description=source.description,
            order=source.order,
        )
        for child in Space.objects.filter(parent_id=source.pk).order_by("order"):
            self._clone_subtree(child, event_id=event_id, parent_id=clone.pk)
        return clone

    @staticmethod
    def _node(space: Space) -> SpaceNodeDTO:
        return SpaceNodeDTO(
            pk=space.pk,
            event_id=space.event_id,
            parent_id=space.parent_id,
            name=space.name,
            slug=space.slug,
            capacity=space.capacity,
            description=space.description,
            order=space.order,
            depth=1 + sum(1 for _ in space.iter_ancestors()),
            is_leaf=not space.children.exists(),
            children=[],
        )


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

    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int:
        category, _ = ProposalCategory.objects.get_or_create(
            event_id=event_id, slug=slug, defaults={"name": name}
        )
        return category.pk

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
        PersonalDataFieldRequirement.objects.filter(category_id=category_id).delete()

        order_map = {fid: idx for idx, fid in enumerate(order or [])}

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
        SessionFieldRequirement.objects.filter(category_id=category_id).delete()

        order_map = {fid: idx for idx, fid in enumerate(order or [])}

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
        base_slug = data.get("slug") or slugify(data["name"])
        slug = self.generate_unique_slug(event_id, base_slug)

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
    def delete_orphans_for_event(event_id: int) -> int:
        # A PersonalDataField is orphan when no facilitator on this event has
        # a HostPersonalData entry that points at it. Used by the importer's
        # "Apply field layout" action after removing values for unmapped
        # fields.
        deleted, _ = (
            PersonalDataField.objects.filter(event_id=event_id)
            .annotate(usage=Count("values"))
            .filter(usage=0)
            .delete()
        )
        return deleted

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
        base_slug = data.get("slug") or slugify(data["name"])
        slug = self.generate_unique_slug(event_id, base_slug)

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
    def delete_orphans_for_event(event_id: int) -> int:
        # A SessionField is orphan when no session on this event has a
        # SessionFieldValue pointing at it. Used by the importer's "Apply
        # field layout" action.
        deleted, _ = (
            SessionField.objects.filter(event_id=event_id)
            .annotate(usage=Count("values"))
            .filter(usage=0)
            .delete()
        )
        return deleted

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
    def list_field_ids_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> list[int]:
        return list(
            HostPersonalData.objects.filter(
                facilitator_id=facilitator_id, event_id=event_id
            ).values_list("field_id", flat=True)
        )

    @staticmethod
    def delete_by_facilitators(facilitator_ids: list[int]) -> None:
        HostPersonalData.objects.filter(facilitator_id__in=facilitator_ids).delete()

    @staticmethod
    def delete_for_facilitator_fields(facilitator_id: int, field_ids: list[int]) -> int:
        if not field_ids:
            return 0
        deleted, _ = HostPersonalData.objects.filter(
            facilitator_id=facilitator_id, field_id__in=field_ids
        ).delete()
        return deleted


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
    def get_or_create(event_id: int, start_time: datetime, end_time: datetime) -> int:
        # Reuse a window the event already has (deduped by exact start+end) so
        # the importer can attach it without spawning duplicates on re-runs.
        time_slot, _ = TimeSlot.objects.get_or_create(
            event_id=event_id, start_time=start_time, end_time=end_time
        )
        return time_slot.pk

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
        old_header = encounter.header_image.name if "header_image" in data else None
        for key, value in data.items():
            setattr(encounter, key, value)
        encounter.save()
        if old_header and old_header != encounter.header_image.name:
            delete_stored_file(encounter.header_image, old_header)

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

    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int:
        track, _ = Track.objects.get_or_create(
            event_id=event_id, slug=slug, defaults={"name": name}
        )
        return track.pk

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


_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT = "connection_unique_display_name_per_sphere"
_SQLITE_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT = (
    "UNIQUE constraint failed: connection.sphere_id, connection.display_name"
)


def is_connection_display_name_conflict(exc: IntegrityError) -> bool:
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


class AnnouncementsRepository(AnnouncementsRepositoryProtocol):
    @staticmethod
    def list_for_sphere(sphere_id: int) -> list[AnnouncementDTO]:
        return [
            AnnouncementDTO.model_validate(a)
            for a in Announcement.objects.filter(sphere_id=sphere_id)
        ]

    @staticmethod
    def list_published(sphere_id: int) -> list[AnnouncementDTO]:
        return [
            AnnouncementDTO.model_validate(a)
            for a in Announcement.objects.filter(sphere_id=sphere_id, is_published=True)
        ]

    @staticmethod
    def get(sphere_id: int, pk: int) -> AnnouncementDTO:
        try:
            announcement = Announcement.objects.get(pk=pk, sphere_id=sphere_id)
        except Announcement.DoesNotExist as exc:
            raise NotFoundError from exc
        return AnnouncementDTO.model_validate(announcement)

    @staticmethod
    def create(sphere_id: int, data: AnnouncementData) -> AnnouncementDTO:
        announcement = Announcement.objects.create(
            sphere_id=sphere_id,
            title=data.title,
            content=data.content,
            is_published=data.is_published,
        )
        return AnnouncementDTO.model_validate(announcement)

    @staticmethod
    def update(sphere_id: int, pk: int, data: AnnouncementData) -> AnnouncementDTO:
        try:
            announcement = Announcement.objects.get(pk=pk, sphere_id=sphere_id)
        except Announcement.DoesNotExist as exc:
            raise NotFoundError from exc
        announcement.title = data.title
        announcement.content = data.content
        announcement.is_published = data.is_published
        announcement.save(
            update_fields=["title", "content", "is_published", "modification_time"]
        )
        return AnnouncementDTO.model_validate(announcement)

    @staticmethod
    def delete(sphere_id: int, pk: int) -> None:
        deleted, _ = Announcement.objects.filter(pk=pk, sphere_id=sphere_id).delete()
        if not deleted:
            raise NotFoundError


class DiscountRepository(DiscountRepositoryProtocol):
    @staticmethod
    def list_by_event(event_pk: int) -> list[DiscountDTO]:
        return [
            DiscountDTO.model_validate(d)
            for d in Discount.objects.filter(event_id=event_pk)
        ]

    @staticmethod
    def get(pk: int) -> DiscountDTO:
        try:
            discount = Discount.objects.get(pk=pk)
        except Discount.DoesNotExist as exception:
            raise NotFoundError from exception
        return DiscountDTO.model_validate(discount)

    @staticmethod
    def create(event_pk: int, data: DiscountData) -> DiscountDTO:
        discount = Discount.objects.create(
            event_id=event_pk,
            facilitator_id=data.facilitator_id,
            kind=data.kind,
            value=data.value,
            note=data.note,
        )
        return DiscountDTO.model_validate(discount)

    @staticmethod
    def update(pk: int, data: DiscountData) -> DiscountDTO:
        try:
            discount = Discount.objects.get(pk=pk)
        except Discount.DoesNotExist as exception:
            raise NotFoundError from exception
        discount.facilitator_id = data.facilitator_id
        discount.kind = data.kind
        discount.value = data.value
        discount.note = data.note
        discount.save(
            update_fields=["facilitator", "kind", "value", "note", "modification_time"]
        )
        return DiscountDTO.model_validate(discount)

    @staticmethod
    def soft_delete(pk: int) -> None:
        # Reach through `all_objects` so an already-dead row raises NotFound
        # instead of silently re-stamping `deleted_at`.
        try:
            discount = Discount.all_objects.get(id=pk, deleted_at__isnull=True)
        except Discount.DoesNotExist as exception:
            raise NotFoundError from exception
        discount.soft_delete()


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
    def create(sphere_id: int, display_name: str) -> ConnectionDTO:
        try:
            connection = Connection.objects.create(
                sphere_id=sphere_id, display_name=display_name
            )
        except IntegrityError as exc:
            if is_connection_display_name_conflict(exc):
                raise DuplicateConnectionDisplayNameError from exc
            raise
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def update(sphere_id: int, pk: int, display_name: str) -> ConnectionDTO:
        try:
            connection = Connection.objects.get(pk=pk, sphere_id=sphere_id)
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        connection.display_name = display_name
        try:
            connection.save(update_fields=["display_name"])
        except IntegrityError as exc:
            if is_connection_display_name_conflict(exc):
                raise DuplicateConnectionDisplayNameError from exc
            raise
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def update_secret(sphere_id: int, pk: int, blob: bytes) -> None:
        updated = Connection.objects.filter(pk=pk, sphere_id=sphere_id).update(
            secret=blob
        )
        if not updated:
            raise NotFoundError

    @staticmethod
    def read_secret(sphere_id: int, pk: int) -> bytes:
        try:
            connection = Connection.objects.only("secret").get(
                pk=pk, sphere_id=sphere_id
            )
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        return bytes(connection.secret)

    @staticmethod
    def delete(sphere_id: int, pk: int) -> None:
        try:
            deleted, _ = Connection.objects.filter(pk=pk, sphere_id=sphere_id).delete()
        except ProtectedError as exc:
            raise ConnectionInUseError from exc
        if not deleted:
            raise NotFoundError


def _event_integration_dto(integration: EventIntegration) -> EventIntegrationDTO:
    return EventIntegrationDTO(
        pk=integration.pk,
        event_id=integration.event_id,
        kind=IntegrationKind(integration.kind),
        implementation=IntegrationImplementationId(integration.implementation),
        connection_id=integration.connection_id,
        connection_display_name=integration.connection.display_name,
        display_name=integration.display_name,
        config_json=integration.config_json or "{}",
        settings_json=integration.settings_json or "{}",
        questions_snapshot_json=integration.questions_snapshot_json or "[]",
    )


class EventIntegrationsRepository(EventIntegrationsRepositoryProtocol):
    @staticmethod
    def list_for_event(
        event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]:
        qs = EventIntegration.objects.select_related("connection").filter(
            event_id=event_id
        )
        if kind is not None:
            qs = qs.filter(kind=kind.value)
        return [_event_integration_dto(i) for i in qs.order_by("kind", "display_name")]

    @staticmethod
    def get(event_id: int, pk: int) -> EventIntegrationDTO:
        try:
            integration = EventIntegration.objects.select_related("connection").get(
                pk=pk, event_id=event_id
            )
        except EventIntegration.DoesNotExist as exc:
            raise NotFoundError from exc
        return _event_integration_dto(integration)

    @staticmethod
    def create(event_id: int, data: EventIntegrationCreateData) -> EventIntegrationDTO:
        integration = EventIntegration.objects.create(
            event_id=event_id,
            kind=data["kind"].value,
            implementation=data["implementation"].value,
            connection_id=data["connection_id"],
            display_name=data["display_name"],
            config_json=data["config_json"],
        )
        integration = EventIntegration.objects.select_related("connection").get(
            pk=integration.pk
        )
        return _event_integration_dto(integration)

    @staticmethod
    def update(
        event_id: int, pk: int, data: EventIntegrationUpdateData
    ) -> EventIntegrationDTO:
        try:
            integration = EventIntegration.objects.get(pk=pk, event_id=event_id)
        except EventIntegration.DoesNotExist as exc:
            raise NotFoundError from exc
        integration.display_name = data["display_name"]
        integration.connection_id = data["connection_id"]
        integration.config_json = data["config_json"]
        integration.save(update_fields=("display_name", "connection_id", "config_json"))
        integration = EventIntegration.objects.select_related("connection").get(
            pk=integration.pk
        )
        return _event_integration_dto(integration)

    @staticmethod
    def update_settings(
        *, event_id: int, pk: int, settings_json: str
    ) -> EventIntegrationDTO:
        try:
            integration = EventIntegration.objects.get(pk=pk, event_id=event_id)
        except EventIntegration.DoesNotExist as exc:
            raise NotFoundError from exc
        integration.settings_json = settings_json
        integration.save(update_fields=("settings_json",))
        integration = EventIntegration.objects.select_related("connection").get(
            pk=integration.pk
        )
        return _event_integration_dto(integration)

    @staticmethod
    def update_questions_snapshot(
        *, event_id: int, pk: int, questions_snapshot_json: str
    ) -> EventIntegrationDTO:
        try:
            integration = EventIntegration.objects.get(pk=pk, event_id=event_id)
        except EventIntegration.DoesNotExist as exc:
            raise NotFoundError from exc
        integration.questions_snapshot_json = questions_snapshot_json
        integration.save(update_fields=("questions_snapshot_json",))
        integration = EventIntegration.objects.select_related("connection").get(
            pk=integration.pk
        )
        return _event_integration_dto(integration)

    @staticmethod
    def delete(event_id: int, pk: int) -> None:
        deleted, _ = EventIntegration.objects.filter(pk=pk, event_id=event_id).delete()
        if not deleted:
            raise NotFoundError


def _import_log_entry_dto(entry: ImportLogEntry) -> ImportLogEntryDTO:
    return ImportLogEntryDTO(
        pk=entry.pk,
        integration_id=entry.integration_id,
        row_index=entry.row_index,
        status=ImportLogStatus(entry.status),
        reason=entry.reason or "",
        response_json=entry.response_json or "{}",
        title=entry.title or "",
        display_name=entry.display_name or "",
        session_id=entry.session_id,
        attempted_at=entry.attempted_at,
    )


class ImportLogEntryRepository(ImportLogEntryRepositoryProtocol):
    @staticmethod
    def upsert(data: ImportLogEntryCreateData) -> ImportLogEntryDTO:
        # One log entry per (integration, row_index): each attempt overwrites
        # the prior entry for that row, preserving the row's identity but
        # reflecting the latest status, reason, response snapshot, and
        # session FK. `attempted_at` resets to "now" on every upsert.
        defaults = {
            "status": data.status.value,
            "reason": data.reason,
            "response_json": data.response_json,
            "title": data.title,
            "display_name": data.display_name,
            "session_id": data.session_id,
            "attempted_at": django_timezone.now(),
        }
        entry, _ = ImportLogEntry.objects.update_or_create(
            integration_id=data.integration_id,
            row_index=data.row_index,
            defaults=defaults,
        )
        return _import_log_entry_dto(entry)

    @staticmethod
    def list_for_integration(
        integration_pk: int, *, status: ImportLogStatus | None = None, search: str = ""
    ) -> list[ImportLogEntryDTO]:
        qs = ImportLogEntry.objects.filter(integration_id=integration_pk)
        if status is not None:
            qs = qs.filter(status=status.value)
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(display_name__icontains=search)
            )
        return [_import_log_entry_dto(e) for e in qs.order_by("-attempted_at", "-pk")]

    @staticmethod
    def for_session(session_pk: int) -> ImportLogEntryDTO | None:
        # Each session has at most one log entry — the row that produced it.
        # Returns None if no log entry points at this session.
        entry = ImportLogEntry.objects.filter(session_id=session_pk).first()
        return _import_log_entry_dto(entry) if entry is not None else None

    @staticmethod
    def read(pk: int) -> ImportLogEntryDTO:
        try:
            entry = ImportLogEntry.objects.get(pk=pk)
        except ImportLogEntry.DoesNotExist as exc:
            raise NotFoundError from exc
        return _import_log_entry_dto(entry)
