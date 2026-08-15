from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.db.models import Count, F, OuterRef, Q, QuerySet, Subquery

from ludamus.links.db.django.agenda_item import (
    confirmed_item_count,
    scheduled_item_count,
)
from ludamus.links.db.django.models import Facilitator, PersonalDataFieldValue
from ludamus.pacts import (
    FacilitatorData,
    FacilitatorDTO,
    FacilitatorListItemDTO,
    FacilitatorRepositoryProtocol,
    FacilitatorUpdateData,
    NotFoundError,
)
from ludamus.pacts.legacy import ConfirmationCountsRow, ConfirmationFacilitatorRow

if TYPE_CHECKING:
    from ludamus.pacts.submissions import FacilitatorListFilters

_FACILITATOR_SORT_FIELDS = {
    "name": "display_name",
    "accreditation": "accreditation_type",
    "sessions": "session_count",
    "linked": "user_id",
    "organizer": "organizer__name",
}


def _readable_facilitators() -> QuerySet[Facilitator]:
    # Every single-facilitator read carries the organizer's name, so a page
    # that shows it needs no second lookup through the user repo.
    return Facilitator.objects.annotate(organizer_name=F("organizer__name"))


def _order_facilitators(qs: QuerySet[Facilitator], sort: str) -> QuerySet[Facilitator]:
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    # `field_<pk>` sorts by a personal-data column: annotate its value via a
    # correlated subquery. JSON values order by their text form — good enough
    # to line up near-duplicate entries.
    if key.startswith("field_") and key[len("field_") :].isdigit():
        field_id = int(key[len("field_") :])
        qs = qs.annotate(
            _sort_value=Subquery(
                PersonalDataFieldValue.objects.filter(
                    facilitator_id=OuterRef("pk"), field_id=field_id
                ).values("value")[:1]
            )
        )
        order_field = "_sort_value"
    else:
        order_field = _FACILITATOR_SORT_FIELDS.get(key, "display_name")
    order = f"-{order_field}" if descending else order_field
    return qs.order_by(order, "display_name", "pk")


class FacilitatorRepository(FacilitatorRepositoryProtocol):
    @staticmethod
    def create(data: FacilitatorData) -> FacilitatorDTO:
        facilitator = Facilitator.objects.create(**data)
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read(pk: int) -> FacilitatorDTO:
        try:
            facilitator = _readable_facilitators().get(pk=pk)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def find_by_event_and_display_name(
        event_id: int, display_name: str
    ) -> FacilitatorDTO | None:
        facilitator = (
            _readable_facilitators()
            .filter(event_id=event_id, display_name=display_name)
            .first()
        )
        if facilitator is None:
            return None
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read_by_event_and_slug(event_id: int, slug: str) -> FacilitatorDTO:
        try:
            facilitator = _readable_facilitators().get(event_id=event_id, slug=slug)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read_by_user_and_event(user_id: int, event_id: int) -> FacilitatorDTO:
        try:
            facilitator = _readable_facilitators().get(
                user_id=user_id, event_id=event_id
            )
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def find_id_by_ident(event_id: int, ident: str) -> int | None:
        return (
            Facilitator.objects.filter(event_id=event_id, ident=ident)
            .values_list("id", flat=True)
            .first()
        )

    @staticmethod
    def set_ident(pk: int, ident: str) -> None:
        Facilitator.objects.filter(id=pk).update(ident=ident)

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
    def list_by_event(
        event_id: int, filters: FacilitatorListFilters | None = None
    ) -> list[FacilitatorListItemDTO]:
        filters = filters or {}
        qs = Facilitator.objects.filter(event_id=event_id).annotate(
            session_count=Count("sessions", distinct=True),
            organizer_name=F("organizer__name"),
        )

        if pks := filters.get("pks"):
            qs = qs.filter(pk__in=pks)

        if search := filters.get("search"):
            # Text personal-data values are stored JSON-encoded; match both the
            # raw string and its JSON-escaped form (mirrors proposals search).
            encoded = json.dumps(search)[1:-1]
            text_value = Q(personal_data__field__field_type="text") & (
                Q(personal_data__value__icontains=search)
                | Q(personal_data__value__icontains=encoded)
            )
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(user__name__icontains=search)
                | text_value
            ).distinct()

        if accreditation := filters.get("accreditation"):
            qs = qs.filter(accreditation_type=accreditation)

        if filters.get("flagged"):
            qs = qs.filter(flagged_for_deletion=True)

        if filters.get("organizer_unassigned"):
            qs = qs.filter(organizer__isnull=True)
        elif organizer_id := filters.get("organizer_id"):
            qs = qs.filter(organizer_id=organizer_id)

        for field_id, value in (filters.get("field_filters") or {}).items():
            # Each condition is its own join, so different fields AND together.
            qs = qs.filter(personal_data__field_id=field_id, personal_data__value=value)

        ordered = _order_facilitators(qs, filters.get("sort") or "name")
        # A picker asks for one row more than it shows, so "there are more"
        # costs no extra COUNT -- and a one-letter search never drags the whole
        # roster into memory to throw most of it away.
        if limit := filters.get("limit"):
            ordered = ordered[:limit]
        return [FacilitatorListItemDTO.model_validate(f) for f in ordered]

    @staticmethod
    def list_by_slugs(
        event_id: int, facilitator_slugs: list[str]
    ) -> list[FacilitatorListItemDTO]:
        if not facilitator_slugs:
            return []
        facilitators = Facilitator.objects.filter(
            event_id=event_id, slug__in=facilitator_slugs
        ).annotate(session_count=Count("sessions", distinct=True))
        by_slug = {f.slug: f for f in facilitators}
        # The caller's order is the answer's order; a slug this event doesn't
        # have drops out rather than raising.
        return [
            FacilitatorListItemDTO.model_validate(by_slug[slug])
            for slug in facilitator_slugs
            if slug in by_slug
        ]

    @staticmethod
    def count_confirmations_by_organizer(event_pk: int) -> list[ConfirmationCountsRow]:
        # Grouping by organizer folds every unclaimed facilitator into a single
        # `organizer_id=None` row — the backlog nobody took on.
        rows = (
            Facilitator.objects.filter(event_id=event_pk)
            .values("organizer_id", "organizer__name")
            .annotate(
                facilitator_count=Count("pk", distinct=True),
                scheduled_count=scheduled_item_count(),
                confirmed_count=confirmed_item_count(),
            )
            .order_by("organizer__name")
        )
        return [
            ConfirmationCountsRow(
                key=row["organizer_id"],
                name=row["organizer__name"] or "",
                facilitator_count=row["facilitator_count"],
                scheduled_count=row["scheduled_count"],
                confirmed_count=row["confirmed_count"],
            )
            for row in rows
        ]

    @staticmethod
    def list_with_scheduled_session_in_track(
        event_pk: int, track_pk: int
    ) -> list[ConfirmationFacilitatorRow]:
        # Who the block makes this organizer responsible for: at least one
        # session of theirs is both in the block and placed in the timetable.
        rows = (
            Facilitator.objects.filter(
                event_id=event_pk,
                sessions__tracks=track_pk,
                sessions__agenda_item__isnull=False,
            )
            .values("pk", "display_name", "slug", "organizer_id", "organizer__name")
            .distinct()
            .order_by("display_name", "pk")
        )
        return [
            ConfirmationFacilitatorRow(
                pk=row["pk"],
                display_name=row["display_name"],
                slug=row["slug"],
                organizer_id=row["organizer_id"],
                organizer_name=row["organizer__name"] or "",
            )
            for row in rows
        ]

    @staticmethod
    def set_flag(pk: int, *, flagged: bool) -> None:
        Facilitator.objects.filter(pk=pk).update(flagged_for_deletion=flagged)

    @staticmethod
    def claim(pk: int, organizer_id: int) -> bool:
        # Conditional update, so two organizers clicking at the same moment
        # cannot both win: the loser's UPDATE matches no row.
        return bool(
            Facilitator.objects.filter(pk=pk, organizer__isnull=True).update(
                organizer_id=organizer_id
            )
        )

    @staticmethod
    def release(pk: int, *, organizer_id: int | None) -> bool:
        # `organizer_id=None` releases whoever holds it — the superuser escape
        # for an organizer who has left.
        qs = Facilitator.objects.filter(pk=pk, organizer__isnull=False)
        if organizer_id is not None:
            qs = qs.filter(organizer_id=organizer_id)
        return bool(qs.update(organizer=None))

    @staticmethod
    def delete(pk: int) -> None:
        Facilitator.objects.filter(pk=pk).delete()

    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool:
        return Facilitator.objects.filter(event_id=event_id, slug=slug).exists()
