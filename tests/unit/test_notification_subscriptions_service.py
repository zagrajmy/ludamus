from contextlib import contextmanager

import pytest

from ludamus.mills.notifications import NotificationSubscriptionsService
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.notifications import SubscriptionDTO, SubscriptionSource


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


class FakeRepo:
    def __init__(self, *, subscriptions=(), known_pks=()):
        self._subscriptions = list(subscriptions)
        self._known_pks = set(known_pks)
        self.ensured_spheres = []
        self.muted = []

    def ensure_sphere(self, *, user_id, sphere_id, source):
        self.ensured_spheres.append((user_id, sphere_id, source))

    def list_for_user(self, user_id):
        return list(self._subscriptions)

    def set_muted(self, *, user_id, pk, muted):
        if pk not in self._known_pks:
            return False
        self.muted.append((user_id, pk, muted))
        return True


class TestSubscribe:
    def test_sphere_visit_ensures_with_visit_source(self):
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = NotificationSubscriptionsService(transaction, repo)

        service.subscribe_sphere_visit(user_id=7, sphere_id=3)

        assert transaction.entered == 1
        assert repo.ensured_spheres == [(7, 3, SubscriptionSource.VISIT)]


class TestListForUser:
    def test_returns_the_repository_rows(self):
        subscription = SubscriptionDTO(pk=1, muted=False, sphere_name="Alpha")
        repo = FakeRepo(subscriptions=[subscription])
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        assert service.list_for_user(7) == [subscription]


class TestSetMuted:
    def test_mutes_owned_subscription(self):
        repo = FakeRepo(known_pks=[5])
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        service.set_muted(user_id=7, pk=5, muted=True)

        assert repo.muted == [(7, 5, True)]

    def test_foreign_subscription_raises(self):
        repo = FakeRepo(known_pks=[])
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        with pytest.raises(NotFoundError):
            service.set_muted(user_id=7, pk=5, muted=True)
