from http import HTTPStatus

from django.urls import reverse

from ludamus.pacts.listing import ListingStatus
from tests.integration.conftest import ListingFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.board.expected import listing_dto


def _url(listing):
    return reverse("web:board:detail", kwargs={"pk": listing.pk})


class TestListingDetailPageView:
    def test_anyone_sees_an_open_listing(self, client, sphere):
        listing = ListingFactory(sphere=sphere)

        response = client.get(_url(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"listing": listing_dto(listing), "is_author": False},
            template_name="board/detail.html",
        )

    def test_author_sees_their_draft(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            status=ListingStatus.DRAFT,
            opened_at=None,
        )

        response = authenticated_client.get(_url(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"listing": listing_dto(listing), "is_author": True},
            template_name="board/detail.html",
        )

    def test_someone_elses_draft_is_not_found(self, authenticated_client, sphere):
        listing = ListingFactory(
            sphere=sphere, status=ListingStatus.DRAFT, opened_at=None
        )

        response = authenticated_client.get(_url(listing))

        assert_response_404(response)

    def test_listing_of_another_sphere_is_not_found(self, client, non_root_sphere):
        listing = ListingFactory(sphere=non_root_sphere)

        response = client.get(_url(listing))

        assert_response_404(response)
