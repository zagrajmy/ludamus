from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from django.urls import reverse

from ludamus.pacts.listing import ListingStatus
from tests.integration.conftest import ListingFactory
from tests.integration.utils import PageMatcher, assert_response, assert_response_404
from tests.integration.web.board.expected import listing_dto

URL = reverse("web:board:index")


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
            context_data={
                "page_obj": PageMatcher(number=1, num_pages=1),
                "page_sizes": [10, 20, 50, 100],
            },
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
            context_data={
                "page_obj": PageMatcher(number=2, num_pages=2),
                "page_sizes": [10, 20, 50, 100],
            },
            template_name="board/index.html",
        )
        assert list(response.context["page_obj"]) == [listing_dto(listings[-1])]

    def test_empty_board(self, client):
        response = client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "page_obj": PageMatcher(number=1, num_pages=1),
                "page_sizes": [10, 20, 50, 100],
            },
            template_name="board/index.html",
        )
        assert not list(response.context["page_obj"])

    def test_other_sphere_has_no_board(self, client, non_root_sphere):
        response = client.get(URL, HTTP_HOST=non_root_sphere.site.domain)

        assert_response_404(response)
