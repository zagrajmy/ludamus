from datetime import UTC, datetime, timedelta

from django.core import mail

from ludamus.inits.builders import build_listings
from ludamus.links.db.django.models import ListingResponse, Notification
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.listing import ListingContact, ListingResponseStatus, ListingStatus
from tests.integration.conftest import ListingFactory, UserFactory


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


def test_tells_everyone_still_waiting_they_were_not_chosen(sphere):
    now = datetime.now(UTC)
    stale = ListingFactory(
        sphere=sphere, title="Mörk Borg", opened_at=now - timedelta(days=31)
    )
    waiting = ListingResponse.objects.create(
        listing=stale, user=UserFactory(), contact=ListingContact.EMAIL
    )

    build_listings().close_stale(now)

    waiting.refresh_from_db()
    assert waiting.status == ListingResponseStatus.NOT_CHOSEN
    assert list(Notification.objects.values_list("recipient", "kind", "title")) == [
        (waiting.user_id, NotificationKind.LISTING_NOT_CHOSEN, "Mörk Borg has closed")
    ]
    assert not mail.outbox
