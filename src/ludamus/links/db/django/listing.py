"""Board listings storage."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from django.db.models import Case, Count, Prefetch, QuerySet, Value, When

from ludamus.links.db.django.models import Listing, ListingResponse, Tag
from ludamus.links.db.django.repositories.storage import (
    save_replacing_files,
    with_original_names,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    ListingBoardRowDTO,
    ListingContact,
    ListingDTO,
    ListingNotification,
    ListingRepositoryProtocol,
    ListingResponseDTO,
    ListingResponseRepositoryProtocol,
    ListingResponseStatus,
    ListingSeeking,
    ListingStatus,
    ListingTagDTO,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.listing import (
        ListingCreateDict,
        ListingResponseCreateDict,
        ListingWriteDict,
    )


def _listings() -> QuerySet[Listing]:
    return Listing.objects.select_related("author").prefetch_related(
        Prefetch("picked_tags", queryset=Tag.objects.order_by("name"))
    )


def _dto(listing: Listing) -> ListingDTO:
    return ListingDTO(
        pk=listing.pk,
        sphere_id=listing.sphere_id,
        author_id=listing.author_id,
        author_name=listing.author.full_name,
        seeking=ListingSeeking(listing.seeking),
        title=listing.title,
        what=listing.what,
        description=listing.description,
        tags=[ListingTagDTO(pk=t.pk, name=t.name) for t in listing.picked_tags.all()],
        seats=listing.seats,
        medium=listing.medium,
        place=listing.place,
        starts_at=listing.starts_at,
        when_text=listing.when_text,
        contact=ListingContact(listing.contact),
        status=ListingStatus(listing.status),
        opened_at=listing.opened_at,
        header_image_url=listing.header_image_url,
        header_image_original_name=listing.header_image_original_name,
    )


def _get(listings: QuerySet[Listing], **lookup: int) -> ListingDTO:
    try:
        return _dto(listings.get(**lookup))
    except Listing.DoesNotExist as exception:
        raise NotFoundError from exception


class ListingRepository(ListingRepositoryProtocol):
    @staticmethod
    def create(data: ListingCreateDict) -> int:
        return Listing.objects.create(**with_original_names(Listing, data)).pk

    @staticmethod
    def update(pk: int, data: ListingWriteDict) -> None:
        save_replacing_files(Listing.objects.get(pk=pk), data)

    @staticmethod
    def set_tags(*, pk: int, tag_ids: list[int]) -> None:
        Listing.objects.get(pk=pk).picked_tags.set(Tag.objects.filter(pk__in=tag_ids))

    @staticmethod
    def read(*, pk: int, sphere_id: int) -> ListingDTO:
        return _get(_listings(), pk=pk, sphere_id=sphere_id)

    @staticmethod
    def read_authored(*, pk: int, sphere_id: int, author_id: int) -> ListingDTO:
        return _get(_listings(), pk=pk, sphere_id=sphere_id, author_id=author_id)

    @staticmethod
    def lock(*, pk: int, sphere_id: int) -> ListingDTO:
        return _get(
            _listings().select_for_update(of=("self",)), pk=pk, sphere_id=sphere_id
        )

    @staticmethod
    def lock_authored(*, pk: int, sphere_id: int, author_id: int) -> ListingDTO:
        return _get(
            _listings().select_for_update(of=("self",)),
            pk=pk,
            sphere_id=sphere_id,
            author_id=author_id,
        )

    @staticmethod
    def board_rows(
        *, sphere_id: int, seeking: ListingSeeking | None, statuses: list[ListingStatus]
    ) -> list[ListingBoardRowDTO]:
        listings = Listing.objects.filter(sphere_id=sphere_id, status__in=statuses)
        if seeking is not None:
            listings = listings.filter(seeking=seeking)
        rows = list(
            listings.order_by(
                Case(When(status=ListingStatus.OPEN, then=Value(0)), default=Value(1)),
                "-opened_at",
                "-pk",
            ).values_list("pk", "status", "title", "what")
        )
        tag_ids: dict[int, list[int]] = defaultdict(list)
        for listing_id, tag_id in Listing.picked_tags.through.objects.filter(
            listing_id__in=[pk for pk, *_ in rows]
        ).values_list("listing_id", "tag_id"):
            tag_ids[listing_id].append(tag_id)
        return [
            ListingBoardRowDTO(
                pk=pk,
                status=ListingStatus(status),
                title=title,
                what=what,
                tag_ids=tag_ids[pk],
            )
            for pk, status, title, what in rows
        ]

    @staticmethod
    def read_many(pks: list[int]) -> list[ListingDTO]:
        listings = _listings().in_bulk(pks)
        return [_dto(listings[pk]) for pk in pks if pk in listings]

    @staticmethod
    def list_authored(*, sphere_id: int, author_id: int) -> list[ListingDTO]:
        listings = _listings().filter(sphere_id=sphere_id, author_id=author_id)
        return [_dto(listing) for listing in listings.order_by("-creation_time")]

    @staticmethod
    def open(*, pk: int, at: datetime) -> None:
        Listing.objects.filter(pk=pk).update(status=ListingStatus.OPEN, opened_at=at)

    @staticmethod
    def close(pk: int) -> None:
        Listing.objects.filter(pk=pk).update(status=ListingStatus.CLOSED)

    @staticmethod
    def close_opened_before(cutoff: datetime) -> list[int]:
        stale = Listing.objects.select_for_update().filter(
            status=ListingStatus.OPEN, opened_at__lt=cutoff
        )
        pks = list(stale.values_list("pk", flat=True))
        Listing.objects.filter(pk__in=pks).update(status=ListingStatus.CLOSED)
        return pks


def _response_dto(response: ListingResponse) -> ListingResponseDTO:
    return ListingResponseDTO(
        pk=response.pk,
        listing_id=response.listing_id,
        user_id=response.user_id,
        user_name=response.user.full_name,
        message=response.message,
        status=ListingResponseStatus(response.status),
        decline_message=response.decline_message,
        creation_time=response.creation_time,
    )


def _responses() -> QuerySet[ListingResponse]:
    return ListingResponse.objects.select_related("user")


class ListingResponseRepository(ListingResponseRepositoryProtocol):
    @staticmethod
    def create(data: ListingResponseCreateDict) -> int:
        return ListingResponse.objects.create(**data).pk

    @staticmethod
    def read(*, pk: int, listing_id: int) -> ListingResponseDTO:
        try:
            return _response_dto(_responses().get(pk=pk, listing_id=listing_id))
        except ListingResponse.DoesNotExist as exception:
            raise NotFoundError from exception

    @staticmethod
    def read_own(*, listing_id: int, user_id: int) -> ListingResponseDTO | None:
        response = _responses().filter(listing_id=listing_id, user_id=user_id).first()
        return _response_dto(response) if response else None

    @staticmethod
    def list_for_listing(
        *, listing_id: int, status: ListingResponseStatus
    ) -> list[ListingResponseDTO]:
        responses = _responses().filter(listing_id=listing_id, status=status)
        return [_response_dto(response) for response in responses.order_by("pk")]

    @staticmethod
    def count_by_status(listing_id: int) -> dict[ListingResponseStatus, int]:
        counts = dict(
            ListingResponse.objects.filter(listing_id=listing_id)
            .values("status")
            .annotate(count=Count("pk"))
            .values_list("status", "count")
        )
        return {status: counts.get(status, 0) for status in ListingResponseStatus}

    @staticmethod
    def waiting_user_ids(listing_id: int) -> list[int]:
        return list(
            ListingResponse.objects.filter(
                listing_id=listing_id, status=ListingResponseStatus.WAITING
            )
            .order_by("pk")
            .values_list("user_id", flat=True)
        )

    @staticmethod
    def decline(*, pk: int, message: str) -> None:
        ListingResponse.objects.filter(pk=pk).update(
            status=ListingResponseStatus.DECLINED, decline_message=message
        )

    @staticmethod
    def dismiss_waiting(listing_ids: list[int]) -> list[ListingNotification]:
        waiting = list(
            ListingResponse.objects.filter(
                listing_id__in=listing_ids, status=ListingResponseStatus.WAITING
            )
            .order_by("listing_id", "pk")
            .values_list("pk", "user_id", "listing_id", "listing__title")
        )
        ListingResponse.objects.filter(pk__in=[row[0] for row in waiting]).update(
            status=ListingResponseStatus.NOT_CHOSEN
        )
        return [
            ListingNotification(
                recipient_user_id=user_id, listing_id=listing_id, listing_title=title
            )
            for _, user_id, listing_id, title in waiting
        ]

    @staticmethod
    def delete(pk: int) -> None:
        ListingResponse.objects.filter(pk=pk).delete()
