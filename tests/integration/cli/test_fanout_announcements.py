from django.core.management import call_command

from ludamus.links.db.django.models import (
    Announcement,
    Notification,
    NotificationSubscription,
)
from ludamus.pacts.legacy import NotificationKind


class TestFanoutAnnouncements:
    def test_notifies_unmuted_subscribers_once(self, sphere, active_user):
        NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, source="visit"
        )
        announcement = Announcement.objects.create(
            sphere=sphere, title="Doors open at 9", content="Hall B, badge in hand."
        )

        call_command("fanout_announcements")
        call_command("fanout_announcements")

        notification = Notification.objects.get(recipient=active_user)
        assert notification.kind == NotificationKind.ANNOUNCEMENT.value
        assert notification.title == "Doors open at 9"
        assert notification.body == "Hall B, badge in hand."
        # No url: the bell opens an announcement in place instead of navigating.
        assert not notification.url
        assert notification.payload == {"announcement_id": announcement.pk}
        announcement.refresh_from_db()
        assert announcement.notified_at is not None

    def test_skips_muted_subscribers_and_leaves_drafts_unclaimed(
        self, sphere, active_user
    ):
        NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, muted=True, source="visit"
        )
        published = Announcement.objects.create(
            sphere=sphere, title="Doors open at 9", content="Hall B."
        )
        draft = Announcement.objects.create(
            sphere=sphere, title="Draft", content="Body", is_published=False
        )

        call_command("fanout_announcements")

        assert not Notification.objects.exists()
        published.refresh_from_db()
        assert published.notified_at is not None
        draft.refresh_from_db()
        assert draft.notified_at is None
