from datetime import timedelta

import pytest

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.listing import (
    BoardCategoryFacetDTO,
    BoardSearchDTO,
    BoardTagFacetDTO,
    ListingContact,
    ListingContactMissingError,
    ListingDetailDTO,
    ListingNotification,
    ListingResponseStage,
    ListingStatus,
    ListingStatusError,
)
from tests.unit.test_listing_service.fakes import (
    AUTHOR_PK,
    COC,
    COSMIC,
    DISCORD_ONLY,
    DND,
    FANTASY,
    GOTHIC,
    HORROR,
    NO_CONTACT,
    NOW,
    ONE_SHOT,
    SPHERE_PK,
    STRANGER_PK,
    WRITE,
    FakeListings,
    FakeNotifier,
    FakeResponses,
    ids_of,
    make_service,
    open_listing,
)


class TestCreate:
    def test_without_publish_at_saves_a_draft_with_its_tags(self):
        listings = FakeListings()

        pk = make_service(listings, **NO_CONTACT).create(
            WRITE | {"sphere_id": SPHERE_PK, "author_id": AUTHOR_PK},
            tag_ids=[5, 6],
            publish_at=None,
        )

        assert (listings.rows[pk].status, listings.tags[pk]) == (
            ListingStatus.DRAFT,
            [5, 6],
        )

    def test_with_publish_at_opens_it_at_that_time(self):
        listings = FakeListings()

        pk = make_service(listings, **DISCORD_ONLY).create(
            WRITE | {"sphere_id": SPHERE_PK, "author_id": AUTHOR_PK},
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
            make_service(listings, **DISCORD_ONLY).create(
                WRITE | {
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

        make_service(listings, **NO_CONTACT).update(
            **ids_of(listing), data=WRITE | {"title": "Renamed"}, tag_ids=[7]
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
            make_service(listings, **NO_CONTACT).update(
                **ids_of(listing), data=WRITE, tag_ids=[]
            )


class TestDetail:
    def test_draft_is_hidden_from_others(self):
        listings = FakeListings()
        listing = listings.add()

        with pytest.raises(NotFoundError):
            make_service(listings).detail(
                pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=STRANGER_PK
            )

    def test_draft_is_shown_to_its_author(self):
        listings = FakeListings()
        listing = listings.add()

        assert (
            make_service(listings)
            .detail(pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=AUTHOR_PK)
            .listing
            == listing
        )

    def test_open_listing_is_shown_to_anonymous_viewers(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        assert (
            make_service(listings)
            .detail(pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=None)
            .listing.status
            is ListingStatus.OPEN
        )

    def test_a_stranger_may_respond_once(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        service = make_service(listings, responses=responses)

        before = service.detail(
            pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=STRANGER_PK
        )
        responses.add(listing.pk)
        after = service.detail(
            pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=STRANGER_PK
        )

        assert (before, after) == (
            ListingDetailDTO(
                listing=listing,
                is_author=False,
                own_response=None,
                can_respond=True,
                waiting_count=None,
                open_for_days=30,
                party_members=[],
            ),
            ListingDetailDTO(
                listing=listing,
                is_author=False,
                own_response=responses.rows[1],
                can_respond=False,
                waiting_count=None,
                open_for_days=30,
                party_members=[],
            ),
        )


def test_contact_channels_lists_what_the_profile_has():
    service = make_service(
        FakeListings(), discord_username="gm#1", email="gm@example.com"
    )

    assert service.contact_channels(AUTHOR_PK) == [
        ListingContact.DISCORD,
        ListingContact.EMAIL,
    ]


class TestTransitions:
    def test_publish_opens_a_draft(self):
        listings = FakeListings()
        listing = listings.add()

        make_service(listings, **DISCORD_ONLY).publish(**ids_of(listing), now=NOW)

        assert listings.rows[listing.pk].opened_at == NOW

    def test_publish_refuses_an_open_listing(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        with pytest.raises(ListingStatusError):
            make_service(listings, **DISCORD_ONLY).publish(
                **ids_of(listing), now=NOW + timedelta(days=1)
            )

        assert listings.rows[listing.pk].opened_at == NOW

    def test_close_closes_an_open_listing(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW)

        make_service(listings).close(**ids_of(listing))

        assert listings.rows[listing.pk].status is ListingStatus.CLOSED

    def test_close_refuses_a_draft(self):
        listings = FakeListings()
        listing = listings.add()

        with pytest.raises(ListingStatusError):
            make_service(listings).close(**ids_of(listing))

    def test_reopen_restarts_the_open_period(self):
        listings = FakeListings()
        listing = listings.add()
        listings.open(pk=listing.pk, at=NOW - timedelta(days=40))
        listings.close(listing.pk)

        make_service(listings, **DISCORD_ONLY).reopen(**ids_of(listing), now=NOW)

        assert (
            listings.rows[listing.pk].status,
            listings.rows[listing.pk].opened_at,
        ) == (ListingStatus.OPEN, NOW)

    def test_another_authors_listing_is_not_found(self):
        listings = FakeListings()
        listing = listings.add(author_id=STRANGER_PK)

        with pytest.raises(NotFoundError):
            make_service(listings).close(**ids_of(listing))


def test_close_stale_closes_only_listings_open_longer_than_the_open_period():
    listings = FakeListings()
    stale = listings.add()
    listings.open(pk=stale.pk, at=NOW - timedelta(days=31))
    fresh = listings.add()
    listings.open(pk=fresh.pk, at=NOW - timedelta(days=29))

    closed = make_service(listings).close_stale(NOW)

    assert (closed, listings.rows[stale.pk].status, listings.rows[fresh.pk].status) == (
        1,
        ListingStatus.CLOSED,
        ListingStatus.OPEN,
    )


def test_update_tells_waiting_responders_the_new_title():
    listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
    listing = open_listing(listings)
    responses.add(listing.pk)

    make_service(
        listings, responses=responses, notifier=notifier, **DISCORD_ONLY
    ).update(**ids_of(listing), data=WRITE | {"title": "Renamed"}, tag_ids=[])

    assert notifier.sent == [
        (
            "changed",
            ListingNotification(
                recipient_user_id=STRANGER_PK,
                listing_id=listing.pk,
                listing_title="Renamed",
            ),
        )
    ]


def test_update_that_changes_nothing_tells_no_one():
    listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
    listing = open_listing(listings)
    responses.add(listing.pk)

    make_service(
        listings, responses=responses, notifier=notifier, **DISCORD_ONLY
    ).update(**ids_of(listing), data=WRITE, tag_ids=[])

    assert not notifier.sent


def test_update_that_changes_only_tags_tells_waiting_responders():
    listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
    listing = open_listing(listings)
    responses.add(listing.pk)

    make_service(
        listings, responses=responses, notifier=notifier, **DISCORD_ONLY
    ).update(**ids_of(listing), data=WRITE, tag_ids=[HORROR])

    assert notifier.sent == [
        (
            "changed",
            ListingNotification(
                recipient_user_id=STRANGER_PK,
                listing_id=listing.pk,
                listing_title=listing.title,
            ),
        )
    ]


def test_close_tells_waiting_responders_they_were_not_chosen():
    listings, notifier = FakeListings(), FakeNotifier()
    responses = FakeResponses(listings)
    listing = open_listing(listings)
    response_pk = responses.add(listing.pk)

    make_service(listings, responses=responses, notifier=notifier).close(
        **ids_of(listing)
    )

    assert (responses.rows[response_pk].stage, notifier.sent) == (
        ListingResponseStage.NOT_CHOSEN,
        [
            (
                "not_chosen",
                ListingNotification(
                    recipient_user_id=STRANGER_PK,
                    listing_id=listing.pk,
                    listing_title="Zew Cthulhu",
                ),
            )
        ],
    )


def _filters(**overrides):
    return {
        "seeking": None,
        "search": "",
        "tag_ids": [],
        "show_closed": False,
    } | overrides


def _facet(*, pk, name, count, selected=False, expanded=False, children=()):
    return BoardTagFacetDTO(
        pk=pk,
        name=name,
        count=count,
        selected=selected,
        expanded=expanded,
        children=list(children),
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

    def ids_of(self, listings, **filters):
        return (
            make_service(listings)
            .search_board(sphere_id=SPHERE_PK, filters=_filters(**filters))
            .listing_ids
        )

    def test_closed_listings_are_hidden_unless_asked(self, listings):
        listings.close(2)

        assert (self.ids_of(listings), self.ids_of(listings, show_closed=True)) == (
            [3, 1],
            [3, 2, 1],
        )

    def test_search_folds_case_and_diacritics(self, listings):
        assert self.ids_of(listings, search="LODZ") == [3]

    def test_search_needs_every_word_in_title_or_what(self, listings):
        assert (
            self.ids_of(listings, search="zew ONE-SHOT"),
            self.ids_of(listings, search="zew smocza"),
        ) == ([1], [])

    def test_tag_matches_listings_tagged_with_its_descendants(self, listings):
        assert self.ids_of(listings, tag_ids=[HORROR]) == [3, 1]

    def test_tags_or_within_a_category_and_across_categories(self, listings):
        assert self.ids_of(listings, tag_ids=[HORROR, FANTASY, DND]) == [3, 2]

    def test_unknown_tag_is_ignored(self, listings):
        assert self.ids_of(listings, tag_ids=[999]) == [3, 2, 1]

    def test_facets_count_without_their_own_picks_and_hide_what_cannot_narrow(
        self, listings
    ):
        result = make_service(listings).search_board(
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
        result = make_service(listings).search_board(
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

    def test_tag_with_a_picked_descendant_comes_expanded(self, listings):
        result = make_service(listings).search_board(
            sphere_id=SPHERE_PK, filters=_filters(tag_ids=[COSMIC])
        )

        assert (
            BoardCategoryFacetDTO(
                slug="genre",
                name="Genre",
                tags=[
                    _facet(pk=FANTASY, name="Fantasy", count=1),
                    _facet(
                        pk=HORROR,
                        name="Horror",
                        count=2,
                        expanded=True,
                        children=[
                            _facet(pk=COSMIC, name="Cosmic", count=1, selected=True),
                            _facet(pk=GOTHIC, name="Gothic", count=1),
                        ],
                    ),
                ],
            )
            in result.facets
        )
