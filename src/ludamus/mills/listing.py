"""Listings on the looking-for-group board."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from unidecode import unidecode

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    BoardCategoryFacetDTO,
    BoardSearchDTO,
    BoardTagFacetDTO,
    ListingContact,
    ListingContactMissingError,
    ListingDeclinedNotification,
    ListingDetailDTO,
    ListingInterestedNotification,
    ListingNotification,
    ListingResponsesDTO,
    ListingResponseStatus,
    ListingServiceProtocol,
    ListingStatus,
    ListingStatusError,
)
from ludamus.specs.listing import LISTING_OPEN_FOR

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.listing import (
        BoardFiltersDict,
        ListingBoardRowDTO,
        ListingCreateDict,
        ListingDTO,
        ListingNotifierProtocol,
        ListingRepositoryProtocol,
        ListingResponseDTO,
        ListingResponseRepositoryProtocol,
        ListingWriteDict,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.tags import TagDTO, TagRepositoryProtocol

logger = logging.getLogger(__name__)


def _search_key(text: str) -> str:
    return unidecode(text).casefold()


def _mentions_all(row: ListingBoardRowDTO, words: list[str]) -> bool:
    haystack = _search_key(f"{row.title} {row.what}")
    return all(word in haystack for word in words)


class _TagTree:
    def __init__(self, tags: list[TagDTO]) -> None:
        self.tags = {tag.pk: tag for tag in tags}
        by_slug = {(tag.category_slug, tag.slug): tag.pk for tag in tags}
        self.parent = {
            tag.pk: by_slug.get((tag.category_slug, tag.parent_slug))
            for tag in tags
            if tag.parent_slug is not None
        }
        self.in_category: dict[str, list[TagDTO]] = defaultdict(list)
        self.children: dict[tuple[str, int | None], list[TagDTO]] = defaultdict(list)
        for tag in sorted(tags, key=_by_name):
            self.in_category[tag.category_slug].append(tag)
            self.children[tag.category_slug, self.parent.get(tag.pk)].append(tag)

    def with_ancestors(self, pks: list[int]) -> set[int]:
        reach: set[int] = set()
        for pk in pks:
            current: int | None = pk
            while current is not None and current not in reach:
                reach.add(current)
                current = self.parent.get(current)
        return reach


class _BoardFacets:
    def __init__(
        self, *, rows: list[ListingBoardRowDTO], tags: list[TagDTO], tag_ids: list[int]
    ) -> None:
        self._rows = rows
        self._tree = _TagTree(tags)
        self._picked: dict[str, set[int]] = defaultdict(set)
        for pk in tag_ids:
            if pk in self._tree.tags:
                self._picked[self._tree.tags[pk].category_slug].add(pk)
        self._reach = {row.pk: self._tree.with_ancestors(row.tag_ids) for row in rows}

    def matching(self, *, ignoring: str | None = None) -> list[ListingBoardRowDTO]:
        return [
            row
            for row in self._rows
            if all(
                self._reach[row.pk] & pks
                for category, pks in self._picked.items()
                if category != ignoring
            )
        ]

    def category(self, *, slug: str, name: str) -> BoardCategoryFacetDTO | None:
        # A category counts against the rows the other categories' picks leave,
        # so its own picks never hide their alternatives.
        pool = self.matching(ignoring=slug)
        counts = Counter(pk for row in pool for pk in self._reach[row.pk])
        selected = self._picked.get(slug, set())

        def nodes(parent: int | None) -> list[BoardTagFacetDTO]:
            facets = []
            for tag in self._tree.children[slug, parent]:
                children = nodes(tag.pk)
                if counts[tag.pk] or tag.pk in selected or children:
                    facets.append(
                        BoardTagFacetDTO(
                            pk=tag.pk,
                            name=tag.name,
                            count=counts[tag.pk],
                            selected=tag.pk in selected,
                            expanded=any(
                                child.selected or child.expanded for child in children
                            ),
                            children=children,
                        )
                    )
            return facets

        roots = nodes(None)
        if not roots or not self._offers_choice(
            slug=slug, counts=counts, pool_size=len(pool)
        ):
            return None
        return BoardCategoryFacetDTO(slug=slug, name=name, tags=roots)

    def _offers_choice(
        self, *, slug: str, counts: Counter[int], pool_size: int
    ) -> bool:
        return bool(self._picked.get(slug)) or any(
            0 < counts[tag.pk] < pool_size for tag in self._tree.in_category[slug]
        )


class ListingService(ListingServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        listings: ListingRepositoryProtocol,
        responses: ListingResponseRepositoryProtocol,
        users: UserRepositoryProtocol,
        tags: TagRepositoryProtocol,
        notifier: ListingNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._listings = listings
        self._responses = responses
        self._users = users
        self._tags = tags
        self._notifier = notifier

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
            listing = self._listings.lock_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            self._listings.update(pk, data)
            self._listings.set_tags(pk=pk, tag_ids=tag_ids)
            if listing.status is not ListingStatus.DRAFT:
                self._check_contact(author_id, data["contact"])
            if not _changes(listing, data=data, tag_ids=tag_ids):
                return
            for user_id in self._responses.waiting_user_ids(pk):
                self._notifier.notify_listing_changed(
                    ListingNotification(
                        recipient_user_id=user_id,
                        listing_id=pk,
                        listing_title=data["title"],
                    )
                )

    def detail(
        self, *, pk: int, sphere_id: int, viewer_id: int | None
    ) -> ListingDetailDTO:
        listing = self._listings.read(pk=pk, sphere_id=sphere_id)
        is_author = listing.author_id == viewer_id
        if listing.status is ListingStatus.DRAFT and not is_author:
            raise NotFoundError
        own_response = (
            self._responses.read_own(listing_id=pk, user_id=viewer_id)
            if viewer_id is not None and not is_author
            else None
        )
        return ListingDetailDTO(
            listing=listing,
            is_author=is_author,
            own_response=own_response,
            can_respond=viewer_id is not None
            and _can_respond(listing, user_id=viewer_id, own_response=own_response),
            waiting_count=(
                self._responses.count_by_status(pk)[ListingResponseStatus.WAITING]
                if is_author
                else None
            ),
            open_for_days=LISTING_OPEN_FOR.days,
        )

    def read_authored(self, *, pk: int, sphere_id: int, author_id: int) -> ListingDTO:
        return self._listings.read_authored(
            pk=pk, sphere_id=sphere_id, author_id=author_id
        )

    def search_board(
        self, *, sphere_id: int, filters: BoardFiltersDict
    ) -> BoardSearchDTO:
        # shortcut: search and tags filter in memory over every listing the
        # board could show; move both into SQL once a board holds ~10k.
        statuses = [ListingStatus.OPEN]
        if filters["show_closed"]:
            statuses.append(ListingStatus.CLOSED)
        rows = self._listings.board_rows(
            sphere_id=sphere_id, seeking=filters["seeking"], statuses=statuses
        )
        words = _search_key(filters["search"]).split()
        board = _BoardFacets(
            rows=[row for row in rows if _mentions_all(row, words)],
            tags=self._tags.read_all(),
            tag_ids=filters["tag_ids"],
        )
        categories = sorted(self._tags.category_names().items(), key=_by_category_name)
        return BoardSearchDTO(
            listing_ids=[row.pk for row in board.matching()],
            facets=[
                facet
                for slug, name in categories
                if (facet := board.category(slug=slug, name=name)) is not None
            ],
        )

    def read_many(self, pks: list[int]) -> list[ListingDTO]:
        return self._listings.read_many(pks)

    def contact_channels(self, user_id: int) -> list[ListingContact]:
        user = self._users.read_by_id(user_id)
        return [
            contact
            for contact, reachable_at in (
                (ListingContact.DISCORD, user.discord_username),
                (ListingContact.EMAIL, user.email),
            )
            if reachable_at
        ]

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
            self._dismiss_waiting([pk])
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
            pks = self._listings.close_opened_before(now - LISTING_OPEN_FOR)
            self._dismiss_waiting(pks)
        return len(pks)

    @staticmethod
    def open_for_days() -> int:
        return LISTING_OPEN_FOR.days

    def respond(
        self,
        *,
        pk: int,
        sphere_id: int,
        user_id: int,
        message: str,
        contact: ListingContact,
    ) -> None:
        with self._transaction.atomic():
            # The lock orders this against a close, which dismisses everyone
            # still waiting, and against a second response from the same user.
            listing = self._listings.lock(pk=pk, sphere_id=sphere_id)
            if not _can_respond(
                listing,
                user_id=user_id,
                own_response=self._responses.read_own(listing_id=pk, user_id=user_id),
            ):
                raise ListingStatusError
            self._check_contact(user_id, contact)
            self._responses.create(
                {
                    "listing_id": pk,
                    "user_id": user_id,
                    "message": message,
                    "contact": contact,
                }
            )
            self._notifier.notify_listing_interested(
                ListingInterestedNotification(
                    recipient_user_id=listing.author_id,
                    listing_id=pk,
                    listing_title=listing.title,
                    responder_name=self._users.read_by_id(user_id).full_name,
                    message=message,
                )
            )
        logger.info("User %s responded to listing %s", user_id, pk)

    def withdraw(self, *, pk: int, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            self._listings.lock(pk=pk, sphere_id=sphere_id)
            response = self._responses.read_own(listing_id=pk, user_id=user_id)
            if response is None or response.status is not ListingResponseStatus.WAITING:
                raise ListingStatusError
            self._responses.delete(response.pk)
        logger.info("User %s withdrew from listing %s", user_id, pk)

    def decline(
        self, *, pk: int, sphere_id: int, author_id: int, response_id: int, message: str
    ) -> None:
        with self._transaction.atomic():
            listing = self._listings.lock_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            )
            response = self._responses.read(pk=response_id, listing_id=pk)
            if response.status is not ListingResponseStatus.WAITING:
                raise ListingStatusError
            self._responses.decline(pk=response_id, message=message)
            self._notifier.notify_listing_declined(
                ListingDeclinedNotification(
                    recipient_user_id=response.user_id,
                    listing_id=pk,
                    listing_title=listing.title,
                    message=message,
                )
            )
        logger.info("Response %s to listing %s declined", response_id, pk)

    def responses(
        self, *, pk: int, sphere_id: int, author_id: int, status: ListingResponseStatus
    ) -> ListingResponsesDTO:
        return ListingResponsesDTO(
            listing=self._listings.read_authored(
                pk=pk, sphere_id=sphere_id, author_id=author_id
            ),
            responses=self._responses.list_for_listing(listing_id=pk, status=status),
            counts=self._responses.count_by_status(pk),
        )

    def _dismiss_waiting(self, listing_ids: list[int]) -> None:
        for notice in self._responses.dismiss_waiting(listing_ids):
            self._notifier.notify_listing_not_chosen(notice)

    def _read_in(
        self, status: ListingStatus, *, pk: int, sphere_id: int, author_id: int
    ) -> ListingDTO:
        listing = self._listings.lock_authored(
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
        if contact not in self.contact_channels(author_id):
            raise ListingContactMissingError(contact)


def _can_respond(
    listing: ListingDTO, *, user_id: int, own_response: ListingResponseDTO | None
) -> bool:
    return (
        listing.status is ListingStatus.OPEN
        and listing.author_id != user_id
        and own_response is None
    )


def _changes(
    listing: ListingDTO, *, data: ListingWriteDict, tag_ids: list[int]
) -> bool:
    # The DTO carries the stored image URL, not an upload to compare against.
    edited = {field: value for field, value in data.items() if field != "header_image"}
    return listing.model_copy(update=edited) != listing or set(tag_ids) != {
        tag.pk for tag in listing.tags
    }


def _by_name(tag: TagDTO) -> str:
    return tag.name.casefold()


def _by_category_name(item: tuple[str, str]) -> str:
    return item[1].casefold()
