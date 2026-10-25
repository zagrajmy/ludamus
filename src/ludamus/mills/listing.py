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
        ListingRepositoryProtocol,
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
        self.children: dict[int | None, list[TagDTO]] = defaultdict(list)
        for tag in sorted(tags, key=_by_name):
            self.children[self.parent.get(tag.pk)].append(tag)

    def with_ancestors(self, pks: list[int]) -> set[int]:
        reach: set[int] = set()
        for pk in pks:
            current: int | None = pk
            while current is not None and current not in reach:
                reach.add(current)
                current = self.parent.get(current)
        return reach

    def facets(
        self,
        *,
        category_slug: str,
        counts: Counter[int],
        selected: set[int],
        parent: int | None = None,
    ) -> list[BoardTagFacetDTO]:
        nodes = []
        for tag in self.children[parent]:
            if tag.category_slug != category_slug:
                continue
            children = self.facets(
                category_slug=category_slug,
                counts=counts,
                selected=selected,
                parent=tag.pk,
            )
            if counts[tag.pk] or tag.pk in selected or children:
                nodes.append(
                    BoardTagFacetDTO(
                        pk=tag.pk,
                        name=tag.name,
                        count=counts[tag.pk],
                        selected=tag.pk in selected,
                        children=children,
                    )
                )
        return nodes


class ListingService(ListingServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        listings: ListingRepositoryProtocol,
        users: UserRepositoryProtocol,
        tags: TagRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._listings = listings
        self._users = users
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
        rows = [row for row in rows if _mentions_all(row, words)]
        # Open first; the repository already orders each status newest first.
        rows.sort(key=lambda row: row.status is not ListingStatus.OPEN)

        tree = _TagTree(self._tags.read_all())
        picked: dict[str, set[int]] = defaultdict(set)
        for pk in filters["tag_ids"]:
            if pk in tree.tags:
                picked[tree.tags[pk].category_slug].add(pk)
        reach = {row.pk: tree.with_ancestors(row.tag_ids) for row in rows}

        def matching(*, ignoring: str | None = None) -> list[ListingBoardRowDTO]:
            return [
                row
                for row in rows
                if all(
                    reach[row.pk] & pks
                    for category, pks in picked.items()
                    if category != ignoring
                )
            ]

        facets = []
        for slug, name in sorted(
            self._tags.category_names().items(), key=_by_category_name
        ):
            pool = matching(ignoring=slug)
            counts = Counter(pk for row in pool for pk in reach[row.pk])
            selected = picked.get(slug, set())
            roots = tree.facets(category_slug=slug, counts=counts, selected=selected)
            splits = any(
                0 < counts[pk] < len(pool)
                for pk, tag in tree.tags.items()
                if tag.category_slug == slug
            )
            if roots and (splits or selected):
                facets.append(BoardCategoryFacetDTO(slug=slug, name=name, tags=roots))
        return BoardSearchDTO(listing_ids=[row.pk for row in matching()], facets=facets)

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

    @staticmethod
    def open_for_days() -> int:
        return LISTING_OPEN_FOR.days

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


def _by_name(tag: TagDTO) -> str:
    return tag.name.casefold()


def _by_category_name(item: tuple[str, str]) -> str:
    return item[1].casefold()
