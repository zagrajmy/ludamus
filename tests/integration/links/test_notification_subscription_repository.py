import pytest

from ludamus.links.db.django.models import NotificationSubscription
from ludamus.links.db.django.notifications import NotificationSubscriptionRepository
from ludamus.pacts.notifications import SubscriptionDTO, SubscriptionSource
from tests.integration.conftest import EventFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(name="repo")
def repo_fixture():
    return NotificationSubscriptionRepository()


class TestEnsureSphere:
    def test_creates_subscription(self, repo, active_user, sphere):
        repo.ensure_sphere(
            user_id=active_user.pk, sphere_id=sphere.pk, source=SubscriptionSource.VISIT
        )

        subscription = NotificationSubscription.objects.get()
        assert subscription.user_id == active_user.pk
        assert subscription.sphere_id == sphere.pk
        assert subscription.event_id is None
        assert subscription.muted is False
        assert subscription.source == "visit"

    def test_repeat_is_idempotent(self, repo, active_user, sphere):
        for _ in range(2):
            repo.ensure_sphere(
                user_id=active_user.pk,
                sphere_id=sphere.pk,
                source=SubscriptionSource.VISIT,
            )

        assert NotificationSubscription.objects.count() == 1

    def test_never_unmutes_existing_subscription(self, repo, active_user, sphere):
        NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, muted=True, source="visit"
        )

        repo.ensure_sphere(
            user_id=active_user.pk, sphere_id=sphere.pk, source=SubscriptionSource.VISIT
        )

        subscription = NotificationSubscription.objects.get()
        assert subscription.muted is True


class TestEnsureEvents:
    def test_creates_subscription_per_user(self, repo, event):
        users = [UserFactory(username="one"), UserFactory(username="two")]

        repo.ensure_events(
            user_ids=[user.pk for user in users],
            event_id=event.pk,
            source=SubscriptionSource.ENROLLMENT,
        )

        rows = NotificationSubscription.objects.order_by("pk")
        assert [(row.user_id, row.event_id, row.source) for row in rows] == [
            (users[0].pk, event.pk, "enrollment"),
            (users[1].pk, event.pk, "enrollment"),
        ]

    def test_never_unmutes_existing_subscription(self, repo, active_user, event):
        NotificationSubscription.objects.create(
            user=active_user, event=event, muted=True, source="enrollment"
        )

        repo.ensure_events(
            user_ids=[active_user.pk],
            event_id=event.pk,
            source=SubscriptionSource.ENROLLMENT,
        )

        subscription = NotificationSubscription.objects.get()
        assert subscription.muted is True


class TestListForUser:
    def test_maps_both_kinds_with_parent_sphere(self, repo, active_user, sphere):
        event = EventFactory(sphere=sphere)
        sphere_sub = NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, source="visit"
        )
        event_sub = NotificationSubscription.objects.create(
            user=active_user, event=event, muted=True, source="enrollment"
        )
        NotificationSubscription.objects.create(
            user=UserFactory(username="other"), sphere=sphere, source="visit"
        )

        result = repo.list_for_user(active_user.pk)

        assert sorted(result, key=lambda s: s.pk) == [
            SubscriptionDTO(
                pk=sphere_sub.pk,
                muted=False,
                sphere_id=sphere.pk,
                event_id=None,
                label=sphere.name,
                parent_sphere_id=sphere.pk,
                parent_sphere_name=sphere.name,
            ),
            SubscriptionDTO(
                pk=event_sub.pk,
                muted=True,
                sphere_id=None,
                event_id=event.pk,
                label=event.name,
                parent_sphere_id=sphere.pk,
                parent_sphere_name=sphere.name,
            ),
        ]


class TestSetMuted:
    def test_updates_own_subscription(self, repo, active_user, sphere):
        subscription = NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, source="visit"
        )

        assert (
            repo.set_muted(user_id=active_user.pk, pk=subscription.pk, muted=True)
            is True
        )
        subscription.refresh_from_db()
        assert subscription.muted is True

    def test_foreign_subscription_untouched(self, repo, active_user, sphere):
        other = UserFactory(username="other")
        subscription = NotificationSubscription.objects.create(
            user=other, sphere=sphere, source="visit"
        )

        assert (
            repo.set_muted(user_id=active_user.pk, pk=subscription.pk, muted=True)
            is False
        )
        subscription.refresh_from_db()
        assert subscription.muted is False
