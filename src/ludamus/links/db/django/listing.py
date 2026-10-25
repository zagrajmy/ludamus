"""Board listings storage."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from django.db.models import Prefetch, QuerySet

from ludamus.links.db.django.models import Listing, Tag
from ludamus.links.db.django.repositories.storage import (
    save_replacing_files,
    with_original_names,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    ListingBoardRowDTO,
    ListingContact,
    ListingDTO,
    ListingRepositoryProtocol,
    ListingSeeking,
    ListingStatus,
    ListingTagDTO,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.listing import ListingCreateDict, ListingWriteDict


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
            listings.order_by("-opened_at", "-pk").values_list(
                "pk", "status", "title", "what"
            )
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
    def close_opened_before(cutoff: datetime) -> int:
        return Listing.objects.filter(
            status=ListingStatus.OPEN, opened_at__lt=cutoff
        ).update(status=ListingStatus.CLOSED)
