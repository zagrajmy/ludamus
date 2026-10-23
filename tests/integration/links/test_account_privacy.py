from ludamus.links.db.django.models import Notification, User
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.pacts.party import PartyInviteNotification


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
