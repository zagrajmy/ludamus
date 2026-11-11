from datetime import UTC, datetime, timedelta
from io import StringIO

from django.core.management import call_command

from ludamus.pacts.listing import ListingStatus
from tests.integration.conftest import ListingFactory


def test_closes_listings_open_for_thirty_days(sphere):
    now = datetime.now(UTC)
    stale = ListingFactory(sphere=sphere, opened_at=now - timedelta(days=31))
    fresh = ListingFactory(sphere=sphere, opened_at=now - timedelta(days=29))
    out = StringIO()

    call_command("close_stale_listings", stdout=out)

    assert "Closed 1 stale listing(s)." in out.getvalue()
    stale.refresh_from_db()
    fresh.refresh_from_db()
    assert (stale.status, fresh.status) == (ListingStatus.CLOSED, ListingStatus.OPEN)
