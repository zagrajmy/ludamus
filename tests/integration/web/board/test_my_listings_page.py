from http import HTTPStatus

from django.urls import reverse

from ludamus.pacts.listing import ListingStatus
from tests.integration.conftest import ListingFactory
from tests.integration.utils import assert_response
from tests.integration.web.board.expected import listing_dto

URL = reverse("web:board:mine")


class TestMyListingsPageView:
    def test_login_required(self, client):
        response = client.get(URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )

    def test_lists_own_listings_in_every_status(
        self, authenticated_client, active_user, sphere
    ):
        draft = ListingFactory(
            sphere=sphere,
            author=active_user,
            status=ListingStatus.DRAFT,
            opened_at=None,
        )
        closed = ListingFactory(
            sphere=sphere, author=active_user, status=ListingStatus.CLOSED
        )
        ListingFactory(sphere=sphere)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"listings": [listing_dto(closed), listing_dto(draft)]},
            template_name="board/mine.html",
        )

    def test_no_listings_yet(self, authenticated_client, sphere):
        ListingFactory(sphere=sphere)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"listings": []},
            template_name="board/mine.html",
        )
