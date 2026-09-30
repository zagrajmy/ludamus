from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

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
AGENDA_ROWS = 20
USER_ID = 5


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
        self.subscribed: set[tuple[int, int]] = set()

    def subscribe(self, *, sphere_id, user_id):
        self.subscribed.add((sphere_id, user_id))

    def unsubscribe(self, *, sphere_id, user_id):
        self.subscribed.discard((sphere_id, user_id))

    def list_pending_announcements(self, *, now):
        del now
        return self.pending

    def mark_announced(self, event_pk, *, at):
        self.announced.append((event_pk, at))


def _card(n, *, role):
    return DashboardCardDTO(
        title=f"Card {n}",
        url=f"/c/{n}",
        start_time=NOW + timedelta(hours=n),
        origin_name="Kapitularz",
        role=role,
    )


class FakeDashboardRepo:
    # Every section has more rows than its limit, so the read shows which
    # limit it hands each one.
    def list_agenda(self, user_id, *, now):
        del user_id, now
        return [_card(n, role=DashboardRole.SIGNED_UP) for n in range(AGENDA_ROWS)]

    def list_open_encounters(self, user_id, *, now, limit):
        del user_id, now
        return [_card(n, role=DashboardRole.OPEN) for n in range(limit)]

    def list_sphere_feed(self, user_id, *, now, limit):
        del user_id, now
        return [_card(n, role=DashboardRole.ORGANIZING) for n in range(limit)]

    def list_spheres_to_discover(self, user_id, *, now, limit):
        del user_id, now
        return [
            DashboardSphereDTO(pk=n, name=f"Sphere {n}", url=f"/s/{n}")
            for n in range(limit)
        ]


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

    def test_each_subscriber_is_told_once_and_the_event_is_stamped(self):
        recipients = [
            SubscriptionRecipientDTO(user_id=1, email="a@example.test"),
            SubscriptionRecipientDTO(user_id=2, email="b@example.test"),
        ]
        repo = FakeSubscriptionsRepo(pending=[_announcement(recipients=recipients)])
        notifier = FakeNotifier()

        announced = _service(repo, notifier).announce_published_events(now=NOW)

        assert announced == 1
        assert repo.announced == [(7, NOW)]
        assert [(n.recipient_user_id, n.recipient_email) for n in notifier.sent] == [
            (1, "a@example.test"),
            (2, "b@example.test"),
        ]
        assert {(n.event_slug, n.sphere_domain) for n in notifier.sent} == {
            ("kapitularz-2026", "kapitularz.example.test")
        }

    def test_subscribe_then_unsubscribe_leaves_no_subscription(self):
        repo = FakeSubscriptionsRepo()
        service = _service(repo, FakeNotifier())

        service.subscribe(sphere_id=3, user_id=USER_ID)
        assert repo.subscribed == {(3, USER_ID)}

        service.unsubscribe(sphere_id=3, user_id=USER_ID)
        assert not repo.subscribed


class TestDashboardService:
    def test_read_caps_every_section_but_the_agenda(self):
        dashboard = DashboardService(FakeDashboardRepo()).read(user_id=USER_ID, now=NOW)

        assert len(dashboard.agenda) == AGENDA_ROWS
        assert len(dashboard.open_encounters) == DASHBOARD_OPEN_ENCOUNTERS
        assert len(dashboard.sphere_feed) == DASHBOARD_SPHERE_FEED
        assert len(dashboard.discover) == DASHBOARD_SPHERES_TO_DISCOVER
        assert {c.role for c in dashboard.open_encounters} == {DashboardRole.OPEN}
