import pytest

from ludamus.links.db.django.models import Notification, User
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.pacts.dashboard import SphereEventPublishedNotification
from ludamus.pacts.party import PartyInviteNotification


def _promotion(user):
    return SphereEventPublishedNotification(
        recipient_user_id=user.pk,
        recipient_email=user.email,
        event_name="Family Convention",
        event_slug="family-convention",
        sphere_name="Family Games",
        sphere_domain="testserver",
        unsubscribe_token="signed-unsubscribe-link",
    )


@pytest.mark.parametrize("age_band", ("unknown", "13_15"))
def test_marketing_notifier_cannot_bypass_account_policy(
    active_user, mailoutbox, django_capture_on_commit_callbacks, age_band
):
    User.objects.filter(pk=active_user.pk).update(age_band=age_band)

    with django_capture_on_commit_callbacks(execute=True):
        DjangoUserNotifier().notify_sphere_event_published(_promotion(active_user))

    assert mailoutbox == []
    assert not Notification.objects.filter(recipient=active_user).exists()


def test_queued_marketing_rechecks_eligibility_before_sending(
    active_user, mailoutbox, django_capture_on_commit_callbacks
):
    User.objects.filter(pk=active_user.pk).update(age_band="16_plus")

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        DjangoUserNotifier().notify_sphere_event_published(_promotion(active_user))
        User.objects.filter(pk=active_user.pk).update(age_band="13_15")
    for callback in callbacks:
        callback()

    assert len(callbacks) == 1
    assert mailoutbox == []


def test_young_account_still_receives_service_notifications(
    active_user, mailoutbox, django_capture_on_commit_callbacks
):
    User.objects.filter(pk=active_user.pk).update(age_band="13_15")

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
