from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.listing import ListingService
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    ListingContact,
    ListingContactMissingError,
    ListingDTO,
    ListingRole,
    ListingSeeking,
    ListingStatus,
    ListingStatusError,
)
from tests.unit.factories import FakeTransaction, user_dto

SPHERE_PK = 1
AUTHOR_PK = 2
STRANGER_PK = 3
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

_WRITE = {
    "role": ListingRole.GM,
    "seeking": ListingSeeking.PLAYERS,
    "title": "Zew Cthulhu",
    "what": "one-shot",
    "description": "",
    "seats": 4,
    "medium": "",
    "place": "",
    "starts_at": None,
    "when_text": "",
    "contact": ListingContact.DISCORD,
}


class FakeListings:
    def __init__(self):
        self.rows: dict[int, ListingDTO] = {}
        self.tags: dict[int, list[int]] = {}

    def create(self, data):
        pk = len(self.rows) + 1
        self.rows[pk] = ListingDTO(
            pk=pk,
            author_name="",
            tags=[],
            status=ListingStatus.DRAFT,
            opened_at=None,
            header_image_url="",
            header_image_original_name="",
            **data,
        )
        return pk

    def add(self, **overrides):
        pk = self.create(
            _WRITE | {"sphere_id": SPHERE_PK, "author_id": AUTHOR_PK} | overrides
        )
        return self.rows[pk]

    def update(self, pk, data):
        self.rows[pk] = self.rows[pk].model_copy(update=data)

    def set_tags(self, *, pk, tag_ids):
        self.tags[pk] = tag_ids

    def read(self, *, pk, sphere_id):
        assert sphere_id == SPHERE_PK
        return self.rows[pk]

    def lock_authored(self, *, pk, sphere_id, author_id):
        listing = self.read(pk=pk, sphere_id=sphere_id)
        if listing.author_id != author_id:
            raise NotFoundError
        return listing

    def open(self, *, pk, at):
        self.update(pk, {"status": ListingStatus.OPEN, "opened_at": at})

    def close(self, pk):
        self.update(pk, {"status": ListingStatus.CLOSED})

    def close_opened_before(self, cutoff):
        stale = [
            pk
            for pk, listing in self.rows.items()
            if listing.status is ListingStatus.OPEN
            and listing.opened_at is not None
            and listing.opened_at < cutoff
        ]
        for pk in stale:
            self.close(pk)
        return len(stale)


class FakeUsers:
    def __init__(self, **profile):
        self.user = user_dto(pk=AUTHOR_PK, **profile)

    def read_by_id(self, pk):
        assert pk == AUTHOR_PK
        return self.user


def _service(listings, **profile):
    return ListingService(FakeTransaction(), listings, FakeUsers(**profile))


def _ids(listing):
    return {"pk": listing.pk, "sphere_id": SPHERE_PK, "author_id": AUTHOR_PK}


DISCORD_ONLY = {"discord_username": "gm#1", "email": ""}
NO_CONTACT = {"discord_username": "", "email": ""}


class TestCreate:
    def test_without_publish_at_saves_a_draft_with_its_tags(self):
        listings = FakeListings()

        pk = _service(listings, **NO_CONTACT).create(
            _WRITE | {"sphere_id": SPHERE_PK, "author_id": AUTHOR_PK},
            tag_ids=[5, 6],
            publish_at=None,
        )

        assert (listings.rows[pk].status, listings.tags[pk]) == (
            ListingStatus.DRAFT,
            [5, 6],
        )

    def test_with_publish_at_opens_it_at_that_time(self):
        listings = FakeListings()

        pk = _service(listings, **DISCORD_ONLY).create(
            _WRITE | {"sphere_id": SPHERE_PK, "author_id": AUTHOR_PK},
            tag_ids=[],
            publish_at=NOW,
        )

        assert (listings.rows[pk].status, listings.rows[pk].opened_at) == (
            ListingStatus.OPEN,
            NOW,
        )

    def test_publishing_with_a_contact_missing_from_profile_fails(self):
        listings = FakeListings()

        with pytest.raises(ListingContactMissingError) as exc_info:
            _service(listings, **DISCORD_ONLY).create(
                _WRITE | {
                    "sphere_id": SPHERE_PK,
                    "author_id": AUTHOR_PK,
                    "contact": ListingContact.EMAIL,
                },
                tag_ids=[],
                publish_at=NOW,
            )

        assert exc_info.value.contact is ListingContact.EMAIL


class TestUpdate:
    def test_draft_may_name_a_missing_contact(self):
        listings = FakeListings()
        listing = listings.add()

        _service(listings, **NO_CONTACT).update(
            **_ids(listing), data=_WRITE | {"title": "Renamed"}, tag_ids=[7]
        )

        assert (listings.rows[listing.pk].title, listings.tags[listing.pk]) == (
            "Renamed",
            [7],
        )

    def test_open_listing_may_not_name_a_missing_contact(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        with pytest.raises(ListingContactMissingError):
            _service(listings, **NO_CONTACT).update(
                **_ids(listing), data=_WRITE, tag_ids=[]
            )


class TestReadVisible:
    def test_draft_is_hidden_from_others(self):
        listings = FakeListings()
        listing = listings.add()

        with pytest.raises(NotFoundError):
            _service(listings).read_visible(
                pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=STRANGER_PK
            )

    def test_draft_is_shown_to_its_author(self):
        listings = FakeListings()
        listing = listings.add()

        assert (
            _service(listings).read_visible(
                pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=AUTHOR_PK
            )
            == listing
        )

    def test_open_listing_is_shown_to_anonymous_viewers(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        assert (
            _service(listings)
            .read_visible(pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=None)
            .status
            is ListingStatus.OPEN
        )


def test_contact_channels_lists_what_the_profile_has():
    service = _service(FakeListings(), discord_username="gm#1", email="gm@example.com")

    assert service.contact_channels(AUTHOR_PK) == [
        ListingContact.DISCORD,
        ListingContact.EMAIL,
    ]


class TestTransitions:
    def test_publish_opens_a_draft(self):
        listings = FakeListings()
        listing = listings.add()

        _service(listings, **DISCORD_ONLY).publish(**_ids(listing), now=NOW)

        assert listings.rows[listing.pk].opened_at == NOW

    def test_publish_refuses_an_open_listing(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        with pytest.raises(ListingStatusError):
            _service(listings, **DISCORD_ONLY).publish(
                **_ids(listing), now=NOW + timedelta(days=1)
            )

        assert listings.rows[listing.pk].opened_at == NOW

    def test_close_closes_an_open_listing(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        _service(listings).close(**_ids(listing))

        assert listings.rows[listing.pk].status is ListingStatus.CLOSED

    def test_close_refuses_a_draft(self):
        listings = FakeListings()
        listing = listings.add()

        with pytest.raises(ListingStatusError):
            _service(listings).close(**_ids(listing))

    def test_reopen_restarts_the_open_period(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW - timedelta(days=40))
        listings.close(listing.pk)

        _service(listings, **DISCORD_ONLY).reopen(**_ids(listing), now=NOW)

        assert (
            listings.rows[listing.pk].status,
            listings.rows[listing.pk].opened_at,
        ) == (ListingStatus.OPEN, NOW)

    def test_another_authors_listing_is_not_found(self):
        listings = FakeListings()
        listing = listings.add(author_id=STRANGER_PK)

        with pytest.raises(NotFoundError):
            _service(listings).close(**_ids(listing))


def test_close_stale_closes_only_listings_open_longer_than_the_open_period():
    listings = FakeListings()
    stale = listings.add()
    listings.open(pk=stale.pk, at=NOW - timedelta(days=31))
    fresh = listings.add()
    listings.open(pk=fresh.pk, at=NOW - timedelta(days=29))

    closed = _service(listings).close_stale(NOW)

    assert (closed, listings.rows[stale.pk].status, listings.rows[fresh.pk].status) == (
        1,
        ListingStatus.CLOSED,
        ListingStatus.OPEN,
    )
