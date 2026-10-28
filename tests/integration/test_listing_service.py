from datetime import UTC, datetime, timedelta

import pytest

from ludamus.inits.builders import build_listings
from ludamus.pacts.listing import (
    ListingContact,
    ListingContactMissingError,
    ListingStatus,
    ListingStatusError,
)
from tests.integration.conftest import ListingFactory
from tests.integration.web.board.expected import listing_dto


def _update(listing, **data):
    build_listings().update(
        pk=listing.pk,
        sphere_id=listing.sphere_id,
        author_id=listing.author_id,
        data={
            "seeking": listing.seeking,
            "title": "Renamed",
            "what": listing.what,
            "description": listing.description,
            "seats": listing.seats,
            "medium": listing.medium,
            "place": listing.place,
            "starts_at": listing.starts_at,
            "when_text": listing.when_text,
            "contact": listing.contact,
        }
        | data,
        tag_ids=[],
    )


def _ids(listing):
    return {
        "pk": listing.pk,
        "sphere_id": listing.sphere_id,
        "author_id": listing.author_id,
    }


class TestUpdate:
    def test_draft_may_name_a_missing_contact(self, sphere, active_user):
        active_user.discord_username = ""
        active_user.save()
        listing = ListingFactory(
            sphere=sphere, author=active_user, status=ListingStatus.DRAFT
        )

        _update(listing, contact=ListingContact.DISCORD)

        listing.refresh_from_db()
        assert (listing.title, listing.contact) == ("Renamed", ListingContact.DISCORD)

    def test_open_listing_with_a_missing_contact_rolls_back(self, sphere, active_user):
        active_user.discord_username = ""
        active_user.save()
        listing = ListingFactory(sphere=sphere, author=active_user)
        before = listing_dto(listing)

        with pytest.raises(ListingContactMissingError):
            _update(listing, contact=ListingContact.DISCORD)

        assert listing_dto(listing) == before


class TestTransitions:
    def test_close_refuses_a_draft(self, sphere):
        listing = ListingFactory(
            sphere=sphere, status=ListingStatus.DRAFT, opened_at=None
        )

        with pytest.raises(ListingStatusError):
            build_listings().close(**_ids(listing))

        listing.refresh_from_db()
        assert listing.status == ListingStatus.DRAFT

    def test_reopen_refuses_a_draft(self, sphere):
        listing = ListingFactory(
            sphere=sphere, status=ListingStatus.DRAFT, opened_at=None
        )

        with pytest.raises(ListingStatusError):
            build_listings().reopen(**_ids(listing), now=datetime.now(UTC))

        listing.refresh_from_db()
        assert (listing.status, listing.opened_at) == (ListingStatus.DRAFT, None)

    def test_reopen_with_a_missing_contact_stays_closed(self, sphere, active_user):
        active_user.discord_username = ""
        active_user.save()
        opened_at = datetime.now(UTC) - timedelta(days=40)
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            contact=ListingContact.DISCORD,
            status=ListingStatus.CLOSED,
            opened_at=opened_at,
        )

        with pytest.raises(ListingContactMissingError):
            build_listings().reopen(**_ids(listing), now=datetime.now(UTC))

        listing.refresh_from_db()
        assert (listing.status, listing.opened_at) == (ListingStatus.CLOSED, opened_at)


def test_contact_channels_lists_what_the_profile_has(active_user):
    active_user.discord_username = "gm#1"
    active_user.email = ""
    active_user.save()

    assert build_listings().contact_channels(active_user.pk) == [ListingContact.DISCORD]
