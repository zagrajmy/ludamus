from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Tag, TagCategory
from ludamus.pacts.listing import (
    BoardCategoryFacetDTO,
    BoardTagFacetDTO,
    ListingSeeking,
    ListingStatus,
)
from tests.integration.conftest import ListingFactory
from tests.integration.utils import PageMatcher, assert_response, assert_response_404
from tests.integration.web.board.expected import listing_dto

URL = reverse("web:board:index")


def _context(*, num_pages=1, number=1, facets=(), is_filtered=False):
    return {
        "form": ANY,
        "facets": list(facets),
        "is_filtered": is_filtered,
        "page_obj": PageMatcher(number=number, num_pages=num_pages),
        "page_sizes": [10, 20, 50, 100],
    }


def _facet(tag, *, count, selected=False, children=()):
    return BoardTagFacetDTO(
        pk=tag.pk,
        name=tag.name,
        count=count,
        selected=selected,
        children=list(children),
    )


@pytest.fixture(name="activity")
def activity_fixture():
    category = TagCategory.objects.create(slug="activity", name="Activity")
    ttrpg = Tag.objects.create(category=category, slug="ttrpg", name="TTRPG")
    osr = Tag.objects.create(category=category, slug="osr", name="OSR", parent=ttrpg)
    mork = Tag.objects.create(
        category=category, slug="mork-borg", name="Mörk Borg", parent=osr
    )
    board_game = Tag.objects.create(
        category=category, slug="board-game", name="Board game"
    )
    return {"ttrpg": ttrpg, "osr": osr, "mork": mork, "board_game": board_game}


@pytest.fixture(name="genre")
def genre_fixture():
    category = TagCategory.objects.create(slug="genre", name="Genre")
    return {
        "horror": Tag.objects.create(category=category, slug="horror", name="Horror"),
        "fantasy": Tag.objects.create(
            category=category, slug="fantasy", name="Fantasy"
        ),
    }


class TestBoardPageView:
    def test_shows_open_listings_newest_first(self, client, sphere, non_root_sphere):
        now = datetime.now(UTC)
        older = ListingFactory(sphere=sphere, opened_at=now - timedelta(days=2))
        newer = ListingFactory(sphere=sphere, opened_at=now - timedelta(days=1))
        ListingFactory(sphere=sphere, status=ListingStatus.DRAFT, opened_at=None)
        ListingFactory(sphere=sphere, status=ListingStatus.CLOSED)
        ListingFactory(sphere=non_root_sphere)

        response = client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [
            listing_dto(newer),
            listing_dto(older),
        ]

    def test_second_page_holds_the_rest(self, client, sphere):
        now = datetime.now(UTC)
        listings = [
            ListingFactory(sphere=sphere, opened_at=now - timedelta(hours=hours))
            for hours in range(11)
        ]

        response = client.get(URL, {"page": 2, "page_size": 10})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(number=2, num_pages=2),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [listing_dto(listings[-1])]

    def test_empty_board(self, client):
        response = client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(),
            template_name="board/index.html",
        )
        assert not list(response.context["page_obj"])

    def test_signed_in_with_the_board_public(
        self, authenticated_client, settings, sphere
    ):
        settings.BOARD_PUBLIC = True
        listing = ListingFactory(sphere=sphere, medium="Foundry", place="Kraków")
        category = TagCategory.objects.create(slug="genre", name="Genre")
        listing.picked_tags.set(
            [Tag.objects.create(category=category, slug="horror", name="Horror")]
        )

        response = authenticated_client.get(URL)

        # One listing cannot be split, so Genre offers no filter.
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [listing_dto(listing)]

    def test_other_sphere_has_no_board(self, client, non_root_sphere):
        response = client.get(URL, HTTP_HOST=non_root_sphere.site.domain)

        assert_response_404(response)


class TestBoardFilters:
    @pytest.mark.parametrize(
        ("looking_for", "seeking"),
        (("game", ListingSeeking.PLAYERS), ("players", ListingSeeking.GM)),
    )
    def test_looking_for_matches_what_the_listing_offers(
        self, client, sphere, looking_for, seeking
    ):
        match = ListingFactory(sphere=sphere, seeking=seeking)
        ListingFactory(
            sphere=sphere,
            seeking=(
                ListingSeeking.GM
                if seeking is ListingSeeking.PLAYERS
                else ListingSeeking.PLAYERS
            ),
        )

        response = client.get(URL, {"looking_for": looking_for})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(is_filtered=True),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [listing_dto(match)]

    def test_search_ignores_case_and_diacritics(self, client, sphere):
        by_title = ListingFactory(sphere=sphere, title="Kampania Mörk Borg", what="x")
        by_what = ListingFactory(
            sphere=sphere, title="Piątek", what="one-shot w MÖRK BORG"
        )
        ListingFactory(sphere=sphere, title="Zew Cthulhu", what="kampania")

        response = client.get(URL, {"q": "mork borg"})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(is_filtered=True),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [
            listing_dto(by_what),
            listing_dto(by_title),
        ]

    def test_parent_tag_finds_its_descendants_and_counts_roll_up(
        self, client, sphere, activity
    ):
        mork = ListingFactory(sphere=sphere)
        mork.picked_tags.set([activity["mork"]])
        board_game = ListingFactory(sphere=sphere)
        board_game.picked_tags.set([activity["board_game"]])
        ListingFactory(sphere=sphere)

        response = client.get(URL, {"tag": activity["ttrpg"].pk})

        mork_facet = _facet(activity["mork"], count=1)
        osr_facet = _facet(activity["osr"], count=1, children=[mork_facet])
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                is_filtered=True,
                facets=[
                    BoardCategoryFacetDTO(
                        slug="activity",
                        name="Activity",
                        tags=[
                            _facet(activity["board_game"], count=1),
                            _facet(
                                activity["ttrpg"],
                                count=1,
                                selected=True,
                                children=[osr_facet],
                            ),
                        ],
                    )
                ],
            ),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [listing_dto(mork)]

    def test_categories_combine_with_and_values_with_or(
        self, client, sphere, activity, genre
    ):
        now = datetime.now(UTC)
        horror_osr = ListingFactory(sphere=sphere, opened_at=now)
        horror_osr.picked_tags.set([activity["osr"], genre["horror"]])
        fantasy_board = ListingFactory(sphere=sphere, opened_at=now - timedelta(1))
        fantasy_board.picked_tags.set([activity["board_game"], genre["fantasy"]])
        horror_board = ListingFactory(sphere=sphere, opened_at=now - timedelta(2))
        horror_board.picked_tags.set([activity["board_game"], genre["horror"]])

        response = client.get(
            URL,
            {
                "tag": [
                    genre["horror"].pk,
                    genre["fantasy"].pk,
                    activity["board_game"].pk,
                ]
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                is_filtered=True,
                facets=[
                    BoardCategoryFacetDTO(
                        slug="activity",
                        name="Activity",
                        tags=[
                            _facet(activity["board_game"], count=2, selected=True),
                            _facet(
                                activity["ttrpg"],
                                count=1,
                                children=[_facet(activity["osr"], count=1)],
                            ),
                        ],
                    ),
                    BoardCategoryFacetDTO(
                        slug="genre",
                        name="Genre",
                        tags=[
                            _facet(genre["fantasy"], count=1, selected=True),
                            _facet(genre["horror"], count=1, selected=True),
                        ],
                    ),
                ],
            ),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [
            listing_dto(fantasy_board),
            listing_dto(horror_board),
        ]

    def test_category_that_does_not_split_the_results_is_hidden(
        self, client, sphere, activity, genre
    ):
        osr = ListingFactory(sphere=sphere)
        osr.picked_tags.set([activity["osr"], genre["horror"]])
        board_game = ListingFactory(sphere=sphere)
        board_game.picked_tags.set([activity["board_game"], genre["horror"]])

        response = client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                facets=[
                    BoardCategoryFacetDTO(
                        slug="activity",
                        name="Activity",
                        tags=[
                            _facet(activity["board_game"], count=1),
                            _facet(
                                activity["ttrpg"],
                                count=1,
                                children=[_facet(activity["osr"], count=1)],
                            ),
                        ],
                    )
                ]
            ),
            template_name="board/index.html",
        )

    def test_show_closed_lists_closed_after_open(self, client, sphere):
        now = datetime.now(UTC)
        closed = ListingFactory(
            sphere=sphere, status=ListingStatus.CLOSED, opened_at=now
        )
        open_listing = ListingFactory(sphere=sphere, opened_at=now - timedelta(1))
        ListingFactory(sphere=sphere, status=ListingStatus.DRAFT, opened_at=None)

        response = client.get(URL, {"closed": "on"})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(is_filtered=True),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [
            listing_dto(open_listing),
            listing_dto(closed),
        ]

    def test_malformed_filters_are_ignored(self, client, sphere):
        listing = ListingFactory(sphere=sphere)

        response = client.get(URL, {"tag": "x", "looking_for": "dragons"})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(),
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [listing_dto(listing)]

    def test_no_match_says_so(self, client, sphere):
        ListingFactory(sphere=sphere, title="Zew Cthulhu", what="kampania")

        response = client.get(URL, {"q": "warhammer"})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(is_filtered=True),
            template_name="board/index.html",
        )
        assert not list(response.context["page_obj"])
