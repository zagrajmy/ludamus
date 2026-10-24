"""After Checkout: the order page, and claiming the order into an account.

How it could go wrong: a claimed order is shown to someone with its link, or
claimed away from its holder; a forwarded order link hands the order to an
account that never proved it reads the order's address; a mail server refusing
the confirmation reads as sent, or holds the next ask back; a mailed
confirmation link works for another account, after it expired, or tampered
with; a refunded
or abandoned order offers to be kept; an order reference from another event is
shown or claimed.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from smtplib import SMTPServerDisconnected
from urllib.parse import urlencode, urlparse

import pytest
from django.contrib import messages
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import resolve, reverse
from freezegun import freeze_time

from ludamus.links.db.django.models import Ticket
from ludamus.links.order_claim_tokens import DjangoOrderClaimCodec
from ludamus.pacts import EventDTO
from ludamus.pacts.tickets import (
    CLAIM_MAIL_INTERVAL,
    ORDER_CLAIM_LINK_MAX_AGE,
    OrderClaimPayload,
    OrderPageState,
    OrderStatus,
    TicketDTO,
)
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.stripe_helpers import GUEST_CLIENT, order, order_url, ticket_type
from tests.integration.utils import (
    AttributesMatcher,
    assert_response,
    assert_response_404,
)

pytestmark = pytest.mark.usefixtures("stripe_settings")

GUEST_EMAIL = "guest@example.com"
CLAIMED = (
    messages.SUCCESS,
    "The tickets are in your account. They're under My tickets.",
)
# Orders that bring no tickets: nothing in them is worth keeping.
SPENT = (
    pytest.param(OrderStatus.REFUNDED, id="refunded"),
    pytest.param(OrderStatus.FAILED, id="failed"),
    pytest.param(OrderStatus.EXPIRED, id="expired"),
)
LINK_INVALID = (
    messages.ERROR,
    (
        "This link has expired or was sent for another account. Ask for a new"
        " one from the order page."
    ),
)


def _claim_url(event, placed):
    return reverse(
        "web:event:event-ticket-order-claim",
        kwargs={"event_slug": event.slug, "reference": placed.reference},
    )


def _confirm_url(event, placed, token):
    return reverse(
        "web:event:event-ticket-order-claim-confirm",
        kwargs={
            "event_slug": event.slug,
            "reference": placed.reference,
            "token": token,
        },
    )


def _token(placed, user):
    return DjangoOrderClaimCodec.dumps(
        OrderClaimPayload(order_pk=placed.pk, user_id=user.pk)
    )


def _login_redirect(next_path):
    # Django's redirect_to_login keeps slashes, and escapes a token's colons.
    return f"/crowd/login-required/?{urlencode({'next': next_path}, safe='/')}"


def _sign_in_url(next_path, **extra):
    # Slashes kept, so analytics redaction finds the reference inside `next`.
    query = urlencode({"next": next_path, **extra}, safe="/")
    return f"{reverse('web:crowd:auth0:login')}?{query}"


def _order_page_context(event, placed, *, order_matcher, state, claimable):
    here = order_url(event, placed)
    return {
        "event": EventDTO.model_validate(event),
        "order": order_matcher,
        "state": state,
        "claimable": claimable,
        "sign_in_url": _sign_in_url(here),
        "sign_up_url": _sign_in_url(here, screen_hint="signup"),
    }


def _confirm_link(mail):
    url = next(part for part in mail.body.split("\n\n") if part.startswith("https://"))
    return resolve(urlparse(url).path)


def _link_sent(email):
    return (
        messages.INFO,
        (
            f"These tickets were bought with {email}. We've sent a link there:"
            " open it while signed in to this account to add them."
        ),
    )


def _awaiting_transfer(event, *, email=GUEST_EMAIL):
    # Still holding seats, so it still holds the guest's network too.
    return order(
        event,
        buyer=None,
        lines=[(ticket_type(event), 1)],
        status=OrderStatus.AWAITING_PAYMENT,
        email=email,
        guest_client=GUEST_CLIENT,
    )


def _holders(placed):
    placed.refresh_from_db()
    return placed.buyer_id, set(placed.tickets.values_list("holder_id", flat=True))


def _guest_order_with_tickets(event, *, email=GUEST_EMAIL):
    kind = ticket_type(event)
    guests = order(event, buyer=None, lines=[(kind, 2)], status="paid", email=email)
    Ticket.objects.create(order=guests, ticket_type=kind, code="GUEST22222")
    Ticket.objects.create(order=guests, ticket_type=kind, code="GUEST33333")
    return guests


class TestEventTicketOrderPage:
    def test_guest_order_is_open_to_whoever_has_its_link(self, client, event):
        kind = ticket_type(event)
        guests = order(
            event, buyer=None, lines=[(kind, 1)], status="paid", email=GUEST_EMAIL
        )
        ticket = Ticket.objects.create(
            order=guests, ticket_type=kind, code="GUEST22222"
        )

        response = client.get(order_url(event, guests))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                guests,
                order_matcher=AttributesMatcher(
                    pk=guests.pk,
                    buyer_id=None,
                    status=OrderStatus.PAID,
                    tickets=[
                        TicketDTO(
                            pk=ticket.pk,
                            code="GUEST22222",
                            ticket_type_name="Weekend pass",
                        )
                    ],
                ),
                state=OrderPageState.PAID,
                claimable=True,
            ),
        )

    def test_signed_in_visitor_may_claim_a_guest_order(
        self, authenticated_client, event
    ):
        guests = order(
            event, buyer=None, lines=[(ticket_type(event), 1)], email=GUEST_EMAIL
        )

        response = authenticated_client.get(order_url(event, guests))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                guests,
                order_matcher=AttributesMatcher(pk=guests.pk, buyer_id=None),
                state=OrderPageState.CONFIRMING,
                claimable=True,
            ),
        )

    @pytest.mark.parametrize(
        ("status", "state", "claimable"),
        (
            pytest.param(
                OrderStatus.AWAITING_PAYMENT,
                OrderPageState.AWAITING_TRANSFER,
                True,
                id="bank-transfer",
            ),
            pytest.param(
                OrderStatus.REFUNDED, OrderPageState.REFUNDED, False, id="refunded"
            ),
            pytest.param(
                OrderStatus.EXPIRED, OrderPageState.NOT_COMPLETED, False, id="expired"
            ),
            pytest.param(
                OrderStatus.FAILED, OrderPageState.NOT_COMPLETED, False, id="failed"
            ),
        ),
    )
    def test_guest_order_offers_to_be_kept_only_while_tickets_are_coming(
        self, client, event, *, status, state, claimable
    ):
        guests = order(
            event,
            buyer=None,
            lines=[(ticket_type(event), 1)],
            status=status,
            email=GUEST_EMAIL,
        )

        response = client.get(order_url(event, guests))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                guests,
                order_matcher=AttributesMatcher(pk=guests.pk, status=status),
                state=state,
                claimable=claimable,
            ),
        )

    def test_guest_order_waits_for_checkouts_email_before_it_may_be_kept(
        self, authenticated_client, event
    ):
        guests = order(event, buyer=None, lines=[(ticket_type(event), 1)])

        response = authenticated_client.get(order_url(event, guests))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                guests,
                order_matcher=AttributesMatcher(pk=guests.pk, email=""),
                state=OrderPageState.CONFIRMING,
                claimable=False,
            ),
        )

    def test_claimed_order_sends_a_signed_out_visitor_to_log_in(
        self, client, event, active_user
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])
        url = order_url(event, mine)

        response = client.get(url)

        assert_response(response, HTTPStatus.FOUND, url=_login_redirect(url))

    def test_paid_order_shows_its_tickets(
        self, authenticated_client, event, active_user
    ):
        kind = ticket_type(event)
        mine = order(event, buyer=active_user, lines=[(kind, 2)], status="paid")
        first = Ticket.objects.create(
            order=mine, ticket_type=kind, holder=active_user, code="AAAAAAAA22"
        )
        second = Ticket.objects.create(
            order=mine, ticket_type=kind, holder=active_user, code="AAAAAAAA33"
        )

        response = authenticated_client.get(order_url(event, mine))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                mine,
                order_matcher=AttributesMatcher(
                    pk=mine.pk,
                    status=OrderStatus.PAID,
                    total=10_000,
                    tickets=[
                        TicketDTO(
                            pk=first.pk,
                            code="AAAAAAAA22",
                            ticket_type_name="Weekend pass",
                        ),
                        TicketDTO(
                            pk=second.pk,
                            code="AAAAAAAA33",
                            ticket_type_name="Weekend pass",
                        ),
                    ],
                ),
                state=OrderPageState.PAID,
                claimable=False,
            ),
        )

    @pytest.mark.parametrize(
        ("status", "hold_minutes", "state"),
        (
            pytest.param(
                OrderStatus.PENDING, 30, OrderPageState.CONFIRMING, id="paying-now"
            ),
            pytest.param(
                OrderStatus.PENDING,
                -1,
                OrderPageState.CONFIRMATION_LATE,
                id="hold-over-webhook-late",
            ),
            pytest.param(
                OrderStatus.AWAITING_PAYMENT,
                30,
                OrderPageState.AWAITING_TRANSFER,
                id="bank-transfer",
            ),
            pytest.param(
                OrderStatus.REFUNDED, 30, OrderPageState.REFUNDED, id="refunded"
            ),
            pytest.param(
                OrderStatus.EXPIRED, 30, OrderPageState.NOT_COMPLETED, id="expired"
            ),
            pytest.param(
                OrderStatus.FAILED, 30, OrderPageState.NOT_COMPLETED, id="failed"
            ),
        ),
    )
    def test_unpaid_order_says_where_it_stands(
        self, authenticated_client, event, active_user, *, status, hold_minutes, state
    ):
        mine = order(
            event,
            buyer=active_user,
            lines=[(ticket_type(event), 1)],
            status=status,
            hold_minutes=hold_minutes,
        )

        response = authenticated_client.get(order_url(event, mine))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                mine,
                order_matcher=AttributesMatcher(pk=mine.pk, status=status, tickets=[]),
                state=state,
                claimable=False,
            ),
        )

    def test_order_under_another_events_url_is_not_found(
        self, authenticated_client, event
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = order(elsewhere, buyer=None, lines=[(ticket_type(elsewhere), 1)])

        response = authenticated_client.get(order_url(event, guests))

        assert_response_404(response)

    def test_someone_elses_order_is_not_found(self, authenticated_client, event):
        theirs = order(event, buyer=UserFactory(), lines=[(ticket_type(event), 1)])

        response = authenticated_client.get(order_url(event, theirs))

        assert_response_404(response)


class TestEventTicketOrderClaimActionView:
    def test_account_verified_for_the_orders_email_claims_it_at_once(
        self, authenticated_client, event, active_user, mailoutbox
    ):
        guests = _guest_order_with_tickets(event, email=active_user.email.upper())

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response(
            response, HTTPStatus.FOUND, url=order_url(event, guests), messages=[CLAIMED]
        )
        assert _holders(guests) == (active_user.pk, {active_user.pk})
        assert not mailoutbox

    def test_claimed_order_forgets_the_guests_network(
        self, authenticated_client, event, active_user
    ):
        guests = _awaiting_transfer(event, email=active_user.email)

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response(
            response, HTTPStatus.FOUND, url=order_url(event, guests), messages=[CLAIMED]
        )
        guests.refresh_from_db()
        assert (guests.buyer_id, guests.guest_client) == (active_user.pk, "")

    @pytest.mark.parametrize(
        ("verified", "order_email"),
        (
            pytest.param(
                False, "testuser@example.com", id="unverified-account-same-address"
            ),
            pytest.param(True, GUEST_EMAIL, id="verified-another-address"),
        ),
    )
    def test_account_not_proven_for_the_email_is_sent_a_link_there(
        self,
        authenticated_client,
        event,
        active_user,
        mailoutbox,
        *,
        verified,
        order_email,
    ):
        active_user.email_verified = verified
        active_user.save()
        guests = _guest_order_with_tickets(event, email=order_email)

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[_link_sent(order_email)],
        )
        assert _holders(guests) == (None, {None})
        assert [(mail.to, mail.subject) for mail in mailoutbox] == [
            ([order_email], f"Add your tickets for {event.name} to an account?")
        ]
        intro, ask, _url, ignore = mailoutbox[0].body.split("\n\n")
        # Neutral: whoever asked, the mail names no account to the address.
        assert (intro, ask, ignore) == (
            (
                "Someone signed in to Zagrajmy wants to add your tickets for"
                f" {event.name} to their account."
            ),
            "If that was you, confirm it here within 24 hours:",
            "If it wasn't, ignore this email. Your tickets stay as they are.",
        )
        link = _confirm_link(mailoutbox[0])
        assert (
            link.view_name,
            link.kwargs["event_slug"],
            link.kwargs["reference"],
        ) == (
            "web:event:event-ticket-order-claim-confirm",
            event.slug,
            guests.reference,
        )
        assert DjangoOrderClaimCodec.loads(link.kwargs["token"]) == OrderClaimPayload(
            order_pk=guests.pk, user_id=active_user.pk
        )

    def test_asking_again_soon_mails_nothing_more(
        self, authenticated_client, event, mailoutbox
    ):
        guests = _guest_order_with_tickets(event)
        url = _claim_url(event, guests)
        with freeze_time(datetime.now(UTC)) as clock:
            # Followed, so the order page shows, and spends, its message.
            authenticated_client.post(url, follow=True)
            clock.tick(CLAIM_MAIL_INTERVAL - timedelta(seconds=1))
            response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[
                (
                    messages.INFO,
                    (
                        "A confirmation link went to guest@example.com recently. If it"
                        " doesn't work for this account, ask again in 10 minutes."
                    ),
                )
            ],
        )
        assert [mail.to for mail in mailoutbox] == [[GUEST_EMAIL]]
        assert _holders(guests) == (None, {None})

    def test_asking_again_after_the_interval_mails_again(
        self, authenticated_client, event, mailoutbox
    ):
        guests = _guest_order_with_tickets(event)
        url = _claim_url(event, guests)
        with freeze_time(datetime.now(UTC)) as clock:
            # Followed, so the order page shows, and spends, its message.
            authenticated_client.post(url, follow=True)
            clock.tick(CLAIM_MAIL_INTERVAL)
            response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[_link_sent(GUEST_EMAIL)],
        )
        assert [mail.to for mail in mailoutbox] == [[GUEST_EMAIL], [GUEST_EMAIL]]

    def test_mail_server_refusing_the_link_says_so_and_lets_you_ask_again(
        self, authenticated_client, event, mailoutbox, monkeypatch
    ):
        guests = _guest_order_with_tickets(event)
        url = _claim_url(event, guests)
        send = EmailMessage.send

        def refused(_message, *_args, **_kwargs):
            raise SMTPServerDisconnected

        monkeypatch.setattr(EmailMessage, "send", refused)
        refused_response = authenticated_client.post(url)
        assert_response(
            refused_response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[
                (
                    messages.ERROR,
                    (
                        "We couldn't send the confirmation link to guest@example.com."
                        " Try again in a moment."
                    ),
                )
            ],
        )
        # The order page shows, and spends, the message.
        authenticated_client.get(order_url(event, guests))
        monkeypatch.setattr(EmailMessage, "send", send)

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[_link_sent(GUEST_EMAIL)],
        )
        assert [mail.to for mail in mailoutbox] == [[GUEST_EMAIL]]

    @pytest.mark.parametrize("status", SPENT)
    @pytest.mark.parametrize(
        "verified", (True, False), ids=("verified-account", "unverified-account")
    )
    def test_order_that_brings_no_tickets_is_not_found_and_stays_as_it_is(
        self, authenticated_client, event, active_user, mailoutbox, *, status, verified
    ):
        active_user.email_verified = verified
        active_user.save()
        guests = order(
            event,
            buyer=None,
            lines=[(ticket_type(event), 1)],
            status=status,
            email=active_user.email,
        )

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response_404(response)
        guests.refresh_from_db()
        assert (guests.buyer_id, guests.status, guests.claim_mailed_at) == (
            None,
            status,
            None,
        )
        assert not mailoutbox

    def test_claimed_order_is_closed_to_its_link_from_then_on(
        self, authenticated_client, event, active_user
    ):
        guests = order(
            event, buyer=None, lines=[(ticket_type(event), 1)], email=active_user.email
        )
        url = order_url(event, guests)
        authenticated_client.post(_claim_url(event, guests))

        response = Client().get(url)

        assert_response(response, HTTPStatus.FOUND, url=_login_redirect(url))

    def test_own_order_stays_as_it_is(self, authenticated_client, event, active_user):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])

        response = authenticated_client.post(_claim_url(event, mine))

        assert_response(response, HTTPStatus.FOUND, url=order_url(event, mine))
        mine.refresh_from_db()
        assert mine.buyer_id == active_user.pk

    def test_someone_elses_order_is_not_found_and_stays_theirs(
        self, authenticated_client, event, active_user
    ):
        holder = UserFactory()
        kind = ticket_type(event)
        theirs = order(
            event,
            buyer=holder,
            lines=[(kind, 1)],
            status="paid",
            email=active_user.email,
        )
        Ticket.objects.create(
            order=theirs, ticket_type=kind, holder=holder, code="THEIRS2222"
        )

        response = authenticated_client.post(_claim_url(event, theirs))

        assert_response_404(response)
        assert _holders(theirs) == (holder.pk, {holder.pk})

    def test_order_of_another_event_is_not_found_and_stays_unclaimed(
        self, authenticated_client, event, active_user, mailoutbox
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = order(
            elsewhere,
            buyer=None,
            lines=[(ticket_type(elsewhere), 1)],
            email=active_user.email,
        )

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response_404(response)
        guests.refresh_from_db()
        assert guests.buyer_id is None
        assert not mailoutbox

    def test_order_without_an_email_yet_is_not_found_and_mails_nothing(
        self, authenticated_client, event, mailoutbox
    ):
        guests = order(event, buyer=None, lines=[(ticket_type(event), 1)])

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response_404(response)
        guests.refresh_from_db()
        assert (guests.buyer_id, guests.email) == (None, "")
        assert not mailoutbox

    def test_signed_out_visitor_is_sent_to_log_in_first(self, client, event):
        guests = order(
            event, buyer=None, lines=[(ticket_type(event), 1)], email=GUEST_EMAIL
        )

        response = client.post(_claim_url(event, guests))

        assert_response(
            response, HTTPStatus.FOUND, url=_login_redirect(order_url(event, guests))
        )
        guests.refresh_from_db()
        assert guests.buyer_id is None


class TestEventTicketOrderClaimConfirmPageView:
    def test_mailed_link_hands_the_order_to_the_account_that_asked(
        self, authenticated_client, event, active_user, mailoutbox
    ):
        guests = _guest_order_with_tickets(event)
        authenticated_client.post(_claim_url(event, guests), follow=True)
        link = _confirm_link(mailoutbox[0])

        response = authenticated_client.post(
            _confirm_url(event, guests, link.kwargs["token"])
        )

        assert_response(
            response, HTTPStatus.FOUND, url=order_url(event, guests), messages=[CLAIMED]
        )
        assert _holders(guests) == (active_user.pk, {active_user.pk})

    def test_confirmed_order_forgets_the_guests_network(
        self, authenticated_client, event, active_user
    ):
        guests = _awaiting_transfer(event)

        response = authenticated_client.post(
            _confirm_url(event, guests, _token(guests, active_user))
        )

        assert_response(
            response, HTTPStatus.FOUND, url=order_url(event, guests), messages=[CLAIMED]
        )
        guests.refresh_from_db()
        assert (guests.buyer_id, guests.guest_client) == (active_user.pk, "")

    def test_page_asks_before_it_claims(self, authenticated_client, event, active_user):
        guests = _guest_order_with_tickets(event)
        token = _token(guests, active_user)

        response = authenticated_client.get(_confirm_url(event, guests, token))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order-claim.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "reference": guests.reference,
                "token": token,
            },
        )
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_signed_out_visitor_is_sent_to_log_in_first(
        self, client, event, active_user, method
    ):
        guests = _guest_order_with_tickets(event)
        url = _confirm_url(event, guests, _token(guests, active_user))

        response = getattr(client, method)(url)

        assert_response(response, HTTPStatus.FOUND, url=_login_redirect(url))
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_link_made_for_another_account_claims_nothing(
        self, authenticated_client, event, method
    ):
        guests = _guest_order_with_tickets(event)
        token = _token(guests, UserFactory())

        response = getattr(authenticated_client, method)(
            _confirm_url(event, guests, token)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[LINK_INVALID],
        )
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_link_made_for_another_order_claims_nothing(
        self, authenticated_client, event, active_user, method
    ):
        guests = _guest_order_with_tickets(event)
        other = order(
            event, buyer=None, lines=[(ticket_type(event), 1)], session_id="cs_2"
        )

        response = getattr(authenticated_client, method)(
            _confirm_url(event, guests, _token(other, active_user))
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[LINK_INVALID],
        )
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_expired_link_claims_nothing(
        self, authenticated_client, event, active_user, method
    ):
        guests = _guest_order_with_tickets(event)
        token = _token(guests, active_user)

        a_second_too_late = ORDER_CLAIM_LINK_MAX_AGE + timedelta(seconds=1)
        with freeze_time(datetime.now(UTC) + a_second_too_late):
            response = getattr(authenticated_client, method)(
                _confirm_url(event, guests, token)
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[LINK_INVALID],
        )
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize(
        "tamper",
        (
            pytest.param(
                lambda token: f"{token.rsplit(':', 1)[0]}:{'A' * 43}", id="signature"
            ),
            pytest.param(lambda token: f"x{token}", id="payload"),
            pytest.param(lambda _token: "not-a-token", id="garbage"),
        ),
    )
    @pytest.mark.parametrize("method", ("get", "post"))
    def test_tampered_link_claims_nothing(
        self, authenticated_client, event, active_user, tamper, method
    ):
        guests = _guest_order_with_tickets(event)
        token = tamper(_token(guests, active_user))

        response = getattr(authenticated_client, method)(
            _confirm_url(event, guests, token)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=order_url(event, guests),
            messages=[LINK_INVALID],
        )
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_own_order_goes_back_to_its_page(
        self, authenticated_client, event, active_user, method
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])

        response = getattr(authenticated_client, method)(
            _confirm_url(event, mine, _token(mine, active_user))
        )

        assert_response(response, HTTPStatus.FOUND, url=order_url(event, mine))
        mine.refresh_from_db()
        assert mine.buyer_id == active_user.pk

    @pytest.mark.parametrize("method", ("get", "post"))
    @pytest.mark.parametrize("status", SPENT)
    def test_order_that_brings_no_tickets_is_not_found_and_stays_unclaimed(
        self, authenticated_client, event, active_user, *, status, method
    ):
        guests = order(
            event,
            buyer=None,
            lines=[(ticket_type(event), 1)],
            status=status,
            email=GUEST_EMAIL,
        )

        response = getattr(authenticated_client, method)(
            _confirm_url(event, guests, _token(guests, active_user))
        )

        assert_response_404(response)
        guests.refresh_from_db()
        assert (guests.buyer_id, guests.status) == (None, status)

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_order_of_another_event_is_not_found_and_stays_unclaimed(
        self, authenticated_client, event, active_user, method
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = _guest_order_with_tickets(elsewhere)

        response = getattr(authenticated_client, method)(
            _confirm_url(event, guests, _token(guests, active_user))
        )

        assert_response_404(response)
        assert _holders(guests) == (None, {None})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_order_someone_else_claimed_is_not_found_and_stays_theirs(
        self, authenticated_client, event, active_user, method
    ):
        holder = UserFactory()
        theirs = order(event, buyer=holder, lines=[(ticket_type(event), 1)])

        response = getattr(authenticated_client, method)(
            _confirm_url(event, theirs, _token(theirs, active_user))
        )

        assert_response_404(response)
        theirs.refresh_from_db()
        assert theirs.buyer_id == holder.pk
