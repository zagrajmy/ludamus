from datetime import UTC, datetime

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from ludamus.adapters.db.django.models import (
    SPACE_MAX_DEPTH,
    AgendaItem,
    DomainEnrollmentConfig,
    EnrollmentConfig,
    Event,
    EventIntegration,
    EventPanelSettings,
    EventSettings,
    Session,
    SessionParticipation,
    Space,
    UserEnrollmentConfig,
)
from ludamus.links.db.django.repositories.storage import delete_stored_file
from ludamus.links.db.django.users import user_dto
from ludamus.pacts import (
    DomainEnrollmentConfigDTO,
    EnrollmentConfigDTO,
    EnrollmentConfigRepositoryProtocol,
    EventDTO,
    EventListItemDTO,
    EventRepositoryProtocol,
    EventSettingsDTO,
    EventSettingsRepositoryProtocol,
    EventStatsData,
    EventUpdateData,
    NotFoundError,
    SessionDTO,
    SessionParticipationStatus,
    SessionStatus,
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
    PartyEventHistoryDTO,
    PartySessionHistoryDTO,
    PartySessionHistoryRepositoryProtocol,
    PartySessionSeatDTO,
)
from ludamus.pacts.legacy import AgendaItemDTO, LocationData
from ludamus.pacts.submissions import (
    EventPanelSettingsDTO,
    EventPanelSettingsRepositoryProtocol,
)


def event_dto(event: Event) -> EventDTO:
    settings = getattr(event, "proposal_settings", None)
    description = settings.description if settings is not None else ""
    dto = EventDTO.model_validate(event)
    return dto.model_copy(update={"proposal_description": description})


class PartySessionHistoryRepository(PartySessionHistoryRepositoryProtocol):
    @staticmethod
    def list_for_party(*, party_pk: int, viewer_pk: int) -> list[PartyEventHistoryDTO]:
        session_ids = (
            SessionParticipation.objects.filter(
                party_id=party_pk, status=SessionParticipationStatus.CONFIRMED
            )
            .values_list("session_id", flat=True)
            .distinct()
        )
        sessions = (
            Session.objects.filter(pk__in=session_ids, agenda_item__isnull=False)
            .annotate(
                enrolled_count_cached=Count(
                    "session_participations",
                    filter=Q(
                        session_participations__status__in=(
                            SessionParticipationStatus.CONFIRMED,
                            SessionParticipationStatus.OFFERED,
                        )
                    ),
                ),
                waiting_count_cached=Count(
                    "session_participations",
                    filter=Q(
                        session_participations__status=SessionParticipationStatus.WAITING
                    ),
                ),
            )
            .select_related(
                "event",
                "presenter",
                "agenda_item__space" + "__parent" * (SPACE_MAX_DEPTH - 1),
            )
            .prefetch_related(
                "event__enrollment_configs", "session_participations__user"
            )
            .order_by("agenda_item__start_time")
        )
        groups: dict[int, PartyEventHistoryDTO] = {}
        for session in sessions:
            item = _party_session_history(session, viewer_pk=viewer_pk)
            if (group := groups.get(session.event_id)) is None:
                groups[session.event_id] = PartyEventHistoryDTO(
                    event_pk=session.event_id,
                    event_name=session.event.name,
                    event_slug=session.event.slug,
                    sessions=[item],
                )
            else:
                group.sessions.append(item)
        return sorted(
            groups.values(),
            key=lambda group: group.sessions[-1].agenda_item.start_time,
            reverse=True,
        )


def _party_session_history(
    session: Session, *, viewer_pk: int
) -> PartySessionHistoryDTO:
    space = session.agenda_item.space
    participations = list(session.session_participations.all())
    return PartySessionHistoryDTO(
        session=SessionDTO.model_validate(session),
        agenda_item=AgendaItemDTO.model_validate(session.agenda_item),
        presenter=(
            user_dto(session.presenter) if session.presenter is not None else None
        ),
        participations=[
            PartySessionSeatDTO(
                user=user_dto(participation.user),
                status=SessionParticipationStatus(participation.status),
                creation_time=participation.creation_time,
            )
            for participation in participations
        ],
        location=LocationData(
            space_name=space.name,
            parent_slug=space.parent.slug if space.parent else "",
            parent_name=space.parent.name if space.parent else "",
            path=str(space),
        ),
        enrolled_count=session.enrolled_count,
        waiting_count=session.waiting_count,
        is_full=session.is_full,
        is_enrollment_available=session.is_enrollment_available,
        effective_participants_limit=session.effective_participants_limit,
        full_participant_info=session.full_participant_info,
        viewer_enrolled=any(
            participation.user_id == viewer_pk
            and participation.status == SessionParticipationStatus.CONFIRMED
            for participation in participations
        ),
    )


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
        return [event_dto(event) for event in events]

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
        return event_dto(event)

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
        return event_dto(event)

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


class EventPanelSettingsRepository(EventPanelSettingsRepositoryProtocol):
    @staticmethod
    def read_or_create(event_id: int) -> EventPanelSettingsDTO:
        settings, _ = EventPanelSettings.objects.get_or_create(event_id=event_id)
        return EventPanelSettingsDTO(
            pk=settings.pk,
            displayed_facilitator_field_ids=list(
                settings.displayed_facilitator_fields.values_list("pk", flat=True)
            ),
        )

    @staticmethod
    def update_displayed_facilitator_fields(
        event_id: int, field_ids: list[int]
    ) -> None:
        settings, _ = EventPanelSettings.objects.get_or_create(event_id=event_id)
        settings.displayed_facilitator_fields.set(field_ids)


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
