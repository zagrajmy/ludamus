import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.db.models import Count, Exists, OuterRef, Q, QuerySet

from ludamus.links.db.django.models import (
    SPACE_MAX_DEPTH,
    AgendaItem,
    Event,
    Session,
    SessionFieldValue,
    SessionParticipationStatus,
    Space,
    TimeSlot,
    Track,
)
from ludamus.links.db.django.repositories.chronology import (
    event_dto,
    location_data,
    session_card_stats,
)
from ludamus.links.db.django.repositories.storage import delete_stored_file
from ludamus.links.db.django.users import user_dto
from ludamus.pacts import (
    OCCUPYING_PARTICIPATION_STATUSES,
    UNSCHEDULED_LIST_LIMIT,
    AgendaItemDTO,
    EventDTO,
    FacilitatorDTO,
    NotFoundError,
    PendingSessionDTO,
    PendingSessionTimeSlotDTO,
    SessionData,
    SessionDTO,
    SessionFieldValueData,
    SessionFieldValueDTO,
    SessionListFilters,
    SessionListItemDTO,
    SessionRepositoryProtocol,
    SessionStatus,
    SessionUpdateData,
    SpaceOptionDTO,
    TimeSlotDTO,
    TrackDTO,
    UnscheduledSessionDTO,
    UnscheduledSessionFilter,
)
from ludamus.pacts.chronology import (
    SessionModalDTO,
    SessionModalRepositoryProtocol,
    SessionModalSeatDTO,
)
from ludamus.pacts.crowd import UserDTO

if TYPE_CHECKING:
    from collections.abc import Iterable

_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")


def _parse_iso8601_duration_minutes(duration: str) -> int:
    if not (m := _ISO8601_DURATION_RE.match(duration)):
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


def annotate_session_participation_counts(
    queryset: QuerySet[Session],
) -> QuerySet[Session]:
    return queryset.annotate(
        enrolled_count_cached=Count(
            "session_participations",
            filter=Q(
                session_participations__status__in=OCCUPYING_PARTICIPATION_STATUSES
            ),
        ),
        waiting_count_cached=Count(
            "session_participations",
            filter=Q(session_participations__status=SessionParticipationStatus.WAITING),
        ),
    )


def with_session_card_relations(queryset: QuerySet[Session]) -> QuerySet[Session]:
    # str(space) walks the whole ancestor chain, so eager-load every level up to
    # the max nesting depth to avoid per-row parent queries.
    return queryset.select_related(
        "presenter",
        "agenda_item__space" + "__parent" * (SPACE_MAX_DEPTH - 1),
        "event",
        "event__sphere",
        "category",
    ).prefetch_related(
        "session_participations__user",
        "field_values__field",
        "event__enrollment_configs",
        "tracks",
    )


def field_value_dto(fv: SessionFieldValue) -> SessionFieldValueDTO:
    return SessionFieldValueDTO(
        allow_custom=fv.field.allow_custom,
        field_icon=fv.field.icon,
        field_id=fv.field_id,
        field_name=fv.field.name,
        field_order=fv.field.order,
        field_question=fv.field.question,
        field_slug=fv.field.slug,
        field_type=fv.field.field_type,
        is_public=fv.field.is_public,
        value=fv.value,
    )


def _session_modal_dto(
    session: Session, *, viewer_user_ids: list[int], editor_user_id: int | None
) -> SessionModalDTO:
    now = datetime.now(tz=UTC)
    agenda_item = session.agenda_item
    participations = list(session.session_participations.all())
    viewer_ids = set(viewer_user_ids)
    field_values = sorted(
        (
            field_value_dto(fv)
            for fv in session.field_values.all()
            if fv.field.is_public
        ),
        key=lambda fv: (fv.field_order, fv.field_name),
    )
    event = session.event
    event_override = event.allow_facilitator_session_edit
    sphere_default = event.sphere.allow_facilitator_session_edit
    edit_allowed = sphere_default if event_override is None else event_override
    return SessionModalDTO(
        session=SessionDTO.model_validate(session),
        agenda_item=AgendaItemDTO.model_validate(agenda_item),
        presenter=(
            user_dto(session.presenter) if session.presenter is not None else None
        ),
        participations=[
            SessionModalSeatDTO(
                user=user_dto(participation.user),
                status=SessionParticipationStatus(participation.status),
                creation_time=participation.creation_time,
            )
            for participation in participations
        ],
        location=location_data(agenda_item.space),
        field_values=field_values,
        **session_card_stats(session).model_dump(),
        viewer_enrolled=any(
            participation.user_id in viewer_ids
            and participation.status == SessionParticipationStatus.CONFIRMED
            for participation in participations
        ),
        viewer_waiting=any(
            participation.user_id in viewer_ids
            and participation.status == SessionParticipationStatus.WAITING
            for participation in participations
        ),
        can_edit=(
            edit_allowed
            and session.presenter_id is not None
            and session.presenter_id == editor_user_id
        ),
        is_ongoing=agenda_item.start_time <= now,
        is_ended=agenda_item.end_time <= now,
    )


class SessionRepository(  # ruff:ignore[too-many-public-methods]
    SessionRepositoryProtocol, SessionModalRepositoryProtocol
):
    @staticmethod
    def read_modal(
        *,
        event_id: int,
        session_id: int,
        viewer_user_ids: list[int],
        editor_user_id: int | None,
    ) -> SessionModalDTO | None:
        base = annotate_session_participation_counts(
            Session.objects.filter(agenda_item__isnull=False)
        )
        try:
            session = with_session_card_relations(base).get(
                pk=session_id, event_id=event_id
            )
        except Session.DoesNotExist:
            return None
        return _session_modal_dto(
            session, viewer_user_ids=viewer_user_ids, editor_user_id=editor_user_id
        )

    @staticmethod
    def create(
        session_data: SessionData,
        *,
        time_slot_ids: Iterable[int] = (),
        facilitator_ids: Iterable[int] = (),
        track_ids: Iterable[int] = (),
    ) -> int:
        session = Session.objects.create(**session_data)
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
            .annotate(
                is_scheduled=Exists(
                    AgendaItem.objects.filter(session_id=OuterRef("pk"))
                )
            )
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
                is_scheduled=s.is_scheduled,
            )
            for s in qs
        ]

    @staticmethod
    def list_by_facilitator(facilitator_id: int) -> list[SessionListItemDTO]:
        qs = (
            Session.objects.filter(facilitators__id=facilitator_id)
            .select_related("category")
            .annotate(
                is_scheduled=Exists(
                    AgendaItem.objects.filter(session_id=OuterRef("pk"))
                )
            )
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
                is_scheduled=s.is_scheduled,
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
        return event_dto(event)

    @staticmethod
    def read_space_options(session_id: int) -> list[SpaceOptionDTO]:
        # Only leaves (childless nodes) are bookable; group each by its
        # immediate parent's name so the picker can render optgroups.
        spaces = (
            Space.objects.filter(
                event__proposal_categories__sessions__id=session_id,
                children__isnull=True,
            )
            .select_related("parent")
            .order_by("order", "name")
        )
        return [
            SpaceOptionDTO(
                pk=space.id,
                name=space.name,
                group=space.parent.name if space.parent else "",
            )
            for space in spaces
        ]

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
            .prefetch_related("time_slots")
            .order_by("-creation_time")
        )
        return [
            PendingSessionDTO(
                contact_email=s.contact_email,
                creation_time=s.creation_time,
                description=s.description,
                participants_limit=s.participants_limit,
                pk=s.pk,
                display_name=s.display_name,
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
    def find_id_by_ident(event_id: int, ident: str) -> int | None:
        return (
            Session.objects.filter(event_id=event_id, ident=ident)
            .values_list("id", flat=True)
            .first()
        )

    @staticmethod
    def find_ids_by_title_and_email(
        *, event_id: int, title: str, contact_email: str
    ) -> list[int]:
        return list(
            Session.objects.filter(
                event_id=event_id, title=title, contact_email=contact_email, ident=""
            ).values_list("id", flat=True)
        )

    @staticmethod
    def set_ident(pk: int, ident: str) -> None:
        Session.objects.filter(id=pk).update(ident=ident)

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
        return [field_value_dto(v) for v in values]

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
        event_id: int, filters: SessionListFilters | None = None
    ) -> list[SessionListItemDTO]:
        filters = filters or {}
        field_filters = filters.get("field_filters")
        search = filters.get("search")
        track_pk = filters.get("track_pk")
        multi_tracks = filters.get("multi_tracks")
        category_pk = filters.get("category_pk")
        status = filters.get("status")
        scheduled = filters.get("scheduled")
        qs = (
            Session.objects.filter(category__event_id=event_id)
            .select_related("presenter", "category")
            .annotate(
                is_scheduled=Exists(
                    AgendaItem.objects.filter(session_id=OuterRef("pk"))
                )
            )
        )

        if category_pk is not None:
            qs = qs.filter(category_id=category_pk)

        if status is not None:
            qs = qs.filter(status=status)

        if scheduled is not None:
            qs = qs.filter(is_scheduled=scheduled)

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

        if multi_tracks:
            qs = qs.annotate(_track_count=Count("tracks", distinct=True)).filter(
                _track_count__gt=1
            )

        return [
            SessionListItemDTO(
                pk=s.pk,
                title=s.title,
                display_name=s.display_name,
                category_name=s.category.name if s.category else "",
                status=SessionStatus(s.status),
                creation_time=s.creation_time,
                is_scheduled=s.is_scheduled,
            )
            for s in qs.order_by("-creation_time")
        ]

    @staticmethod
    def read_track_ids(session_id: int) -> list[int]:
        return list(
            Track.objects.filter(sessions__id=session_id).values_list("id", flat=True)
        )

    @staticmethod
    def read_tracks(session_id: int) -> list[TrackDTO]:
        return [
            TrackDTO.model_validate(t)
            for t in Track.objects.filter(sessions__id=session_id)
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
            .filter(status=SessionStatus.ACCEPTED)
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
