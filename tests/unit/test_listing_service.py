from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.listing import ListingService
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    BoardCategoryFacetDTO,
    BoardSearchDTO,
    BoardTagFacetDTO,
    ListingBoardRowDTO,
    ListingContact,
    ListingContactMissingError,
    ListingDTO,
    ListingSeeking,
    ListingStatus,
    ListingStatusError,
)
from ludamus.pacts.tags import TagDTO
from tests.unit.factories import FakeTransaction, user_dto

SPHERE_PK = 1
AUTHOR_PK = 2
STRANGER_PK = 3
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

_WRITE = {
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

    def board_rows(self, *, sphere_id, seeking, statuses):
        return [
            ListingBoardRowDTO(
                pk=listing.pk,
                status=listing.status,
                title=listing.title,
                what=listing.what,
                tag_ids=self.tags.get(listing.pk, []),
            )
            for listing in reversed(self.rows.values())
            if listing.sphere_id == sphere_id
            and listing.status in statuses
            and seeking in {None, listing.seeking}
        ]


HORROR, COSMIC, GOTHIC, FANTASY, SCIFI = 10, 11, 12, 13, 14
COC, DND = 20, 21
ONE_SHOT = 30
CALM = 40


class FakeTags:
    @staticmethod
    def read_all():
        return [
            TagDTO(
                pk=pk,
                category_slug=category_slug,
                slug=name.casefold(),
                name=name,
                parent_slug=parent_slug,
            )
            for pk, category_slug, name, parent_slug in (
                (HORROR, "genre", "Horror", None),
                (COSMIC, "genre", "Cosmic", "horror"),
                (GOTHIC, "genre", "Gothic", "horror"),
                (FANTASY, "genre", "Fantasy", None),
                (SCIFI, "genre", "Scifi", None),
                (COC, "system", "CoC", None),
                (DND, "system", "DnD", None),
                (ONE_SHOT, "length", "One-shot", None),
                (CALM, "mood", "Calm", None),
            )
        ]

    @staticmethod
    def category_names():
        return {
            "system": "System",
            "mood": "Mood",
            "length": "Length",
            "genre": "Genre",
        }


class FakeUsers:
    def __init__(self, **profile):
        self.user = user_dto(pk=AUTHOR_PK, **profile)

    def read_by_id(self, pk):
        assert pk == AUTHOR_PK
        return self.user


def _service(listings, **profile):
    return ListingService(
        transaction=FakeTransaction(),
        listings=listings,
        users=FakeUsers(**profile),
        tags=FakeTags(),
    )


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


def _filters(**overrides):
    return {
        "seeking": None,
        "search": "",
        "tag_ids": [],
        "show_closed": False,
    } | overrides


def _facet(*, pk, name, count, selected=False, children=()):
    return BoardTagFacetDTO(
        pk=pk, name=name, count=count, selected=selected, children=list(children)
    )


class TestSearchBoard:
    @pytest.fixture
    def listings(self):
        listings = FakeListings()
        for title, tag_ids in (
            ("Zew Cthulhu", [COSMIC, GOTHIC, COC, ONE_SHOT]),
            ("Smocza Jama", [FANTASY, DND, ONE_SHOT]),
            ("Horror w Łodzi", [HORROR, DND, ONE_SHOT]),
        ):
            listing = listings.add(title=title)
            listings.set_tags(pk=listing.pk, tag_ids=tag_ids)
            listings.open(pk=listing.pk, at=NOW)
        return listings

    def _ids(self, listings, **filters):
        return (
            _service(listings)
            .search_board(sphere_id=SPHERE_PK, filters=_filters(**filters))
            .listing_ids
        )

    def test_closed_listings_are_hidden_unless_asked_and_then_come_last(self, listings):
        listings.close(2)

        assert (self._ids(listings), self._ids(listings, show_closed=True)) == (
            [3, 1],
            [3, 1, 2],
        )

    def test_search_folds_case_and_diacritics(self, listings):
        assert self._ids(listings, search="LODZ") == [3]

    def test_search_needs_every_word_in_title_or_what(self, listings):
        assert (
            self._ids(listings, search="zew ONE-SHOT"),
            self._ids(listings, search="zew smocza"),
        ) == ([1], [])

    def test_tag_matches_listings_tagged_with_its_descendants(self, listings):
        assert self._ids(listings, tag_ids=[HORROR]) == [3, 1]

    def test_tags_or_within_a_category_and_across_categories(self, listings):
        assert self._ids(listings, tag_ids=[HORROR, FANTASY, DND]) == [3, 2]

    def test_unknown_tag_is_ignored(self, listings):
        assert self._ids(listings, tag_ids=[999]) == [3, 2, 1]

    def test_facets_count_without_their_own_picks_and_hide_what_cannot_narrow(
        self, listings
    ):
        result = _service(listings).search_board(
            sphere_id=SPHERE_PK, filters=_filters(tag_ids=[HORROR])
        )

        assert result == BoardSearchDTO(
            listing_ids=[3, 1],
            facets=[
                BoardCategoryFacetDTO(
                    slug="genre",
                    name="Genre",
                    tags=[
                        _facet(pk=FANTASY, name="Fantasy", count=1),
                        _facet(
                            pk=HORROR,
                            name="Horror",
                            count=2,
                            selected=True,
                            children=[
                                _facet(pk=COSMIC, name="Cosmic", count=1),
                                _facet(pk=GOTHIC, name="Gothic", count=1),
                            ],
                        ),
                    ],
                ),
                BoardCategoryFacetDTO(
                    slug="system",
                    name="System",
                    tags=[
                        _facet(pk=COC, name="CoC", count=1),
                        _facet(pk=DND, name="DnD", count=1),
                    ],
                ),
            ],
        )

    def test_picked_category_stays_shown_even_when_it_cannot_narrow(self, listings):
        result = _service(listings).search_board(
            sphere_id=SPHERE_PK, filters=_filters(tag_ids=[ONE_SHOT])
        )

        assert (
            BoardCategoryFacetDTO(
                slug="length",
                name="Length",
                tags=[_facet(pk=ONE_SHOT, name="One-shot", count=3, selected=True)],
            )
            in result.facets
        )
