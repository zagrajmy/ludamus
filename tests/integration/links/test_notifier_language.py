from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from django.utils import translation

from ludamus.links.db.django import notifications
from ludamus.links.db.django.delivery import compose_mail
from ludamus.links.db.django.models import (
    Notification,
    Session,
    SphereSubscription,
    User,
)
from ludamus.links.db.django.recipients import (
    NoAddressError,
    NotSpeakingError,
    Voice,
    speaking_to,
)
from ludamus.links.db.django.users import ClaimRepository
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
from ludamus.pacts.sessions import (
    AnonymousProposalAcceptedNotification,
    ProposalAcceptedNotification,
)
from ludamus.pacts.user import (
    AgeBand,
    EmailChangeCompletedNotification,
    EmailChangeRequestedNotification,
    EmailVerificationNotification,
    UserType,
)
from tests.integration.conftest import SessionFactory, UserFactory

_EXPIRES = datetime(2031, 5, 1, 17, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Reader:
    session: Session
    subscription: SphereSubscription
    language: str

    @property
    def user_id(self):
        return self.session.presenter_id

    @property
    def seat(self):
        return {
            "recipient_user_id": self.user_id,
            "session_id": self.session.pk,
            "session_title": self.session.title,
            "event_slug": self.session.event.slug,
        }

    @property
    def held_seat(self):
        return {
            "recipient_user_id": self.user_id,
            "session_id": self.session.pk,
            "session_title": self.session.title,
            "claim_token": "tok",
            "offer_expires_at": _EXPIRES,
        }

    @property
    def held(self):
        return self.held_seat | {"event_slug": self.session.event.slug}

    @property
    def listing(self):
        return {
            "recipient_user_id": self.user_id,
            "listing_id": 7,
            "listing_title": "Dune",
        }

    @property
    def event(self):
        return {
            "event_name": self.session.event.name,
            "event_slug": self.session.event.slug,
            "sphere_domain": "con.example.net",
        }

    def acceptance(self, *, placed):
        return {
            "session_id": self.session.pk,
            "session_title": self.session.title,
            "event_name": self.session.event.name,
            "event_slug": self.session.event.slug,
            "placed": placed,
        }

    @property
    def email_change(self):
        return {
            "recipient_user_id": self.user_id,
            "recipient_email": self.session.presenter.email,
            "new_address": "new@example.com",
        }

    def shadowban(self, *, at_their_table, elsewhere):
        return ShadowbanSignupNotification(
            recipient_user_id=self.user_id,
            session_title=self.session.title,
            session_player_names=at_their_table,
            player_names=elsewhere,
            **self.event,
        )


# One sample per branch that changes the copy a reader gets.
_SAMPLES = {
    "notify_promoted": [lambda r: PromotionNotification(**r.seat)],
    "notify_offered": [lambda r: OfferNotification(**r.held)],
    "notify_offer_expired": [lambda r: PromotionNotification(**r.seat)],
    "notify_party_invited": [
        lambda r, party=party: PartyInviteNotification(
            recipient_user_id=r.user_id, party_name=party, actor_name="Kasia"
        )
        for party in ("", "Smoki")
    ],
    "notify_party_enrolled": [
        lambda r: PartyEnrolledNotification(**r.seat, actor_name="Kasia")
    ],
    "notify_seat_held": [
        lambda r: HeldSeatNotification(**r.held_seat, actor_name="Kasia")
    ],
    "notify_email_verification": [
        lambda r: EmailVerificationNotification(
            recipient_user_id=r.user_id,
            recipient_email=r.session.presenter.email,
            token="tok",
        )
    ],
    "notify_email_change_requested": [
        lambda r: EmailChangeRequestedNotification(**r.email_change, cancel_token="tok")
    ],
    "notify_email_change_completed": [
        lambda r: EmailChangeCompletedNotification(**r.email_change)
    ],
    "notify_printables_ready": [
        lambda r: PrintablesReadyNotification(recipient_user_id=r.user_id, **r.event)
    ],
    "notify_listing_interested": [
        lambda r: ListingInterestedNotification(
            **r.listing, responder_name="Kasia", message=""
        )
    ],
    "notify_listing_declined": [
        lambda r, message=message: ListingDeclinedNotification(
            **r.listing, message=message
        )
        for message in ("", "Może następnym razem!")
    ],
    "notify_listing_not_chosen": [lambda r: ListingNotification(**r.listing)],
    "notify_listing_changed": [lambda r: ListingNotification(**r.listing)],
    "notify_sphere_event_published": [
        lambda r: SphereEventPublishedNotification(
            subscription_id=r.subscription.pk,
            recipient_user_id=r.user_id,
            sphere_name="Skytower",
            unsubscribe_token="tok",
            **r.event,
        )
    ],
    "notify_proposal_accepted": [
        lambda r, placed=placed: ProposalAcceptedNotification(
            **r.acceptance(placed=placed), recipient_user_id=r.user_id
        )
        for placed in (False, True)
    ],
    "notify_anonymous_proposal_accepted": [
        lambda r, placed=placed: AnonymousProposalAcceptedNotification(
            **r.acceptance(placed=placed),
            contact_email="guest@example.com",
            language=r.language,
        )
        for placed in (False, True)
    ],
    "notify_shadowbanned_signup": [
        lambda r: r.shadowban(at_their_table=["Bob"], elsewhere=["Bob"]),
        lambda r: r.shadowban(at_their_table=[], elsewhere=["Bob"]),
        lambda r: r.shadowban(at_their_table=["Bob"], elsewhere=[]),
    ],
}


def _unsampled(method):
    def fail(_reader):
        pytest.fail(f"Add a sample for {method}")

    return [fail]


_NOTIFIERS = [
    pytest.param(notifier, method, sample, id=f"{notifier.__name__}.{method}-{index}")
    for notifier in vars(notifications).values()
    if isinstance(notifier, type) and notifier.__module__ == notifications.__name__
    for method in sorted(vars(notifier))
    if method.startswith("notify_")
    for index, sample in enumerate(_SAMPLES.get(method) or _unsampled(method))
]


def test_every_sample_names_a_notifier():
    assert set(_SAMPLES) <= {param.values[1] for param in _NOTIFIERS}


@pytest.mark.usefixtures("polish_catalog")
@pytest.mark.parametrize(
    "email_verified", (True, False), ids=("verified", "unverified")
)
@pytest.mark.parametrize(("notifier", "method", "sample"), _NOTIFIERS)
def test_every_notification_speaks_its_readers_language_whoever_sends_it(
    notifier,
    method,
    sample,
    email_verified,
    mailoutbox,
    django_capture_on_commit_callbacks,
):
    reader = UserFactory(age_band=AgeBand.SIXTEEN_PLUS, email_verified=email_verified)
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
        notification = sample(_Reader(session, subscription, reader_language))
        with (
            translation.override(sender_language),
            django_capture_on_commit_callbacks(execute=True),
        ):
            getattr(notifier(), method)(notification)
        return (
            list(Notification.objects.values_list("title", "body", "url")),
            [(mail.subject, mail.body, mail.to) for mail in mailoutbox],
        )

    polish = delivered(reader_language="pl", sender_language="en")
    english = delivered(reader_language="en", sender_language="pl")

    assert polish != ([], [])
    assert polish != english
    assert delivered(reader_language="pl", sender_language="pl") == polish
    assert delivered(reader_language="en", sender_language="en") == english
    if not email_verified and not method.startswith("notify_email_"):
        assert all(reader.email not in to for *_, to in polish[1] + english[1])


class TestRecipient:
    def test_speaks_the_accounts_stored_language(self):
        user = UserFactory(language="pl")

        with speaking_to(user.pk) as recipient:
            recipient.confirm()
            assert translation.get_language() == "pl"
            assert recipient.mail_to() == user.email

    def test_an_account_never_seen_reads_english_whatever_the_site_default(
        self, settings
    ):
        settings.LANGUAGE_CODE = "pl"
        user = UserFactory(language="")

        with speaking_to(user.pk):
            assert translation.get_language() == "en"

    def test_an_account_gone_before_delivery_reads_english_and_is_not_mailed(
        self, settings
    ):
        settings.LANGUAGE_CODE = "pl"
        user = UserFactory(language="pl")
        user_id = user.pk
        user.delete()

        with speaking_to(user_id) as recipient:
            assert translation.get_language() == "en"
            assert not recipient.can_mail

    def test_a_companion_reads_its_managers_language(self):
        manager = UserFactory(language="pl")
        companion = UserFactory(
            user_type=UserType.CONNECTED, manager=manager, language=""
        )

        with speaking_to(companion.pk):
            assert translation.get_language() == "pl"

    def test_a_claimed_companion_reads_its_own_language(self):
        companion = UserFactory(
            user_type=UserType.CONNECTED,
            manager=UserFactory(language="en"),
            claim_token="tok",
        )
        ClaimRepository.convert(token="tok", username="ola")
        User.objects.filter(pk=companion.pk).update(language="pl")

        with speaking_to(companion.pk):
            assert translation.get_language() == "pl"

    def test_an_unproven_address_is_never_mailed(self):
        user = UserFactory(language="pl", email_verified=False)

        with speaking_to(user.pk) as recipient:
            assert not recipient.can_mail
            with pytest.raises(NoAddressError):
                compose_mail(recipient, subject="Hej", body="Treść")

    def test_refuses_delivery_once_its_block_has_ended(self):
        with speaking_to(UserFactory(language="pl").pk) as recipient:
            pass

        with pytest.raises(NotSpeakingError, match="outside a speaking block"):
            recipient.confirm()

    def test_refuses_delivery_while_another_language_has_taken_over(self):
        with (
            speaking_to(UserFactory(language="pl").pk) as recipient,
            translation.override("en"),
            pytest.raises(NotSpeakingError, match="in en to a pl reader"),
        ):
            recipient.confirm()


class TestVoice:
    def test_holds_one_block_at_a_time(self):
        voice = Voice("pl", address="guest@example.com")

        with voice, pytest.raises(RuntimeError, match="one block at a time"), voice:
            pass

    def test_hands_over_its_address_only_inside_its_block(self):
        voice = Voice("pl", address="guest@example.com")

        with voice:
            assert voice.mail_to() == "guest@example.com"
        with pytest.raises(NotSpeakingError):
            voice.mail_to()
