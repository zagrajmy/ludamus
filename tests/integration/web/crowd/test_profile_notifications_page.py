from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import NotificationSubscription
from ludamus.pacts.notifications import SubscriptionDTO, SubscriptionGroupDTO
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:crowd:profile-notifications")


def _dto(subscription: NotificationSubscription) -> SubscriptionDTO:
    sphere = subscription.sphere or subscription.event.sphere
    return SubscriptionDTO(
        pk=subscription.pk,
        muted=subscription.muted,
        sphere_id=subscription.sphere_id,
        event_id=subscription.event_id,
        label=(
            subscription.sphere.name if subscription.sphere else subscription.event.name
        ),
        parent_sphere_id=sphere.pk,
        parent_sphere_name=sphere.name,
    )


def _visit_subscription(user, sphere) -> NotificationSubscription:
    # The row the visit middleware creates for the requesting user; every
    # authenticated request to the root domain carries it.
    return NotificationSubscription.objects.get(user=user, sphere=sphere)


class TestProfileNotificationsPageView:
    def test_unauthenticated_redirects(self, client):
        response = client.get(URL)

        assert response.status_code == HTTPStatus.FOUND

    def test_get_lists_own_visit_subscription(
        self, authenticated_client, active_user, sphere
    ):
        response = authenticated_client.get(URL)

        subscription = _visit_subscription(active_user, sphere)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "subscription_groups": [
                    SubscriptionGroupDTO(
                        sphere_name=sphere.name,
                        sphere_subscription=_dto(subscription),
                        events=[],
                    )
                ],
                "profile_active_tab": "notifications",
            },
            template_name="crowd/user/notifications.html",
        )

    def test_get_groups_events_under_sphere(
        self, authenticated_client, active_user, sphere
    ):
        event = EventFactory(sphere=sphere)
        event_sub = NotificationSubscription.objects.create(
            user=active_user, event=event, source="enrollment"
        )

        response = authenticated_client.get(URL)

        sphere_sub = _visit_subscription(active_user, sphere)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "subscription_groups": [
                    SubscriptionGroupDTO(
                        sphere_name=sphere.name,
                        sphere_subscription=_dto(sphere_sub),
                        events=[_dto(event_sub)],
                    )
                ],
                "profile_active_tab": "notifications",
            },
            template_name="crowd/user/notifications.html",
        )

    def test_get_empty_after_subscriptions_removed(
        self, authenticated_client, active_user
    ):
        # First visit subscribes and stamps the session flag; once the rows are
        # gone the flagged session must not resubscribe, so the tab goes empty.
        authenticated_client.get(URL)
        NotificationSubscription.objects.all().delete()

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "subscription_groups": [],
                "profile_active_tab": "notifications",
            },
            template_name="crowd/user/notifications.html",
        )


class TestProfileNotificationsMuteActionView:
    @staticmethod
    def _mute_url(pk: int) -> str:
        return reverse("web:crowd:profile-notifications-mute", kwargs={"pk": pk})

    def test_mutes_own_subscription(self, authenticated_client, active_user, sphere):
        subscription = NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, source="visit"
        )

        response = authenticated_client.post(
            self._mute_url(subscription.pk), data={"muted": "true"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Subscription muted.")],
            url=URL,
        )
        subscription.refresh_from_db()
        assert subscription.muted is True

    def test_unmutes_own_subscription(self, authenticated_client, active_user, sphere):
        subscription = NotificationSubscription.objects.create(
            user=active_user, sphere=sphere, muted=True, source="visit"
        )

        response = authenticated_client.post(
            self._mute_url(subscription.pk), data={"muted": "false"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Subscription unmuted.")],
            url=URL,
        )
        subscription.refresh_from_db()
        assert subscription.muted is False

    def test_foreign_subscription_404s_without_side_effects(
        self, authenticated_client, sphere
    ):
        other = UserFactory(username="other")
        subscription = NotificationSubscription.objects.create(
            user=other, sphere=sphere, source="visit"
        )

        response = authenticated_client.post(
            self._mute_url(subscription.pk), data={"muted": "true"}
        )

        assert_response_404(response)
        subscription.refresh_from_db()
        assert subscription.muted is False
