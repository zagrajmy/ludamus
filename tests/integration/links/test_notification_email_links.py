from datetime import UTC, datetime, timedelta

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.pacts.enrollment import OfferNotification
from ludamus.pacts.party import PartyInviteNotification
from ludamus.pacts.safety import ShadowbanSignupNotification
from tests.integration.conftest import EventFactory, SessionFactory, SphereFactory


def _mailed_link():
    return mail.outbox[0].body.rsplit("\n\n", 1)[1]


class TestEmailLink:
    def test_offer_link_uses_the_session_sphere_domain(
        self, django_capture_on_commit_callbacks
    ):
        sphere = SphereFactory(site__domain="skytower.example.net")
        session = SessionFactory(event=EventFactory(sphere=sphere))

        with django_capture_on_commit_callbacks(execute=True):
            DjangoUserNotifier().notify_offered(
                OfferNotification(
                    recipient_user_id=session.presenter_id,
                    recipient_email="waiter@example.com",
                    session_id=session.pk,
                    session_title=session.title,
                    event_slug=session.event.slug,
                    claim_token="tok-123",
                    offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )

        path = reverse("web:chronology:offer-claim", kwargs={"token": "tok-123"})
        assert _mailed_link() == f"https://skytower.example.net{path}"

    def test_link_prefers_the_domain_the_notification_carries(
        self, django_capture_on_commit_callbacks, active_user
    ):
        with django_capture_on_commit_callbacks(execute=True):
            DjangoUserNotifier().notify_shadowbanned_signup(
                ShadowbanSignupNotification(
                    recipient_user_id=active_user.pk,
                    recipient_email="organizer@example.com",
                    event_slug="con-2026",
                    event_name="Con 2026",
                    session_title="Deniable Game",
                    sphere_domain="con.example.net",
                    player_names=["Banned Bob"],
                    session_player_names=[],
                )
            )

        path = reverse("web:chronology:event", kwargs={"slug": "con-2026"})
        assert _mailed_link() == f"https://con.example.net{path}"

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

        path = reverse("web:crowd:profile-parties")
        assert _mailed_link() == f"https://zagrajmy.example.net{path}"
