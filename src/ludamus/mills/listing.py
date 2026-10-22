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
    ListingStatusError,
)
from ludamus.specs.listing import LISTING_OPEN_FOR

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.listing import (
        ListingCreateDict,
        ListingDTO,
        ListingRepositoryProtocol,
        ListingWriteDict,
    )
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


class ListingService(ListingServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        listings: ListingRepositoryProtocol,
        users: UserRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._listings = listings
        self._users = users

    def create(
        self,
        data: ListingCreateDict,
        *,
        tag_ids: list[int],
        publish_at: datetime | None,
    ) -> int:
        with self._transaction.atomic():
            pk = self._listings.create(data)
            self._listings.set_tags(pk=pk, tag_ids=tag_ids)
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
            self._listings.set_tags(pk=pk, tag_ids=tag_ids)
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
        return bool(self._users.read_by_id(user_id).discord_username)

    def authored(self, *, sphere_id: int, author_id: int) -> list[ListingDTO]:
        return self._listings.list_authored(sphere_id=sphere_id, author_id=author_id)

    def publish(
        self, *, pk: int, sphere_id: int, author_id: int, now: datetime
    ) -> None:
        with self._transaction.atomic():
            listing = self._read_in(
                ListingStatus.DRAFT, pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            self._open(pk, author_id=author_id, contact=listing.contact, now=now)
        logger.info("Listing %s published", pk)

    def close(self, *, pk: int, sphere_id: int, author_id: int) -> None:
        with self._transaction.atomic():
            self._read_in(
                ListingStatus.OPEN, pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            self._listings.close(pk)
        logger.info("Listing %s closed by its author", pk)

    def reopen(self, *, pk: int, sphere_id: int, author_id: int, now: datetime) -> None:
        with self._transaction.atomic():
            listing = self._read_in(
                ListingStatus.CLOSED, pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            self._open(pk, author_id=author_id, contact=listing.contact, now=now)
        logger.info("Listing %s reopened", pk)

    def close_stale(self, now: datetime) -> int:
        with self._transaction.atomic():
            return self._listings.close_opened_before(now - LISTING_OPEN_FOR)

    def _read_in(
        self, status: ListingStatus, *, pk: int, sphere_id: int, author_id: int
    ) -> ListingDTO:
        listing = self._listings.read_authored(
            pk=pk, sphere_id=sphere_id, author_id=author_id
        )
        if listing.status is not status:
            raise ListingStatusError
        return listing

    def _open(
        self, pk: int, *, author_id: int, contact: ListingContact, now: datetime
    ) -> None:
        self._check_contact(author_id, contact)
        self._listings.open(pk=pk, at=now)

    def _check_contact(self, author_id: int, contact: ListingContact) -> None:
        author = self._users.read_by_id(author_id)
        reachable_at = (
            author.discord_username
            if contact is ListingContact.DISCORD
            else author.email
        )
        if not reachable_at:
            raise ListingContactMissingError
