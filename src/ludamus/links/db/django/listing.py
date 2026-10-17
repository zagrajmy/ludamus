"""Board listings storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Prefetch, QuerySet

from ludamus.links.db.django.models import Listing, Tag, User
from ludamus.links.db.django.repositories.storage import (
    save_replacing_files,
    with_original_names,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    ListingContact,
    ListingDTO,
    ListingRepositoryProtocol,
    ListingRole,
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
        role=ListingRole(listing.role),
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
    def set_tags(*, pk: int, picked: list[int], with_ancestors: list[int]) -> None:
        listing = Listing.objects.get(pk=pk)
        listing.picked_tags.set(picked)
        listing.tags.set(with_ancestors)

    @staticmethod
    def read(*, pk: int, sphere_id: int) -> ListingDTO:
        return _get(_listings(), pk=pk, sphere_id=sphere_id)

    @staticmethod
    def read_authored(*, pk: int, sphere_id: int, author_id: int) -> ListingDTO:
        return _get(_listings(), pk=pk, sphere_id=sphere_id, author_id=author_id)

    @staticmethod
    def list_open(sphere_id: int) -> list[ListingDTO]:
        listings = _listings().filter(sphere_id=sphere_id, status=ListingStatus.OPEN)
        return [_dto(listing) for listing in listings.order_by("-opened_at", "-pk")]

    @staticmethod
    def list_authored(*, sphere_id: int, author_id: int) -> list[ListingDTO]:
        listings = _listings().filter(sphere_id=sphere_id, author_id=author_id)
        return [_dto(listing) for listing in listings.order_by("-creation_time")]

    @staticmethod
    def set_status(
        *, pk: int, status: ListingStatus, opened_at: datetime | None = None
    ) -> None:
        changes: dict[str, object] = {"status": status}
        if opened_at is not None:
            changes["opened_at"] = opened_at
        Listing.objects.filter(pk=pk).update(**changes)

    @staticmethod
    def close_opened_before(cutoff: datetime) -> int:
        return Listing.objects.filter(
            status=ListingStatus.OPEN, opened_at__lt=cutoff
        ).update(status=ListingStatus.CLOSED)

    @staticmethod
    def discord_of(user_id: int) -> str:
        return User.objects.values_list("discord_username", flat=True).get(pk=user_id)
