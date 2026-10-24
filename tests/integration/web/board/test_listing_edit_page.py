from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib.messages import constants
from django.urls import reverse

from tests.integration.conftest import ListingFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    FormInitialMatcher,
    assert_response,
    assert_response_404,
)
from tests.integration.web.board.expected import listing_dto


def _url(listing):
    return reverse("web:board:edit", kwargs={"pk": listing.pk})


def _post(**overrides):
    return {
        "seeking": "gm",
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
                    seeking="players",
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
        assert (listing.seeking, listing.title, listing.what) == (
            "gm",
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

    def test_invalid_post_rerenders_and_leaves_the_listing(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user)
        before = listing_dto(listing)

        response = authenticated_client.post(_url(listing), _post(seeking="group"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormErrorsMatcher(
                    seeking=[
                        (
                            "Select a valid choice. group is not one of the "
                            "available choices."
                        )
                    ]
                ),
                "listing": before,
            },
            template_name="board/edit.html",
        )
        assert listing_dto(listing) == before

    def test_open_listing_needs_a_contact_on_the_profile(
        self, authenticated_client, active_user, sphere
    ):
        active_user.discord_username = ""
        active_user.email = ""
        active_user.save()
        listing = ListingFactory(sphere=sphere, author=active_user)
        before = listing_dto(listing)

        response = authenticated_client.post(_url(listing), _post(contact="email"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormErrorsMatcher(
                    contact=[
                        (
                            "Add an email address to your profile, or pick "
                            "another contact."
                        )
                    ]
                ),
                "listing": before,
            },
            template_name="board/edit.html",
        )
        assert listing_dto(listing) == before
