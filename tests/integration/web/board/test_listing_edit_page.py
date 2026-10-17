from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib.messages import constants
from django.urls import reverse

from tests.integration.conftest import ListingFactory
from tests.integration.utils import (
    FormInitialMatcher,
    assert_response,
    assert_response_404,
)
from tests.integration.web.board.expected import listing_dto


def _url(listing):
    return reverse("web:board:edit", kwargs={"pk": listing.pk})


def _post(**overrides):
    return {
        "pair": "player:group",
        "title": "New title",
        "what": "Board games",
        "starts_at": "2031-05-01T19:00",
        "contact": "email",
    } | overrides


class TestListingEditPageView:
    def test_get_fills_the_form(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            starts_at=datetime(2031, 5, 1, 17, 0, tzinfo=UTC),
        )

        response = authenticated_client.get(_url(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormInitialMatcher(
                    pair="gm:players",
                    title=listing.title,
                    what=listing.what,
                    tags=[],
                    starts_at=datetime(2031, 5, 1, 17, 0, tzinfo=UTC),
                    when_text="Fridays",
                ),
                "listing": listing_dto(listing),
            },
            template_name="board/edit.html",
        )

    def test_post_updates(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(sphere=sphere, author=active_user)

        response = authenticated_client.post(_url(listing), _post())

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Listing updated."),),
            url=reverse("web:board:detail", kwargs={"pk": listing.pk}),
        )
        listing.refresh_from_db()
        assert (listing.role, listing.seeking, listing.title, listing.what) == (
            "player",
            "group",
            "New title",
            "Board games",
        )

    def test_someone_elses_listing_is_not_found_and_unchanged(
        self, authenticated_client, sphere
    ):
        listing = ListingFactory(sphere=sphere)
        before = listing_dto(listing)

        response = authenticated_client.post(_url(listing), _post())

        assert_response_404(response)
        assert listing_dto(listing) == before
