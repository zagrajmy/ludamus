from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.dashboard import SphereSubscriptionService
from ludamus.pacts.dashboard import SphereEventAnnouncementDTO

NOW = datetime(2026, 6, 4, 12, tzinfo=UTC)


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeSubscriptionsRepo:
    def __init__(self, pending=()):
        self.pending = list(pending)
        self.announced: list[tuple[int, datetime]] = []

    def list_pending_announcements(self, *, now):
        del now
        return self.pending

    def mark_announced(self, event_pk, *, at):
        self.announced.append((event_pk, at))


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify_sphere_event_published(self, notification):
        self.sent.append(notification)


def _announcement(*, recipients):
    return SphereEventAnnouncementDTO(
        event_pk=7,
        event_name="Kapitularz 2026",
        event_slug="kapitularz-2026",
        sphere_name="Kapitularz",
        sphere_domain="kapitularz.example.test",
        recipients=recipients,
    )


def _service(repo, notifier):
    return SphereSubscriptionService(
        transaction=FakeTransaction(), subscriptions=repo, notifier=notifier
    )


class TestSphereSubscriptionService:
    def test_an_event_with_no_subscribers_is_stamped_and_never_revisited(self):
        # Otherwise the sweep would re-read it on every tick forever, and the
        # first person to subscribe would be told about an old announcement.
        repo = FakeSubscriptionsRepo(pending=[_announcement(recipients=[])])
        notifier = FakeNotifier()

        announced = _service(repo, notifier).announce_published_events(now=NOW)

        assert announced == 1
        assert repo.announced == [(7, NOW)]
        assert not notifier.sent
