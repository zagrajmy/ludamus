from datetime import UTC, datetime

import pytest
from django.utils import translation

from ludamus.links.db.django.models import Notification, Session, SphereSubscription
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.db.django.recipients import (
    AccountReader,
    NotSpeakingError,
    Recipient,
    Voice,
    speaking_to,
)
from ludamus.pacts.chronology import (
    AnonymousProposalAcceptedNotification,
    ProposalAcceptedNotification,
)
from ludamus.pacts.crowd import (
    AgeBand,
    EmailChangeCompletedNotification,
    EmailChangeRequestedNotification,
    EmailVerificationNotification,
)
from ludamus.pacts.dashboard import SphereEventPublishedNotification
from ludamus.pacts.enrollment import OfferNotification, PromotionNotification
from ludamus.pacts.listing import (
    ListingDeclinedNotification,
    ListingInterestedNotification,
    ListingNotification,
)
from ludamus.pacts.party import (
    HeldSeatNotification,
    PartyEnrolledNotification,
    PartyInviteNotification,
)
from ludamus.pacts.printing import PrintablesReadyNotification
from ludamus.pacts.safety import ShadowbanSignupNotification
from tests.integration.conftest import SessionFactory, UserFactory

_EXPIRES = datetime(2031, 5, 1, 17, 0, tzinfo=UTC)
_NOTIFY = sorted(
    name for name in vars(DjangoUserNotifier) if name.startswith("notify_")
)


def _sample(method, *, session, subscription, language):
    user_id = session.presenter_id
    email = session.presenter.email
    seat = {
        "recipient_user_id": user_id,
        "session_id": session.pk,
        "session_title": session.title,
        "event_slug": session.event.slug,
    }
    listing = {"recipient_user_id": user_id, "listing_id": 7, "listing_title": "Dune"}
    acceptance = {
        "session_id": session.pk,
        "session_title": session.title,
        "event_name": session.event.name,
        "event_slug": session.event.slug,
        "placed": False,
    }
    event = {
        "event_name": session.event.name,
        "event_slug": session.event.slug,
        "sphere_domain": "con.example.net",
    }
    held = seat | {"claim_token": "tok", "offer_expires_at": _EXPIRES}
    samples = {
        "notify_promoted": lambda: PromotionNotification(**seat),
        "notify_offered": lambda: OfferNotification(**held),
        "notify_offer_expired": lambda: PromotionNotification(**seat),
        "notify_party_invited": lambda: PartyInviteNotification(
            recipient_user_id=user_id, party_name="", actor_name="Kasia"
        ),
        "notify_party_enrolled": lambda: PartyEnrolledNotification(
            **seat, actor_name="Kasia"
        ),
        "notify_seat_held": lambda: HeldSeatNotification(
            **{k: v for k, v in held.items() if k != "event_slug"}, actor_name="Kasia"
        ),
        "notify_email_verification": lambda: EmailVerificationNotification(
            recipient_user_id=user_id, recipient_email=email, token="tok"
        ),
        "notify_email_change_requested": lambda: EmailChangeRequestedNotification(
            recipient_user_id=user_id,
            recipient_email=email,
            new_address="new@example.com",
            cancel_token="tok",
        ),
        "notify_email_change_completed": lambda: EmailChangeCompletedNotification(
            recipient_user_id=user_id,
            recipient_email=email,
            new_address="new@example.com",
        ),
        "notify_printables_ready": lambda: PrintablesReadyNotification(
            recipient_user_id=user_id, **event
        ),
        "notify_listing_interested": lambda: ListingInterestedNotification(
            **listing, responder_name="Kasia", message=""
        ),
        "notify_listing_declined": lambda: ListingDeclinedNotification(
            **listing, message=""
        ),
        "notify_listing_not_chosen": lambda: ListingNotification(**listing),
        "notify_listing_changed": lambda: ListingNotification(**listing),
        "notify_sphere_event_published": lambda: SphereEventPublishedNotification(
            subscription_id=subscription.pk,
            recipient_user_id=user_id,
            recipient_email=email,
            sphere_name="Skytower",
            unsubscribe_token="tok",
            **event,
        ),
        "notify_proposal_accepted": lambda: ProposalAcceptedNotification(
            **acceptance, recipient_user_id=user_id
        ),
        "notify_anonymous_proposal_accepted": lambda: (
            AnonymousProposalAcceptedNotification(
                **acceptance, contact_email="guest@example.com", language=language
            )
        ),
        "notify_shadowbanned_signup": lambda: ShadowbanSignupNotification(
            recipient_user_id=user_id,
            session_title=session.title,
            player_names=["Bob"],
            session_player_names=["Bob"],
            **event,
        ),
    }
    if method not in samples:
        pytest.fail(f"Add a sample for DjangoUserNotifier.{method}")
    return samples[method]()


@pytest.mark.usefixtures("polish_catalog")
@pytest.mark.parametrize("method", _NOTIFY)
def test_every_notification_speaks_its_readers_language_whoever_sends_it(
    method, mailoutbox, django_capture_on_commit_callbacks
):
    reader = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    session = SessionFactory(presenter=reader)
    subscription = SphereSubscription.objects.create(
        sphere=session.event.sphere, user=reader
    )

    def delivered(*, reader_language, sender_language):
        reader.language = reader_language
        reader.save(update_fields=["language"])
        Notification.objects.all().delete()
        Session.objects.filter(pk=session.pk).update(acceptance_mailed_at=None)
        mailoutbox.clear()
        notification = _sample(
            method, session=session, subscription=subscription, language=reader_language
        )
        with (
            translation.override(sender_language),
            django_capture_on_commit_callbacks(execute=True),
        ):
            getattr(DjangoUserNotifier(), method)(notification)
        return (
            list(Notification.objects.values_list("title", "body", "url")),
            [(mail.subject, mail.body, mail.to) for mail in mailoutbox],
        )

    polish = delivered(reader_language="pl", sender_language="en")

    assert polish != ([], [])
    assert delivered(reader_language="pl", sender_language="pl") == polish
    assert delivered(reader_language="en", sender_language="pl") != polish


class TestRecipient:
    reader = AccountReader(user_id=1, language="pl", deliverable_email="o@example.com")

    def test_confirms_its_reader_while_speaking_their_language(self):
        with speaking_to(self.reader) as recipient:
            assert recipient.confirm() == self.reader

    def test_refuses_delivery_once_its_block_has_ended(self):
        with speaking_to(self.reader) as recipient:
            pass

        with pytest.raises(NotSpeakingError, match="outside a speaking block"):
            recipient.confirm()

    def test_refuses_delivery_while_another_language_has_taken_over(self):
        with (
            speaking_to(self.reader) as recipient,
            translation.override("en"),
            pytest.raises(NotSpeakingError, match="in en to a pl reader"),
        ):
            recipient.confirm()

    def test_one_made_outside_speaking_to_never_delivers(self):
        with (
            translation.override("pl"),
            pytest.raises(NotSpeakingError, match="outside a speaking block"),
        ):
            Recipient(self.reader, Voice("pl")).confirm()
