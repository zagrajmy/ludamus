from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.dashboard import DashboardService, SphereSubscriptionService
from ludamus.pacts.dashboard import (
    DASHBOARD_OPEN_ENCOUNTERS,
    DASHBOARD_SPHERE_FEED,
    DASHBOARD_SPHERES_TO_DISCOVER,
    DashboardCardDTO,
    DashboardRole,
    DashboardSphereDTO,
    SphereEventAnnouncementDTO,
    SubscriptionRecipientDTO,
)

NOW = datetime(2026, 6, 4, 12, tzinfo=UTC)


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


def _card(title):
    return DashboardCardDTO(
        title=title,
        url=f"https://example.test/{title}",
        start_time=NOW,
        origin_name="Kapitularz",
        role=DashboardRole.OPEN,
    )


class FakeDashboardRepo:
    def __init__(self):
        self.limits: dict[str, int] = {}

    def list_agenda(self, user_id, *, now):
        del user_id, now
        return [_card("agenda")]

    def list_open_encounters(self, user_id, *, now, limit):
        del user_id, now
        self.limits["open"] = limit
        return [_card("open")]

    def list_sphere_feed(self, user_id, *, now, limit):
        del user_id, now
        self.limits["feed"] = limit
        return [_card("feed")]

    def list_spheres_to_discover(self, user_id, *, now, limit):
        del user_id, now
        self.limits["discover"] = limit
        return [DashboardSphereDTO(pk=1, name="Kapitularz", url="https://ka.test/")]


class FakeSubscriptionsRepo:
    def __init__(self, pending=()):
        self.pending = list(pending)
        self.subscribed: list[tuple[int, int]] = []
        self.unsubscribed: list[tuple[int, int]] = []
        self.announced: list[tuple[int, datetime]] = []

    def subscribe(self, *, sphere_id, user_id):
        self.subscribed.append((sphere_id, user_id))

    def unsubscribe(self, *, sphere_id, user_id):
        self.unsubscribed.append((sphere_id, user_id))

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


class TestDashboardService:
    def test_read_fills_every_section_with_its_own_limit(self):
        repo = FakeDashboardRepo()

        dashboard = DashboardService(repo).read(user_id=1, now=NOW)

        assert [card.title for card in dashboard.agenda] == ["agenda"]
        assert [card.title for card in dashboard.open_encounters] == ["open"]
        assert [card.title for card in dashboard.sphere_feed] == ["feed"]
        assert [sphere.name for sphere in dashboard.discover] == ["Kapitularz"]
        assert repo.limits == {
            "open": DASHBOARD_OPEN_ENCOUNTERS,
            "feed": DASHBOARD_SPHERE_FEED,
            "discover": DASHBOARD_SPHERES_TO_DISCOVER,
        }


def _service(repo, notifier):
    return SphereSubscriptionService(
        transaction=FakeTransaction(), subscriptions=repo, notifier=notifier
    )


class TestSphereSubscriptionService:
    def test_subscribe_and_unsubscribe_reach_the_repository(self):
        repo = FakeSubscriptionsRepo()

        service = _service(repo, FakeNotifier())
        service.subscribe(sphere_id=3, user_id=9)
        service.unsubscribe(sphere_id=3, user_id=9)

        assert repo.subscribed == [(3, 9)]
        assert repo.unsubscribed == [(3, 9)]

    def test_announce_notifies_every_subscriber_and_stamps_the_event(self):
        repo = FakeSubscriptionsRepo(
            pending=[
                _announcement(
                    recipients=[
                        SubscriptionRecipientDTO(user_id=1, email="a@example.test"),
                        SubscriptionRecipientDTO(user_id=2, email="b@example.test"),
                    ]
                )
            ]
        )
        notifier = FakeNotifier()

        announced = _service(repo, notifier).announce_published_events(now=NOW)

        assert announced == 1
        assert repo.announced == [(7, NOW)]
        assert [n.recipient_user_id for n in notifier.sent] == [1, 2]
        assert notifier.sent[0].event_name == "Kapitularz 2026"

    def test_an_event_with_no_subscribers_is_stamped_and_never_revisited(self):
        # Otherwise the sweep would re-read it on every tick forever, and the
        # first person to subscribe would be told about an old announcement.
        repo = FakeSubscriptionsRepo(pending=[_announcement(recipients=[])])
        notifier = FakeNotifier()

        announced = _service(repo, notifier).announce_published_events(now=NOW)

        assert announced == 1
        assert repo.announced == [(7, NOW)]
        assert not notifier.sent
