from datetime import UTC, datetime, timedelta

from ludamus.inits.builders import build_listings
from ludamus.pacts.listing import ListingStatus
from tests.integration.conftest import ListingFactory


def test_closes_listings_open_for_thirty_days(sphere):
    now = datetime.now(UTC)
    stale = ListingFactory(sphere=sphere, opened_at=now - timedelta(days=31))
    fresh = ListingFactory(sphere=sphere, opened_at=now - timedelta(days=29))
    draft = ListingFactory(sphere=sphere, status=ListingStatus.DRAFT, opened_at=None)

    closed = build_listings().close_stale(now)

    assert closed == 1
    assert [
        listing.status
        for listing in (stale, fresh, draft)
        if not listing.refresh_from_db()
    ] == [ListingStatus.CLOSED, ListingStatus.OPEN, ListingStatus.DRAFT]
