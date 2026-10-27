import pytest
from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.models import Notification, SphereSubscription, User
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.unsubscribe_tokens import DjangoSphereUnsubscribeTokenCodec
from ludamus.pacts.crowd import AgeBand
from ludamus.pacts.dashboard import (
    SphereEventPublishedNotification,
    SphereUnsubscribeTokenPayload,
)
from ludamus.pacts.party import PartyInviteNotification
from tests.integration.conftest import UserFactory


@pytest.fixture(name="subscription")
def _subscription(sixteen_plus_user, non_root_sphere):
    Services().sphere_subscriptions.subscribe(
        sphere_id=non_root_sphere.pk, user_id=sixteen_plus_user.pk
    )
    return SphereSubscription.objects.select_related("user", "sphere").get(
        user=sixteen_plus_user, sphere=non_root_sphere
    )


def _promotion(subscription):
    return SphereEventPublishedNotification(
        subscription_id=subscription.pk,
        recipient_user_id=subscription.user_id,
        recipient_email=subscription.user.email,
        event_name="Family Convention",
        event_slug="family-convention",
        sphere_name=subscription.sphere.name,
        sphere_domain="testserver",
        unsubscribe_token=DjangoSphereUnsubscribeTokenCodec.dumps(
            SphereUnsubscribeTokenPayload(
                user_id=subscription.user_id,
                sphere_id=subscription.sphere_id,
                sphere_name=subscription.sphere.name,
            )
        ),
    )


def _reset_age(user):
    service = Services().crowd_auth
    service.confirm_age(user_slug=user.slug, age_band=AgeBand.THIRTEEN_TO_FIFTEEN)
    service.confirm_age(user_slug=user.slug, age_band=AgeBand.SIXTEEN_PLUS)


@pytest.mark.parametrize("age_band", (AgeBand.UNKNOWN, AgeBand.THIRTEEN_TO_FIFTEEN))
def test_marketing_notifier_cannot_bypass_current_age(
    *, subscription, mailoutbox, django_capture_on_commit_callbacks, age_band
):
    promotion = _promotion(subscription)
    User.objects.filter(pk=subscription.user_id).update(age_band=age_band)

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(promotion)

    assert mailoutbox == []
    assert not Notification.objects.filter(recipient_id=subscription.user_id).exists()


@pytest.mark.parametrize("resubscribe", (False, True))
def test_snapshot_does_not_survive_age_reset(
    *, subscription, mailoutbox, django_capture_on_commit_callbacks, resubscribe
):
    promotion = _promotion(subscription)
    _reset_age(subscription.user)
    if resubscribe:
        Services().sphere_subscriptions.subscribe(
            sphere_id=subscription.sphere_id, user_id=subscription.user_id
        )

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(promotion)

    assert mailoutbox == []
    assert not Notification.objects.filter(recipient_id=subscription.user_id).exists()


@pytest.mark.parametrize("resubscribe", (False, True))
def test_snapshot_does_not_survive_signed_link_withdrawal(
    *, subscription, client, mailoutbox, django_capture_on_commit_callbacks, resubscribe
):
    promotion = _promotion(subscription)
    client.post(
        reverse(
            "web:email-unsubscribe-confirm",
            kwargs={"token": promotion.unsubscribe_token},
        ),
        {"List-Unsubscribe": "One-Click"},
    )
    assert not SphereSubscription.objects.filter(pk=subscription.pk).exists()
    if resubscribe:
        Services().sphere_subscriptions.subscribe(
            sphere_id=subscription.sphere_id, user_id=subscription.user_id
        )

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(promotion)

    assert mailoutbox == []
    assert not Notification.objects.filter(recipient_id=subscription.user_id).exists()


@pytest.mark.parametrize("age_band", (AgeBand.UNKNOWN, AgeBand.THIRTEEN_TO_FIFTEEN))
def test_queued_marketing_rechecks_current_age_before_sending(
    *, subscription, mailoutbox, django_capture_on_commit_callbacks, age_band
):
    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(_promotion(subscription))
        User.objects.filter(pk=subscription.user_id).update(age_band=age_band)

    assert mailoutbox == []
    assert Notification.objects.filter(recipient_id=subscription.user_id).count() == 1


@pytest.mark.parametrize("resubscribe", (False, True))
def test_queued_marketing_does_not_survive_age_reset(
    *, subscription, mailoutbox, django_capture_on_commit_callbacks, resubscribe
):
    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(_promotion(subscription))
        _reset_age(subscription.user)
        if resubscribe:
            Services().sphere_subscriptions.subscribe(
                sphere_id=subscription.sphere_id, user_id=subscription.user_id
            )

    assert mailoutbox == []
    assert Notification.objects.filter(recipient_id=subscription.user_id).count() == 1


@pytest.mark.parametrize("resubscribe", (False, True))
def test_queued_marketing_does_not_survive_signed_link_withdrawal(
    *, subscription, client, mailoutbox, django_capture_on_commit_callbacks, resubscribe
):
    promotion = _promotion(subscription)
    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(promotion)
        client.post(
            reverse(
                "web:email-unsubscribe-confirm",
                kwargs={"token": promotion.unsubscribe_token},
            ),
            {"List-Unsubscribe": "One-Click"},
        )
        assert not SphereSubscription.objects.filter(pk=subscription.pk).exists()
        if resubscribe:
            Services().sphere_subscriptions.subscribe(
                sphere_id=subscription.sphere_id, user_id=subscription.user_id
            )

    assert mailoutbox == []
    assert Notification.objects.filter(recipient_id=subscription.user_id).count() == 1


def test_foreign_subscription_cannot_authorize_marketing(
    *, subscription, mailoutbox, django_capture_on_commit_callbacks
):
    recipient = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    promotion = _promotion(subscription).model_copy(
        update={"recipient_user_id": recipient.pk, "recipient_email": recipient.email}
    )

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(promotion)

    assert mailoutbox == []
    assert not Notification.objects.filter(recipient=recipient).exists()


def test_changed_subscription_owner_revokes_queued_marketing(
    *, subscription, mailoutbox, django_capture_on_commit_callbacks
):
    other_user = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(_promotion(subscription))
        SphereSubscription.objects.filter(pk=subscription.pk).update(user=other_user)

    assert mailoutbox == []
    assert Notification.objects.filter(recipient_id=subscription.user_id).count() == 1


def test_young_account_still_receives_service_notifications(
    *, active_user, mailoutbox, django_capture_on_commit_callbacks
):
    User.objects.filter(pk=active_user.pk).update(age_band=AgeBand.THIRTEEN_TO_FIFTEEN)

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_party_invited(
            PartyInviteNotification(
                recipient_user_id=active_user.pk,
                actor_name="A friend",
                party_name="Convention crew",
            )
        )

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [active_user.email]
    assert "List-Unsubscribe" not in mailoutbox[0].extra_headers
    assert Notification.objects.filter(recipient=active_user).exists()
