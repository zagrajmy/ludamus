"""Ticket sales: the buyer's order page, abandoning Checkout, claiming an order.

Ways the service could fail, each pinned below:

Order page
- An order claimed into an account is shown to anyone else, an order from
  another event is shown, or a guest's order is hidden from its link.
- The page polls for an order Stripe will not settle within seconds.
- The page offers to keep an order in an account when the order holds an
  account already, or when no ticket will ever come of it.

Abandoning Checkout
- It expires an order Stripe already completed, one that is no longer
  pending, or someone else's.

Claiming
- Claiming takes an order another account holds, or one of another event, or
  mails a confirmation for a guest's order before Checkout reported its email.
- A refunded or failed guest order, which no ticket will come of, is claimed
  or confirmed.
- Whoever holds a forwarded link takes the order without the order's email
  agreeing, or an account verified for that email is sent a link anyway, or
  an account holding that address unverified is not asked to prove it.
- Asking again and again floods the order's address with confirmations, or a
  later ask, once the interval has passed, sends none.
- A claimed order leaves its tickets out of the new holder's count, or keeps
  the guest's network on it.
- A confirmation link takes the order for an account it was not made for, or
  takes an order it was not made for, or works once expired or forged.
- A link followed twice, or for an order already yours, claims it again.
- An address differing only in case is not the order's, or an account with no
  verified address owns an order bought without one.
"""

import logging
from datetime import timedelta

import pytest

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.tickets import (
    AbandonOutcome,
    ClaimConfirmationMail,
    ClaimOutcome,
    ClaimResultDTO,
    ConfirmOutcome,
    OrderClaimPayload,
    OrderMailEvent,
    OrderPageState,
    OrderStatus,
)
from ludamus.specs.tickets import CLAIM_MAIL_INTERVAL, owns_order_email
from tests.unit.ticket_fakes import (
    BUYER_ID,
    EVENT_ID,
    GUEST_EMAIL,
    NOW,
    OTHER_BUYER_ID,
    OTHER_EVENT_ID,
    SPHERE_ID,
    TICKETS_LOGGER,
    add_guest_order,
    add_order,
    status_of,
)

pytest_plugins = ("tests.unit.ticket_fixtures",)

_GUEST_CLIENT = "client-a"
_NO_TICKETS_COMING = (OrderStatus.REFUNDED, OrderStatus.FAILED, OrderStatus.EXPIRED)


def _claim(sales, order, *, user_id=BUYER_ID):
    return sales.claim_order(
        event_id=EVENT_ID, reference=order.reference, user_id=user_id
    )


def _claimed_codes(sales, *, holder_id=BUYER_ID):
    return [
        ticket.code
        for ticket in sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=holder_id)
    ]


class TestOrderPage:
    @pytest.mark.parametrize(
        ("event_id", "reference", "viewer_id"),
        (
            pytest.param(EVENT_ID, "ref1", OTHER_BUYER_ID, id="someone-elses"),
            pytest.param(EVENT_ID, "ref1", None, id="claimed-and-signed-out"),
            pytest.param(OTHER_EVENT_ID, "ref1", BUYER_ID, id="another-event"),
            pytest.param(EVENT_ID, "nope", BUYER_ID, id="unknown-reference"),
        ),
    )
    def test_order_out_of_the_viewers_reach_is_not_found(
        self, sales, book, types, orders, payments, event_id, reference, viewer_id
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        payments.down.add("expire_checkout")

        with pytest.raises(NotFoundError):
            sales.order(event_id=event_id, reference=reference, viewer_id=viewer_id)
        with pytest.raises(NotFoundError):
            sales.abandon_checkout(
                event_id=event_id, reference=reference, viewer_id=viewer_id
            )
        assert book.orders[order.pk] == order

    def test_guest_order_is_its_links_whoever_holds_it(self, sales, types, orders):
        order = add_guest_order(orders, types.add(), email=GUEST_EMAIL)

        pages = [
            sales.order(event_id=EVENT_ID, reference=order.reference, viewer_id=viewer)
            for viewer in (None, OTHER_BUYER_ID)
        ]

        assert [(page.order, page.claimable) for page in pages] == [
            (order, True),
            (order, True),
        ]

    def test_order_held_by_an_account_is_not_offered_to_claim(
        self, sales, types, orders
    ):
        order = add_order(orders, types.add())

        page = sales.order(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert not page.claimable

    @pytest.mark.parametrize(
        ("overrides", "claimable"),
        (
            pytest.param({"status": OrderStatus.PAID}, True, id="paid"),
            pytest.param(
                {"status": OrderStatus.AWAITING_PAYMENT}, True, id="awaiting-payment"
            ),
            pytest.param({"status": OrderStatus.REFUNDED}, False, id="refunded"),
            pytest.param({"status": OrderStatus.EXPIRED}, False, id="expired"),
            pytest.param({"status": OrderStatus.FAILED}, False, id="failed"),
            pytest.param({"email": ""}, False, id="no-email-yet"),
        ),
    )
    def test_guest_order_is_offered_to_claim_only_while_tickets_may_come_of_it(
        self, sales, types, orders, overrides, claimable
    ):
        order = add_guest_order(
            orders, types.add(), **({"email": GUEST_EMAIL} | overrides)
        )

        page = sales.order(event_id=EVENT_ID, reference=order.reference, viewer_id=None)

        assert page.claimable is claimable

    @pytest.mark.parametrize(
        ("status", "hold", "state"),
        (
            (OrderStatus.PENDING, timedelta(minutes=30), OrderPageState.CONFIRMING),
            (
                OrderStatus.PENDING,
                -timedelta(minutes=1),
                OrderPageState.CONFIRMATION_LATE,
            ),
            (
                OrderStatus.AWAITING_PAYMENT,
                timedelta(minutes=30),
                OrderPageState.AWAITING_TRANSFER,
            ),
            (OrderStatus.PAID, timedelta(minutes=30), OrderPageState.PAID),
            (OrderStatus.REFUNDED, timedelta(minutes=30), OrderPageState.REFUNDED),
            (OrderStatus.EXPIRED, timedelta(minutes=30), OrderPageState.NOT_COMPLETED),
            (OrderStatus.FAILED, timedelta(minutes=30), OrderPageState.NOT_COMPLETED),
        ),
    )
    def test_order_page_says_where_the_order_stands(
        self, sales, types, orders, status, hold, state
    ):
        order = add_order(orders, types.add(), status=status, hold_until=NOW + hold)

        page = sales.order(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert page.state is state


class TestAbandonCheckout:
    @pytest.mark.parametrize("session_id", ("cs_1", ""))
    @pytest.mark.parametrize(
        ("buyer_id", "viewer_id"),
        ((BUYER_ID, BUYER_ID), (None, None)),
        ids=("holder", "guest"),
    )
    def test_abandoning_checkout_expires_the_pending_order(
        self, sales, book, types, orders, session_id, buyer_id, viewer_id
    ):
        order = add_order(
            orders,
            types.add(),
            buyer_id=buyer_id,
            stripe_checkout_session_id=session_id,
        )

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=viewer_id
        )

        assert outcome is AbandonOutcome.CANCELLED
        assert status_of(book, order) is OrderStatus.EXPIRED

    def test_abandoning_a_checkout_stripe_already_closed_leaves_it_to_the_webhook(
        self, sales, book, types, orders, payments
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        payments.down.add("expire_checkout")

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert outcome is AbandonOutcome.UNCONFIRMED
        assert status_of(book, order) is OrderStatus.PENDING

    def test_abandoning_a_paid_order_changes_nothing(self, sales, book, types, orders):
        order = add_order(orders, types.add(), status=OrderStatus.PAID)

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert outcome is AbandonOutcome.SETTLED
        assert status_of(book, order) is OrderStatus.PAID

    def test_order_paid_while_its_session_was_expired_stays_paid(
        self, sales, book, types, orders, payments, monkeypatch
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        def paid_meanwhile(**_stripe_call):
            orders.move(
                pk=order.pk,
                to=OrderStatus.PAID,
                allowed_from=frozenset({OrderStatus.PENDING}),
                changes={},
            )

        monkeypatch.setattr(payments, "expire_checkout", paid_meanwhile)

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert outcome is AbandonOutcome.SETTLED
        assert status_of(book, order) is OrderStatus.PAID


class TestClaimOrder:
    @pytest.fixture(name="paid_guest_order")
    def paid_guest_order_fixture(self, book, types, orders):
        regular = types.add()
        order = add_guest_order(
            orders,
            regular,
            status=OrderStatus.PAID,
            email=GUEST_EMAIL,
            guest_client=_GUEST_CLIENT,
        )
        orders.issue_tickets(
            order=order, tickets=[{"ticket_type_id": regular.pk, "code": "AAAA"}]
        )
        return book.orders[order.pk]

    def test_account_verified_for_the_orders_email_claims_it_at_once(
        self, sales, book, users, mailer, paid_guest_order
    ):
        order = paid_guest_order
        users.add(pk=BUYER_ID, email=GUEST_EMAIL.upper(), email_verified=True)

        result = _claim(sales, order)

        assert result == ClaimResultDTO(
            outcome=ClaimOutcome.CLAIMED, order_email=GUEST_EMAIL
        )
        assert book.orders[order.pk].buyer_id == BUYER_ID
        assert not book.guest_clients[order.pk]
        assert mailer.confirmations == []
        assert _claimed_codes(sales) == ["AAAA"]
        assert sales.shop(event=book.event, viewer_id=BUYER_ID).viewer_ticket_count == 1
        for viewer in (None, OTHER_BUYER_ID):
            with pytest.raises(NotFoundError):
                sales.order(
                    event_id=EVENT_ID, reference=order.reference, viewer_id=viewer
                )

    @pytest.mark.parametrize(
        "user_id",
        (
            pytest.param(OTHER_BUYER_ID, id="the-address-unverified"),
            pytest.param(BUYER_ID, id="another-verified-address"),
        ),
    )
    def test_any_other_account_is_sent_to_ask_the_orders_email(
        self, sales, book, mailer, claims, paid_guest_order, user_id
    ):
        order = paid_guest_order

        result = _claim(sales, order, user_id=user_id)

        assert result == ClaimResultDTO(
            outcome=ClaimOutcome.CONFIRMATION_SENT, order_email=GUEST_EMAIL
        )
        assert book.orders[order.pk].buyer_id is None
        [mail] = mailer.confirmations
        assert mail == ClaimConfirmationMail(
            order_pk=order.pk,
            email=GUEST_EMAIL,
            event=OrderMailEvent(
                pk=EVENT_ID, name=book.event.name, slug=book.event.slug
            ),
            reference=order.reference,
            token=mail.token,
        )
        assert claims.loads(mail.token) == OrderClaimPayload(
            order_pk=order.pk, user_id=user_id
        )

    def test_asking_again_within_the_interval_mails_nothing_more(
        self, sales, mailer, paid_guest_order, caplog
    ):
        order = paid_guest_order

        with caplog.at_level(logging.INFO, logger=TICKETS_LOGGER):
            first = _claim(sales, order)
            again = _claim(sales, order)
            by_another = _claim(sales, order, user_id=OTHER_BUYER_ID)

        assert first == ClaimResultDTO(
            outcome=ClaimOutcome.CONFIRMATION_SENT, order_email=GUEST_EMAIL
        )
        assert (
            again
            == by_another
            == ClaimResultDTO(
                outcome=ClaimOutcome.CONFIRMATION_HELD, order_email=GUEST_EMAIL
            )
        )
        assert len(mailer.confirmations) == 1
        assert caplog.messages == [
            f"Ticket order claim confirmation sent: order={order.pk} user={BUYER_ID}",
            f"Ticket order claim mail held back: order={order.pk}",
            f"Ticket order claim mail held back: order={order.pk}",
        ]

    def test_asking_again_once_the_interval_passed_mails_a_new_link(
        self, sales, book, orders, mailer, claims, paid_guest_order
    ):
        order = paid_guest_order
        orders.mark_claim_mailed(
            pk=order.pk, at=NOW - CLAIM_MAIL_INTERVAL - timedelta(seconds=1)
        )

        result = _claim(sales, order, user_id=OTHER_BUYER_ID)

        assert result.outcome is ClaimOutcome.CONFIRMATION_SENT
        [mail] = mailer.confirmations
        assert claims.loads(mail.token) == OrderClaimPayload(
            order_pk=order.pk, user_id=OTHER_BUYER_ID
        )
        assert book.orders[order.pk].claim_mailed_at > NOW

    @pytest.mark.parametrize("status", (OrderStatus.PAID, OrderStatus.REFUNDED))
    def test_claiming_your_own_order_again_changes_nothing(
        self, sales, book, types, orders, mailer, status
    ):
        order = add_order(orders, types.add(), status=status)

        result = _claim(sales, order)

        assert result == ClaimResultDTO(
            outcome=ClaimOutcome.ALREADY_YOURS, order_email=order.email
        )
        assert book.orders[order.pk] == order
        assert mailer.confirmations == []

    @pytest.mark.parametrize(
        ("event_id", "reference", "holder"),
        (
            pytest.param(EVENT_ID, "ref1", OTHER_BUYER_ID, id="held-by-another"),
            pytest.param(OTHER_EVENT_ID, "ref1", None, id="another-event"),
            pytest.param(EVENT_ID, "nope", None, id="unknown-reference"),
        ),
    )
    def test_order_out_of_reach_is_not_claimed(
        self, sales, book, types, orders, users, mailer, event_id, reference, holder
    ):
        order = add_order(orders, types.add(), buyer_id=holder)
        users.add(pk=BUYER_ID, email=order.email, email_verified=True)

        with pytest.raises(NotFoundError):
            sales.claim_order(event_id=event_id, reference=reference, user_id=BUYER_ID)
        assert book.orders[order.pk] == order
        assert mailer.confirmations == []

    @pytest.mark.parametrize(
        ("email", "status"),
        (
            pytest.param("", OrderStatus.PAID, id="no-email-yet"),
            *((GUEST_EMAIL, status) for status in _NO_TICKETS_COMING),
        ),
    )
    def test_guest_order_no_ticket_may_come_of_is_not_claimed(
        self, sales, book, types, orders, users, mailer, email, status
    ):
        order = add_guest_order(orders, types.add(), email=email, status=status)
        users.add(pk=BUYER_ID, email=GUEST_EMAIL, email_verified=True)

        for user_id in (BUYER_ID, OTHER_BUYER_ID):
            with pytest.raises(NotFoundError):
                _claim(sales, order, user_id=user_id)
        assert book.orders[order.pk] == order
        assert mailer.confirmations == []


class TestConfirmClaim:
    @pytest.fixture(name="regular")
    def regular_fixture(self, types):
        return types.add()

    @staticmethod
    def _ask(sales, mailer, order, *, user_id=BUYER_ID):
        _claim(sales, order, user_id=user_id)
        return mailer.confirmations[-1].token

    @staticmethod
    def _confirm(sales, order, *, token, user_id=BUYER_ID):
        return sales.confirm_claim(
            event_id=EVENT_ID, reference=order.reference, token=token, user_id=user_id
        )

    def test_link_from_the_orders_email_gives_the_order_to_its_account(
        self, sales, book, orders, mailer, regular
    ):
        order = add_guest_order(
            orders,
            regular,
            status=OrderStatus.PAID,
            email=GUEST_EMAIL,
            guest_client=_GUEST_CLIENT,
        )
        orders.issue_tickets(
            order=order, tickets=[{"ticket_type_id": regular.pk, "code": "AAAA"}]
        )
        token = self._ask(sales, mailer, order)

        outcome = self._confirm(sales, order, token=token)

        assert outcome is ConfirmOutcome.CLAIMED
        assert book.orders[order.pk].buyer_id == BUYER_ID
        assert not book.guest_clients[order.pk]
        assert _claimed_codes(sales) == ["AAAA"]

    def test_link_made_for_another_account_claims_nothing(
        self, sales, book, orders, mailer, regular
    ):
        order = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, order, user_id=OTHER_BUYER_ID)
        asked = book.orders[order.pk]

        outcome = self._confirm(sales, order, token=token)

        assert outcome is ConfirmOutcome.LINK_INVALID
        assert book.orders[order.pk] == asked

    def test_link_made_for_another_order_claims_nothing(
        self, sales, book, orders, mailer, regular
    ):
        asked = add_guest_order(orders, regular, email=GUEST_EMAIL)
        other = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, asked)

        outcome = self._confirm(sales, other, token=token)

        assert outcome is ConfirmOutcome.LINK_INVALID
        assert book.orders[other.pk] == other

    @pytest.mark.parametrize("expired", (True, False), ids=("expired", "forged"))
    def test_link_that_does_not_read_back_claims_nothing(
        self, sales, book, orders, mailer, claims, regular, expired
    ):
        order = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, order)
        asked = book.orders[order.pk]
        if expired:
            claims.expire(token)

        outcome = self._confirm(sales, order, token=token if expired else "forged")

        assert outcome is ConfirmOutcome.LINK_INVALID
        assert book.orders[order.pk] == asked

    def test_link_followed_again_finds_the_order_already_yours(
        self, sales, book, orders, mailer, regular
    ):
        order = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, order)
        self._confirm(sales, order, token=token)
        claimed = book.orders[order.pk]

        outcome = self._confirm(sales, order, token=token)

        assert outcome is ConfirmOutcome.ALREADY_YOURS
        assert book.orders[order.pk] == claimed

    def test_link_for_an_order_another_account_took_meanwhile_is_not_found(
        self, sales, book, orders, mailer, regular
    ):
        order = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, order)
        orders.claim(pk=order.pk, buyer_id=OTHER_BUYER_ID)
        taken = book.orders[order.pk]

        with pytest.raises(NotFoundError):
            self._confirm(sales, order, token=token)
        assert book.orders[order.pk] == taken

    @pytest.mark.parametrize("given_up", _NO_TICKETS_COMING)
    def test_link_for_an_order_no_ticket_will_come_of_any_more_is_not_found(
        self, sales, book, orders, mailer, regular, given_up
    ):
        order = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, order)
        orders.move(
            pk=order.pk, to=given_up, allowed_from=frozenset(OrderStatus), changes={}
        )
        moved = book.orders[order.pk]

        with pytest.raises(NotFoundError):
            self._confirm(sales, order, token=token)
        assert book.orders[order.pk] == moved

    def test_link_followed_on_another_events_page_is_not_found(
        self, sales, book, orders, mailer, regular
    ):
        order = add_guest_order(orders, regular, email=GUEST_EMAIL)
        token = self._ask(sales, mailer, order)
        asked = book.orders[order.pk]

        with pytest.raises(NotFoundError):
            sales.confirm_claim(
                event_id=OTHER_EVENT_ID,
                reference=order.reference,
                token=token,
                user_id=BUYER_ID,
            )
        assert book.orders[order.pk] == asked


class TestOwnsOrderEmail:
    @pytest.mark.parametrize(
        ("order_email", "verified_email", "owns"),
        (
            pytest.param(GUEST_EMAIL, GUEST_EMAIL, True, id="same"),
            pytest.param(GUEST_EMAIL, "Guest@Example.COM", True, id="other-case"),
            pytest.param(GUEST_EMAIL, "someone@example.com", False, id="another"),
            pytest.param(GUEST_EMAIL, "", False, id="unverified"),
            pytest.param("", "", False, id="neither-has-one"),
        ),
    )
    def test_only_the_verified_address_of_the_order_owns_it(
        self, order_email, verified_email, owns
    ):
        assert (
            owns_order_email(order_email=order_email, verified_email=verified_email)
            is owns
        )
