import pytest

from ludamus.links.db.django.models import NotificationSubscription
from ludamus.links.db.django.notifications import NotificationSubscriptionRepository
from ludamus.pacts.notifications import SubscriptionDTO, SubscriptionSource
from tests.integration.conftest import SphereFactory, UserFactory

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


class TestListForUser:
    def test_maps_own_rows_sorted_by_sphere_name(self, repo, active_user, sphere):
        sphere.name = "beta"
        sphere.save(update_fields=["name"])
        other_sphere = SphereFactory(name="Alpha")
        beta_sub = NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, muted=True, source="visit"
        )
        alpha_sub = NotificationSubscription.objects.create(
            user=active_user, sphere=other_sphere, source="visit"
        )
        NotificationSubscription.objects.create(
            user=UserFactory(username="other"), sphere=sphere, source="visit"
        )

        result = repo.list_for_user(active_user.pk)

        assert result == [
            SubscriptionDTO(pk=alpha_sub.pk, muted=False, sphere_name="Alpha"),
            SubscriptionDTO(pk=beta_sub.pk, muted=True, sphere_name="beta"),
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
