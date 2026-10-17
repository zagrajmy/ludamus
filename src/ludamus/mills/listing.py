"""Listings on the looking-for-group board."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    ListingContact,
    ListingContactMissingError,
    ListingServiceProtocol,
    ListingStatus,
)
from ludamus.specs.listing import LISTING_OPEN_FOR

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.listing import (
        ListingCreateDict,
        ListingDTO,
        ListingRepositoryProtocol,
        ListingWriteDict,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.tags import TagRepositoryProtocol

logger = logging.getLogger(__name__)


class ListingService(ListingServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        listings: ListingRepositoryProtocol,
        tags: TagRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._listings = listings
        self._tags = tags

    def create(
        self,
        data: ListingCreateDict,
        *,
        tag_ids: list[int],
        publish_at: datetime | None,
    ) -> int:
        with self._transaction.atomic():
            pk = self._listings.create(data)
            self._set_tags(pk, tag_ids)
            if publish_at is not None:
                self._open(
                    pk,
                    author_id=data["author_id"],
                    contact=data["contact"],
                    now=publish_at,
                )
        logger.info(
            "Listing %s created by user %s (%s)",
            pk,
            data["author_id"],
            "open" if publish_at else "draft",
        )
        return pk

    def update(
        self,
        *,
        pk: int,
        sphere_id: int,
        author_id: int,
        data: ListingWriteDict,
        tag_ids: list[int],
    ) -> None:
        with self._transaction.atomic():
            listing = self._listings.read_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            self._listings.update(pk, data)
            self._set_tags(pk, tag_ids)
            if listing.status is not ListingStatus.DRAFT:
                self._check_contact(author_id, data["contact"])

    def read_visible(
        self, *, pk: int, sphere_id: int, viewer_id: int | None
    ) -> ListingDTO:
        listing = self._listings.read(pk=pk, sphere_id=sphere_id)
        if listing.status is ListingStatus.DRAFT and listing.author_id != viewer_id:
            raise NotFoundError
        return listing

    def read_authored(self, *, pk: int, sphere_id: int, author_id: int) -> ListingDTO:
        return self._listings.read_authored(
            pk=pk, sphere_id=sphere_id, author_id=author_id
        )

    def board(self, sphere_id: int) -> list[ListingDTO]:
        return self._listings.list_open(sphere_id)

    def has_discord(self, user_id: int) -> bool:
        return bool(self._listings.discord_of(user_id))

    def authored(self, *, sphere_id: int, author_id: int) -> list[ListingDTO]:
        return self._listings.list_authored(sphere_id=sphere_id, author_id=author_id)

    def publish(
        self, *, pk: int, sphere_id: int, author_id: int, now: datetime
    ) -> None:
        with self._transaction.atomic():
            listing = self._listings.read_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            if listing.status is ListingStatus.DRAFT:
                self._open(pk, author_id=author_id, contact=listing.contact, now=now)
                logger.info("Listing %s published", pk)

    def close(self, *, pk: int, sphere_id: int, author_id: int) -> None:
        with self._transaction.atomic():
            listing = self._listings.read_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            if listing.status is ListingStatus.OPEN:
                self._listings.set_status(pk=pk, status=ListingStatus.CLOSED)
                logger.info("Listing %s closed by its author", pk)

    def reopen(self, *, pk: int, sphere_id: int, author_id: int, now: datetime) -> None:
        with self._transaction.atomic():
            listing = self._listings.read_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            if listing.status is ListingStatus.CLOSED:
                self._open(pk, author_id=author_id, contact=listing.contact, now=now)
                logger.info("Listing %s reopened", pk)

    def close_stale(self, now: datetime) -> int:
        with self._transaction.atomic():
            return self._listings.close_opened_before(now - LISTING_OPEN_FOR)

    def _open(
        self, pk: int, *, author_id: int, contact: ListingContact, now: datetime
    ) -> None:
        self._check_contact(author_id, contact)
        self._listings.set_status(pk=pk, status=ListingStatus.OPEN, opened_at=now)

    def _check_contact(self, author_id: int, contact: ListingContact) -> None:
        # The account email always exists; Discord only once the profile has it.
        if contact is ListingContact.DISCORD and not self.has_discord(author_id):
            raise ListingContactMissingError

    def _set_tags(self, pk: int, tag_ids: list[int]) -> None:
        tags = {tag.pk: tag for tag in self._tags.read_all()}
        by_key = {(tag.category_slug, tag.slug): tag for tag in tags.values()}
        picked = sorted(set(tag_ids) & tags.keys())
        with_ancestors: dict[int, None] = {}
        for tag_id in picked:
            tag = tags.get(tag_id)
            while tag is not None and tag.pk not in with_ancestors:
                with_ancestors[tag.pk] = None
                parent = tag.parent_slug
                tag = (
                    None if parent is None else by_key.get((tag.category_slug, parent))
                )
        self._listings.set_tags(
            pk=pk, picked=picked, with_ancestors=list(with_ancestors)
        )
