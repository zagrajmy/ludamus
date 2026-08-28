import pytest

from ludamus.links.db.django.models import (
    Announcement,
    Notification,
    NotificationSubscription,
)
from ludamus.links.db.django.notifications import AnnouncementFanoutRepository
from ludamus.pacts.notifications import ClaimedAnnouncementDTO
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(name="repo")
def repo_fixture():
    return AnnouncementFanoutRepository()


@pytest.fixture(name="announcement")
def announcement_fixture(sphere):
    return Announcement.objects.create(sphere=sphere, title="News", content="Body")


class TestClaim:
    def test_claims_published_unnotified_once(self, repo, announcement):
        claimed = repo.claim(announcement.pk)

        assert claimed == ClaimedAnnouncementDTO(
            pk=announcement.pk,
            sphere_id=announcement.sphere_id,
            title="News",
            content="Body",
        )
        announcement.refresh_from_db()
        assert announcement.notified_at is not None
        assert repo.claim(announcement.pk) is None

    def test_draft_is_not_claimable(self, repo, sphere):
        draft = Announcement.objects.create(
            sphere=sphere, title="Draft", content="Body", is_published=False
        )

        assert repo.claim(draft.pk) is None
        draft.refresh_from_db()
        assert draft.notified_at is None


class TestDueIds:
    def test_lists_only_published_unnotified(self, repo, sphere, announcement):
        claimed = Announcement.objects.create(sphere=sphere, title="Old", content="B")
        repo.claim(claimed.pk)
        Announcement.objects.create(
            sphere=sphere, title="Draft", content="B", is_published=False
        )

        assert repo.due_ids() == [announcement.pk]


class TestActiveSphereSubscriberIds:
    def test_excludes_muted_foreign_and_event_subscriptions(self, repo, sphere):
        subscriber = UserFactory(username="sub")
        muted = UserFactory(username="muted")
        elsewhere = UserFactory(username="elsewhere")
        enrolled = UserFactory(username="enrolled")
        NotificationSubscription.objects.create(
            user=subscriber, sphere=sphere, source="visit"
        )
        NotificationSubscription.objects.create(
            user=muted, sphere=sphere, muted=True, source="visit"
        )
        NotificationSubscription.objects.create(
            user=elsewhere, sphere=SphereFactory(), source="visit"
        )
        NotificationSubscription.objects.create(
            user=enrolled, event=EventFactory(sphere=sphere), source="enrollment"
        )

        assert repo.active_sphere_subscriber_ids(sphere.pk) == [subscriber.pk]


class TestCreateAnnouncementNotifications:
    def test_writes_overlay_notifications(self, repo, announcement):
        recipients = [UserFactory(username="one"), UserFactory(username="two")]
        claimed = repo.claim(announcement.pk)

        created = repo.create_announcement_notifications(
            recipient_ids=[user.pk for user in recipients], announcement=claimed
        )

        assert created == len(recipients)
        rows = Notification.objects.order_by("pk")
        assert [
            (row.recipient_id, row.kind, row.title, row.body, row.url, row.payload)
            for row in rows
        ] == [
            (
                recipients[0].pk,
                "announcement",
                "News",
                "Body",
                "",
                {"announcement_id": announcement.pk},
            ),
            (
                recipients[1].pk,
                "announcement",
                "News",
                "Body",
                "",
                {"announcement_id": announcement.pk},
            ),
        ]
