from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
)
from ludamus.pacts.tags import TagDTO
from tests.unit.factories import FakeTransaction

AUTHOR_ID = 7
SPHERE_ID = 1
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def _listing(pk=1, **overrides):
    defaults = {
        "pk": pk,
        "sphere_id": SPHERE_ID,
        "author_id": AUTHOR_ID,
        "author_name": "Author",
        "role": ListingRole.GM,
        "seeking": ListingSeeking.PLAYERS,
        "title": "Mörk Borg one-shot",
        "what": "Mörk Borg",
        "description": "",
        "tags": [],
        "seats": 4,
        "medium": "",
        "place": "",
        "starts_at": None,
        "when_text": "",
        "contact": ListingContact.EMAIL,
        "status": ListingStatus.DRAFT,
        "opened_at": None,
        "header_image_url": "",
        "header_image_original_name": "",
    }
    return ListingDTO(**defaults | overrides)


class FakeListings:
    def __init__(self, *listings, discord=""):
        self.listings = {listing.pk: listing for listing in listings}
        self.discord = discord
        self.tags = None

    def create(self, data):
        pk = len(self.listings) + 1
        self.listings[pk] = _listing(
            pk, author_id=data["author_id"], contact=data["contact"]
        )
        return pk

    def update(self, pk, data):
        self.listings[pk] = self.listings[pk].model_copy(update=data)

    def set_tags(self, *, pk, picked, with_ancestors):
        self.tags = (pk, picked, with_ancestors)

    def read(self, *, pk, sphere_id):
        assert sphere_id == SPHERE_ID
        return self.listings[pk]

    def read_authored(self, *, pk, sphere_id, author_id):
        assert (sphere_id, author_id) == (SPHERE_ID, AUTHOR_ID)
        return self.listings[pk]

    def list_open(self, sphere_id):
        assert sphere_id == SPHERE_ID
        return [
            listing
            for listing in self.listings.values()
            if listing.status is ListingStatus.OPEN
        ]

    def list_authored(self, *, sphere_id, author_id):
        assert sphere_id == SPHERE_ID
        return [
            listing
            for listing in self.listings.values()
            if listing.author_id == author_id
        ]

    def set_status(self, *, pk, status, opened_at=None):
        update = {
            "status": status,
            "opened_at": opened_at or self.listings[pk].opened_at,
        }
        self.listings[pk] = self.listings[pk].model_copy(update=update)

    def close_opened_before(self, cutoff):
        stale = [
            pk
            for pk, listing in self.listings.items()
            if listing.status is ListingStatus.OPEN and listing.opened_at < cutoff
        ]
        for pk in stale:
            self.set_status(pk=pk, status=ListingStatus.CLOSED)
        return len(stale)

    def discord_of(self, user_id):
        assert user_id == AUTHOR_ID
        return self.discord


def _tag(pk, slug, parent=None, *, category="activity"):
    return TagDTO(
        pk=pk, category_slug=category, slug=slug, name=slug, parent_slug=parent
    )


TAGS = [
    _tag(1, "ttrpg"),
    _tag(2, "osr", "ttrpg"),
    _tag(3, "mork-borg", "osr"),
    _tag(4, "horror", category="genre"),
]


def _service(listings):
    tags = SimpleNamespace(read_all=lambda: TAGS)
    return ListingService(FakeTransaction(), listings, tags)


def _create_data(contact=ListingContact.EMAIL):
    return {"sphere_id": SPHERE_ID, "author_id": AUTHOR_ID, "contact": contact}


def _status(listings, pk=1):
    listing = listings.listings[pk]
    return listing.status, listing.opened_at


class TestCreate:
    def test_without_publish_date_stays_draft(self):
        listings = FakeListings()

        pk = _service(listings).create(_create_data(), tag_ids=[], publish_at=None)

        assert pk == 1
        assert _status(listings) == (ListingStatus.DRAFT, None)

    def test_with_publish_date_opens_at_that_date(self):
        listings = FakeListings()

        _service(listings).create(_create_data(), tag_ids=[], publish_at=NOW)

        assert _status(listings) == (ListingStatus.OPEN, NOW)

    def test_open_with_discord_contact_needs_discord_on_profile(self):
        listings = FakeListings()

        with pytest.raises(ListingContactMissingError):
            _service(listings).create(
                _create_data(ListingContact.DISCORD), tag_ids=[], publish_at=NOW
            )

    def test_tags_are_stored_with_their_ancestors(self):
        listings = FakeListings()

        _service(listings).create(
            _create_data(), tag_ids=[3, 2, 4, 99], publish_at=None
        )

        assert listings.tags == (1, [2, 3, 4], [2, 1, 3, 4])


class TestUpdate:
    def test_draft_may_name_a_missing_contact(self):
        listings = FakeListings(_listing())

        _service(listings).update(
            pk=1,
            sphere_id=SPHERE_ID,
            author_id=AUTHOR_ID,
            data={"contact": ListingContact.DISCORD},
            tag_ids=[1],
        )

        assert listings.listings[1].contact is ListingContact.DISCORD
        assert listings.tags == (1, [1], [1])

    def test_open_listing_rejects_a_missing_contact(self):
        listings = FakeListings(_listing(status=ListingStatus.OPEN))

        with pytest.raises(ListingContactMissingError):
            _service(listings).update(
                pk=1,
                sphere_id=SPHERE_ID,
                author_id=AUTHOR_ID,
                data={"contact": ListingContact.DISCORD},
                tag_ids=[],
            )

    def test_open_listing_accepts_discord_on_profile(self):
        listings = FakeListings(_listing(status=ListingStatus.OPEN), discord="gm#1")

        _service(listings).update(
            pk=1,
            sphere_id=SPHERE_ID,
            author_id=AUTHOR_ID,
            data={"contact": ListingContact.DISCORD},
            tag_ids=[],
        )

        assert listings.listings[1].contact is ListingContact.DISCORD


class TestReadVisible:
    def test_draft_is_hidden_from_others(self):
        service = _service(FakeListings(_listing()))

        with pytest.raises(NotFoundError):
            service.read_visible(pk=1, sphere_id=SPHERE_ID, viewer_id=None)

    def test_draft_is_shown_to_its_author(self):
        listing = _listing()

        assert (
            _service(FakeListings(listing)).read_visible(
                pk=1, sphere_id=SPHERE_ID, viewer_id=AUTHOR_ID
            )
            == listing
        )

    def test_open_is_shown_to_anyone(self):
        listing = _listing(status=ListingStatus.OPEN)

        assert (
            _service(FakeListings(listing)).read_visible(
                pk=1, sphere_id=SPHERE_ID, viewer_id=None
            )
            == listing
        )


class TestReads:
    def test_board_lists_open_only(self):
        open_listing = _listing(2, status=ListingStatus.OPEN)
        service = _service(FakeListings(_listing(), open_listing))

        assert service.board(SPHERE_ID) == [open_listing]

    def test_authored_lists_every_status(self):
        draft = _listing()
        closed = _listing(2, status=ListingStatus.CLOSED)
        service = _service(FakeListings(draft, closed, _listing(3, author_id=8)))

        assert service.authored(sphere_id=SPHERE_ID, author_id=AUTHOR_ID) == [
            draft,
            closed,
        ]

    def test_read_authored(self):
        listing = _listing()

        assert (
            _service(FakeListings(listing)).read_authored(
                pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID
            )
            == listing
        )

    @pytest.mark.parametrize(("discord", "expected"), (("", False), ("gm#1", True)))
    def test_has_discord(self, discord, expected):
        assert (
            _service(FakeListings(discord=discord)).has_discord(AUTHOR_ID) is expected
        )


class TestTransitions:
    def test_publish_opens_a_draft(self):
        listings = FakeListings(_listing())

        _service(listings).publish(
            pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID, now=NOW
        )

        assert _status(listings) == (ListingStatus.OPEN, NOW)

    def test_publish_leaves_a_closed_listing(self):
        listings = FakeListings(_listing(status=ListingStatus.CLOSED))

        _service(listings).publish(
            pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID, now=NOW
        )

        assert _status(listings) == (ListingStatus.CLOSED, None)

    def test_close_closes_an_open_listing(self):
        listings = FakeListings(_listing(status=ListingStatus.OPEN, opened_at=NOW))

        _service(listings).close(pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID)

        assert _status(listings) == (ListingStatus.CLOSED, NOW)

    def test_close_leaves_a_draft(self):
        listings = FakeListings(_listing())

        _service(listings).close(pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID)

        assert _status(listings) == (ListingStatus.DRAFT, None)

    def test_reopen_restarts_the_clock(self):
        earlier = NOW - timedelta(days=40)
        listings = FakeListings(
            _listing(status=ListingStatus.CLOSED, opened_at=earlier)
        )

        _service(listings).reopen(
            pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID, now=NOW
        )

        assert _status(listings) == (ListingStatus.OPEN, NOW)

    def test_reopen_with_discord_contact_needs_discord_on_profile(self):
        listings = FakeListings(
            _listing(status=ListingStatus.CLOSED, contact=ListingContact.DISCORD)
        )

        with pytest.raises(ListingContactMissingError):
            _service(listings).reopen(
                pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID, now=NOW
            )

    def test_reopen_leaves_a_draft(self):
        listings = FakeListings(_listing())

        _service(listings).reopen(
            pk=1, sphere_id=SPHERE_ID, author_id=AUTHOR_ID, now=NOW
        )

        assert _status(listings) == (ListingStatus.DRAFT, None)


def test_close_stale_closes_listings_open_for_thirty_days():
    stale_at = NOW - timedelta(days=31)
    fresh_at = NOW - timedelta(days=29)
    listings = FakeListings(
        _listing(1, status=ListingStatus.OPEN, opened_at=stale_at),
        _listing(2, status=ListingStatus.OPEN, opened_at=fresh_at),
    )

    closed = _service(listings).close_stale(NOW)

    assert closed == 1
    assert [_status(listings, pk) for pk in (1, 2)] == [
        (ListingStatus.CLOSED, stale_at),
        (ListingStatus.OPEN, fresh_at),
    ]
