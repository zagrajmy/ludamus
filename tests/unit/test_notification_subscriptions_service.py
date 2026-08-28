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


def _sphere_sub(pk, *, sphere_id=1, sphere_name="Alpha", muted=False):
    return SubscriptionDTO(
        pk=pk,
        muted=muted,
        sphere_id=sphere_id,
        event_id=None,
        label=sphere_name,
        parent_sphere_id=sphere_id,
        parent_sphere_name=sphere_name,
    )


def _event_sub(pk, *, event_id, label, sphere_id=1, sphere_name="Alpha", muted=False):
    return SubscriptionDTO(
        pk=pk,
        muted=muted,
        sphere_id=None,
        event_id=event_id,
        label=label,
        parent_sphere_id=sphere_id,
        parent_sphere_name=sphere_name,
    )


class FakeRepo:
    def __init__(self, *, subscriptions=(), known_pks=()):
        self._subscriptions = list(subscriptions)
        self._known_pks = set(known_pks)
        self.ensured_spheres = []
        self.ensured_events = []
        self.muted = []

    def ensure_sphere(self, *, user_id, sphere_id, source):
        self.ensured_spheres.append((user_id, sphere_id, source))

    def ensure_events(self, *, user_ids, event_id, source):
        self.ensured_events.append((user_ids, event_id, source))

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

    def test_enrollments_ensure_with_enrollment_source(self):
        repo = FakeRepo()
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        service.subscribe_enrollments(user_ids=[7, 8], event_id=4)

        assert repo.ensured_events == [([7, 8], 4, SubscriptionSource.ENROLLMENT)]

    def test_enrollments_with_no_users_write_nothing(self):
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = NotificationSubscriptionsService(transaction, repo)

        service.subscribe_enrollments(user_ids=[], event_id=4)

        assert transaction.entered == 0
        assert not repo.ensured_events


class TestListGrouped:
    def test_groups_events_under_their_sphere(self):
        sphere_sub = _sphere_sub(1)
        event_sub = _event_sub(2, event_id=10, label="Con")
        repo = FakeRepo(subscriptions=[event_sub, sphere_sub])
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        groups = service.list_grouped(7)

        assert len(groups) == 1
        assert groups[0].sphere_name == "Alpha"
        assert groups[0].sphere_subscription == sphere_sub
        assert groups[0].events == [event_sub]

    def test_event_only_group_has_no_sphere_subscription(self):
        event_sub = _event_sub(2, event_id=10, label="Con")
        repo = FakeRepo(subscriptions=[event_sub])
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        groups = service.list_grouped(7)

        assert groups[0].sphere_subscription is None
        assert groups[0].events == [event_sub]

    def test_groups_sorted_by_sphere_events_by_label(self):
        repo = FakeRepo(
            subscriptions=[
                _sphere_sub(1, sphere_id=2, sphere_name="beta"),
                _event_sub(
                    2, event_id=11, label="Zjazd", sphere_id=2, sphere_name="beta"
                ),
                _event_sub(
                    3, event_id=10, label="Antykon", sphere_id=2, sphere_name="beta"
                ),
                _sphere_sub(4, sphere_id=1, sphere_name="Alpha"),
            ]
        )
        service = NotificationSubscriptionsService(FakeTransaction(), repo)

        groups = service.list_grouped(7)

        assert [g.sphere_name for g in groups] == ["Alpha", "beta"]
        assert [e.label for e in groups[1].events] == ["Antykon", "Zjazd"]


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
