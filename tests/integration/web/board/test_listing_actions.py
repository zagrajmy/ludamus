from datetime import UTC, datetime, timedelta

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.pacts.listing import ListingContact, ListingStatus
from tests.integration.conftest import ListingFactory
from tests.integration.utils import (
    RequestTimeMatcher,
    assert_response,
    assert_response_404,
)
from tests.integration.web.board.expected import listing_dto


def _url(name, listing):
    return reverse(f"web:board:{name}", kwargs={"pk": listing.pk})


def _detail(listing):
    return reverse("web:board:detail", kwargs={"pk": listing.pk})


class TestListingPublishActionView:
    def test_opens_a_draft(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            status=ListingStatus.DRAFT,
            opened_at=None,
        )

        response = authenticated_client.post(_url("publish", listing))

        assert_response(
            response,
            302,
            messages=((constants.SUCCESS, "Listing published."),),
            url=_detail(listing),
        )
        listing.refresh_from_db()
        assert (listing.status, listing.opened_at) == (
            ListingStatus.OPEN,
            RequestTimeMatcher(),
        )

    def test_discord_contact_without_discord_stays_a_draft(
        self, authenticated_client, active_user, sphere
    ):
        active_user.discord_username = ""
        active_user.save()
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            contact=ListingContact.DISCORD,
            status=ListingStatus.DRAFT,
            opened_at=None,
        )

        response = authenticated_client.post(_url("publish", listing))

        assert_response(
            response,
            302,
            messages=(
                (
                    constants.ERROR,
                    (
                        "Add your Discord username to your profile, or pick "
                        "another contact."
                    ),
                ),
            ),
            url=_detail(listing),
        )
        listing.refresh_from_db()
        assert listing.status == ListingStatus.DRAFT

    def test_email_contact_without_email_stays_a_draft(
        self, authenticated_client, active_user, sphere
    ):
        active_user.email = ""
        active_user.save()
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            contact=ListingContact.EMAIL,
            status=ListingStatus.DRAFT,
            opened_at=None,
        )

        response = authenticated_client.post(_url("publish", listing))

        assert_response(
            response,
            302,
            messages=(
                (
                    constants.ERROR,
                    "Add an email address to your profile, or pick another contact.",
                ),
            ),
            url=_detail(listing),
        )
        listing.refresh_from_db()
        assert listing.status == ListingStatus.DRAFT

    def test_closed_listing_reports_the_stale_click_and_stays_closed(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(
            sphere=sphere, author=active_user, status=ListingStatus.CLOSED
        )
        before = listing_dto(listing)

        response = authenticated_client.post(_url("publish", listing))

        assert_response(
            response,
            302,
            messages=(
                (
                    constants.ERROR,
                    "This listing has already changed. Nothing was done.",
                ),
            ),
            url=_detail(listing),
        )
        assert listing_dto(listing) == before


class TestListingCloseActionView:
    def test_closes(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(sphere=sphere, author=active_user)

        response = authenticated_client.post(_url("close", listing))

        assert_response(
            response,
            302,
            messages=((constants.SUCCESS, "Listing closed."),),
            url=_detail(listing),
        )
        listing.refresh_from_db()
        assert listing.status == ListingStatus.CLOSED

    def test_someone_elses_listing_is_not_found_and_unchanged(
        self, authenticated_client, sphere
    ):
        listing = ListingFactory(sphere=sphere)
        before = listing_dto(listing)

        response = authenticated_client.post(_url("close", listing))

        assert_response_404(response)
        assert listing_dto(listing) == before


class TestListingReopenActionView:
    def test_reopens_and_restarts_the_clock(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            status=ListingStatus.CLOSED,
            opened_at=datetime.now(UTC) - timedelta(days=40),
        )

        response = authenticated_client.post(_url("reopen", listing))

        assert_response(
            response,
            302,
            messages=((constants.SUCCESS, "Listing reopened."),),
            url=_detail(listing),
        )
        listing.refresh_from_db()
        assert (listing.status, listing.opened_at) == (
            ListingStatus.OPEN,
            RequestTimeMatcher(),
        )
