from datetime import UTC, datetime, timedelta

from django.core import mail
from django.test import override_settings

from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.pacts.enrollment import OfferNotification
from ludamus.pacts.party import PartyInviteNotification
from tests.integration.conftest import EventFactory, SessionFactory, SphereFactory


def _offer(session, *, email):
    return OfferNotification(
        recipient_user_id=session.presenter_id,
        recipient_email=email,
        session_id=session.pk,
        session_title=session.title,
        event_slug=session.event.slug,
        claim_token="tok-123",
        offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


class TestOfferEmailLink:
    def test_link_uses_the_session_sphere_domain(
        self, django_capture_on_commit_callbacks
    ):
        sphere = SphereFactory(site__domain="skytower.example.net")
        session = SessionFactory(event=EventFactory(sphere=sphere))

        with django_capture_on_commit_callbacks(execute=True):
            DjangoUserNotifier().notify_offered(
                _offer(session, email="waiter@example.com")
            )

        assert (
            "https://skytower.example.net/offer/tok-123/claim/" in mail.outbox[0].body
        )

    @override_settings(ROOT_DOMAIN="zagrajmy.example.net")
    def test_link_falls_back_to_the_root_domain(
        self, django_capture_on_commit_callbacks, active_user
    ):
        with django_capture_on_commit_callbacks(execute=True):
            DjangoUserNotifier().notify_party_invited(
                PartyInviteNotification(
                    recipient_user_id=active_user.pk,
                    recipient_email="invitee@example.com",
                    actor_name="Kobold",
                    party_name="Drużyna",
                )
            )

        assert "https://zagrajmy.example.net/" in mail.outbox[0].body
