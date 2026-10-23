"""Ticket sales: the sphere's payout account, the shop, the panel, the webhook.

Every id a request supplies is scoped here, not in the view: ticket type ids
to the event the gate resolved, order ids to their buyer or to the panel's
event. Stripe's ids arrive only in signed webhooks.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.mills.qr import qr_svg
from ludamus.pacts.billing import PlanKind
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import PaymentProviderError, WebhookEventKind
from ludamus.pacts.tickets import (
    DEFAULT_CURRENCY,
    MAX_TICKETS_PER_ORDER,
    TICKET_CODE_LENGTH,
    CheckoutLine,
    CheckoutOutcome,
    CheckoutRequest,
    CheckoutStartDTO,
    EventShopDTO,
    FeeBreakdownDTO,
    OfferState,
    OrderStatus,
    PayoutPageDTO,
    PayoutServiceProtocol,
    PayoutStatus,
    RefundOutcome,
    TicketOfferDTO,
    TicketPanelDTO,
    TicketPanelServiceProtocol,
    TicketSalesServiceProtocol,
    TicketSalesSummaryDTO,
    TicketTypeRowDTO,
)
from ludamus.specs.tickets import (
    CHECKOUT_HOLD,
    PLATFORM_FEE_BPS,
    STRIPE_FEE_ESTIMATE_BPS,
    STRIPE_FEE_ESTIMATE_FIXED,
)

if TYPE_CHECKING:
    from ludamus.pacts.billing import SpherePlanRepositoryProtocol
    from ludamus.pacts.payment_api import CheckoutSessionFacts, StripeWebhookEvent
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.tickets import (
        CheckoutUrls,
        OrderDTO,
        OrderLineData,
        OwnedTicketDTO,
        PayoutAccountDTO,
        PayoutAccountRepositoryProtocol,
        TicketPaymentsProtocol,
        TicketRepos,
        TicketTypeData,
        TicketTypeDTO,
    )

logger = logging.getLogger(__name__)

_BPS = 10_000
# Unambiguous on a phone screen and read aloud at a door: no 0/O, 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _share(total: int, bps: int) -> int:
    # Integer round half up, so a 10 000 zł order is as exact as a 10 zł one.
    return (total * bps + _BPS // 2) // _BPS


def platform_fee(total: int, *, plan: PlanKind) -> int:
    if total <= 0:
        message = f"A fee needs a positive total, got {total}."
        raise ValueError(message)
    return _share(total, PLATFORM_FEE_BPS[plan])


def estimated_stripe_fee(total: int) -> int:
    return _share(total, STRIPE_FEE_ESTIMATE_BPS) + STRIPE_FEE_ESTIMATE_FIXED


def offer_for(
    ticket_type: TicketTypeDTO, *, now: datetime, closes_at: datetime | None = None
) -> TicketOfferDTO:
    """Say what a buyer may do with a ticket type right now.

    `closes_at` is when sales end for a type without its own end: the event's
    end, so nobody buys entry to something already over.
    """
    remaining = (
        None
        if ticket_type.quantity is None
        else max(ticket_type.quantity - ticket_type.sold - ticket_type.held, 0)
    )
    sales_end = ticket_type.sales_end or closes_at
    if sales_end is not None and now >= sales_end:
        state = OfferState.ENDED
    elif ticket_type.sales_start is not None and now < ticket_type.sales_start:
        state = OfferState.NOT_YET
    elif remaining == 0:
        state = OfferState.SOLD_OUT
    else:
        state = OfferState.ON_SALE
    max_quantity = (
        0
        if state is not OfferState.ON_SALE
        else min(MAX_TICKETS_PER_ORDER, remaining or MAX_TICKETS_PER_ORDER)
    )
    return TicketOfferDTO(
        ticket_type=ticket_type,
        state=state,
        remaining=remaining,
        max_quantity=max_quantity,
    )


def payout_status(account: PayoutAccountDTO | None) -> PayoutStatus:
    if account is None:
        return PayoutStatus.NOT_CONNECTED
    if account.charges_enabled:
        return PayoutStatus.ACTIVE
    return PayoutStatus.INCOMPLETE


def plan_kind(plans: SpherePlanRepositoryProtocol, *, sphere_id: int) -> PlanKind:
    plan = plans.read(sphere_id=sphere_id)
    return PlanKind.STANDARD if plan is None else plan.kind


def _ticket_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(TICKET_CODE_LENGTH))


class PayoutService(PayoutServiceProtocol):
    """The sphere's connected Stripe account: connect it, and read its state."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        accounts: PayoutAccountRepositoryProtocol,
        payments: TicketPaymentsProtocol,
    ) -> None:
        self._transaction = transaction
        self._accounts = accounts
        self._payments = payments

    def page(self, *, sphere_id: int) -> PayoutPageDTO:
        account = self._accounts.read(sphere_id=sphere_id)
        return PayoutPageDTO(
            status=payout_status(account),
            available=self._payments.enabled,
            payouts_enabled=account is not None and account.payouts_enabled,
        )

    def onboarding_url(
        self, *, sphere_id: int, email: str, refresh_url: str, return_url: str
    ) -> str:
        account = self._accounts.read(sphere_id=sphere_id)
        if account is None:
            account_id = self._payments.create_account(sphere_id=sphere_id, email=email)
            with self._transaction.atomic():
                account = self._accounts.create(
                    sphere_id=sphere_id, stripe_account_id=account_id
                )
            logger.info(
                "Payout account created: sphere=%s account=%s", sphere_id, account_id
            )
        return self._payments.onboarding_url(
            account_id=account.stripe_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )

    def refresh(self, *, sphere_id: int) -> PayoutPageDTO:
        # The return from onboarding: Stripe's webhook may lag the browser, so
        # ask once rather than show a stale "incomplete".
        if (account := self._accounts.read(sphere_id=sphere_id)) is not None:
            state = self._payments.read_account(account_id=account.stripe_account_id)
            with self._transaction.atomic():
                self._accounts.update_state(
                    stripe_account_id=account.stripe_account_id, state=state
                )
        return self.page(sphere_id=sphere_id)


class TicketSalesService(TicketSalesServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: TicketRepos,
        payments: TicketPaymentsProtocol,
    ) -> None:
        self._transaction = transaction
        self._ticket_types = repos.ticket_types
        self._orders = repos.orders
        self._accounts = repos.accounts
        self._plans = repos.plans
        self._event_log = repos.event_log
        self._payments = payments

    def shop(
        self,
        *,
        sphere_id: int,
        event_id: int,
        viewer_id: int | None,
        closes_at: datetime | None = None,
    ) -> EventShopDTO:
        now = datetime.now(tz=UTC)
        account = self._accounts.read(sphere_id=sphere_id)
        return EventShopDTO(
            offers=[
                offer_for(ticket_type, now=now, closes_at=closes_at)
                for ticket_type in self._ticket_types.list_for_event(
                    event_id=event_id, now=now
                )
            ],
            accepting_payments=self._payments.enabled
            and payout_status(account) is PayoutStatus.ACTIVE,
            viewer_ticket_count=(
                0
                if viewer_id is None
                else self._orders.count_valid_tickets(
                    event_id=event_id, holder_id=viewer_id
                )
            ),
        )

    def start_checkout(
        self,
        *,
        sphere_id: int,
        event_id: int,
        buyer_id: int,
        email: str,
        quantities: dict[int, int],
        urls: CheckoutUrls,
        closes_at: datetime | None = None,
    ) -> CheckoutStartDTO:
        wanted = {pk: count for pk, count in quantities.items() if count > 0}
        if not wanted:
            return CheckoutStartDTO(outcome=CheckoutOutcome.NOTHING_SELECTED)
        if sum(wanted.values()) > MAX_TICKETS_PER_ORDER:
            return CheckoutStartDTO(outcome=CheckoutOutcome.TOO_MANY)
        account = self._accounts.read(sphere_id=sphere_id)
        if (
            not self._payments.enabled
            or account is None
            or payout_status(account) is not PayoutStatus.ACTIVE
        ):
            return CheckoutStartDTO(outcome=CheckoutOutcome.SALES_CLOSED)

        now = datetime.now(tz=UTC)
        hold_until = now + CHECKOUT_HOLD
        with self._transaction.atomic():
            types = {
                ticket_type.pk: ticket_type
                for ticket_type in self._ticket_types.lock_for_event(
                    event_id=event_id, now=now
                )
            }
            lines: list[OrderLineData] = []
            for pk, count in sorted(wanted.items()):
                # An id from another event, or archived, is simply not here.
                if (ticket_type := types.get(pk)) is None:
                    return CheckoutStartDTO(outcome=CheckoutOutcome.NOT_ON_SALE)
                offer = offer_for(ticket_type, now=now, closes_at=closes_at)
                if offer.state is OfferState.SOLD_OUT or (
                    offer.state is OfferState.ON_SALE and count > offer.max_quantity
                ):
                    return CheckoutStartDTO(outcome=CheckoutOutcome.SOLD_OUT)
                if offer.state is not OfferState.ON_SALE:
                    return CheckoutStartDTO(outcome=CheckoutOutcome.NOT_ON_SALE)
                lines.append(
                    {
                        "ticket_type_id": pk,
                        "quantity": count,
                        "unit_price": ticket_type.price,
                    }
                )
            total = sum(line["quantity"] * line["unit_price"] for line in lines)
            order = self._orders.create(
                {
                    "event_id": event_id,
                    "buyer_id": buyer_id,
                    "email": email,
                    "currency": DEFAULT_CURRENCY,
                    "total": total,
                    "platform_fee": platform_fee(
                        total, plan=plan_kind(self._plans, sphere_id=sphere_id)
                    ),
                    "stripe_account_id": account.stripe_account_id,
                    "hold_until": hold_until,
                    "lines": lines,
                }
            )

        # Outside the lock: the hold is committed, so a slow Stripe call keeps
        # nobody else waiting, and a failed one releases it below.
        try:
            session = self._payments.create_checkout(
                CheckoutRequest(
                    account_id=order.stripe_account_id,
                    order_pk=order.pk,
                    currency=order.currency,
                    lines=[
                        CheckoutLine(
                            name=line.ticket_type_name,
                            unit_amount=line.unit_price,
                            quantity=line.quantity,
                        )
                        for line in order.lines
                    ],
                    application_fee=order.platform_fee,
                    customer_email=email,
                    success_url=urls.success(order.pk),
                    cancel_url=urls.cancel(order.pk),
                    expires_at=hold_until,
                )
            )
        except PaymentProviderError:
            with self._transaction.atomic():
                self._orders.mark(pk=order.pk, status=OrderStatus.FAILED)
            return CheckoutStartDTO(outcome=CheckoutOutcome.PROVIDER_ERROR)
        with self._transaction.atomic():
            self._orders.attach_checkout(pk=order.pk, session_id=session.id)
        logger.info(
            "Ticket checkout started: event=%s order=%s tickets=%s total=%s",
            event_id,
            order.pk,
            order.ticket_count,
            order.total,
        )
        return CheckoutStartDTO(outcome=CheckoutOutcome.STARTED, url=session.url)

    def order(self, *, buyer_id: int, event_id: int, pk: int) -> OrderDTO:
        order = self._orders.read_for_buyer(buyer_id=buyer_id, pk=pk)
        if order is None or order.event_id != event_id:
            raise NotFoundError
        return order

    def abandon_checkout(self, *, buyer_id: int, event_id: int, pk: int) -> None:
        order = self.order(buyer_id=buyer_id, event_id=event_id, pk=pk)
        if order.status is not OrderStatus.PENDING:
            return
        if order.stripe_checkout_session_id:
            try:
                self._payments.expire_checkout(
                    account_id=order.stripe_account_id,
                    session_id=order.stripe_checkout_session_id,
                )
            except PaymentProviderError:
                # Already completed or expired on Stripe's side: its webhook
                # tells us which. Leave the order to it.
                return
        with self._transaction.atomic():
            self._orders.mark(pk=order.pk, status=OrderStatus.EXPIRED)
        logger.info("Ticket checkout abandoned: order=%s", order.pk)

    def owned_tickets(self, *, sphere_id: int, holder_id: int) -> list[OwnedTicketDTO]:
        return [
            ticket.model_copy(
                update={"qr_svg": qr_svg(ticket.code, scale=5, xmldecl=False)}
            )
            for ticket in self._orders.list_owned_tickets(
                sphere_id=sphere_id, holder_id=holder_id
            )
        ]

    def handle_webhook(self, *, payload: bytes, signature: str) -> str:
        event = self._payments.parse_webhook(payload=payload, signature=signature)
        with self._transaction.atomic():
            if not self._event_log.record(event_id=event.id, event_type=event.type):
                return "duplicate"
            return self._apply(event)

    def _apply(self, event: StripeWebhookEvent) -> str:
        now = datetime.now(tz=UTC)
        if event.kind is WebhookEventKind.ACCOUNT_UPDATED and event.account:
            known = self._accounts.update_state(
                stripe_account_id=event.account_id, state=event.account
            )
            return "account_updated" if known else "unknown_account"
        if event.kind is WebhookEventKind.CHARGE_REFUNDED and event.refund:
            order = self._orders.lock_by_payment_intent(
                payment_intent_id=event.refund.payment_intent_id
            )
            if order is None:
                return "unknown_order"
            if not event.refund.fully_refunded or order.status is not OrderStatus.PAID:
                return "ignored"
            self._refunded(order, when=now)
            return "refunded"
        if event.checkout is None or event.checkout.mode != "payment":
            return "ignored"
        return self._apply_checkout(event.kind, event.checkout, now=now)

    def _apply_checkout(
        self,
        kind: WebhookEventKind | None,
        checkout: CheckoutSessionFacts,
        *,
        now: datetime,
    ) -> str:
        order = self._orders.lock_by_checkout(session_id=checkout.session_id)
        if order is None:
            return "unknown_order"
        match kind:
            case WebhookEventKind.CHECKOUT_COMPLETED if checkout.paid:
                return self._paid(order, checkout.payment_intent_id, when=now)
            case WebhookEventKind.CHECKOUT_COMPLETED:
                if order.status is OrderStatus.PENDING:
                    self._orders.mark(
                        pk=order.pk,
                        status=OrderStatus.AWAITING_PAYMENT,
                        payment_intent_id=checkout.payment_intent_id,
                    )
                return "awaiting_payment"
            case WebhookEventKind.CHECKOUT_ASYNC_SUCCEEDED:
                return self._paid(order, checkout.payment_intent_id, when=now)
            case WebhookEventKind.CHECKOUT_ASYNC_FAILED:
                if order.status is OrderStatus.AWAITING_PAYMENT:
                    self._orders.mark(pk=order.pk, status=OrderStatus.FAILED)
                return "failed"
            case WebhookEventKind.CHECKOUT_EXPIRED:
                if order.status is OrderStatus.PENDING:
                    self._orders.mark(pk=order.pk, status=OrderStatus.EXPIRED)
                return "expired"
        return "ignored"

    def _paid(self, order: OrderDTO, payment_intent_id: str, *, when: datetime) -> str:
        if order.status in {OrderStatus.PAID, OrderStatus.REFUNDED}:
            return "already_paid"
        # Stripe completed it, so the money is taken whatever we thought of
        # the hold: a session cannot complete after its expiry, so the seats
        # were still held when the buyer paid.
        self._orders.mark(
            pk=order.pk,
            status=OrderStatus.PAID,
            payment_intent_id=payment_intent_id,
            when=when,
        )
        self._orders.issue_tickets(
            order=order, codes=[_ticket_code() for _ in range(order.ticket_count)]
        )
        logger.info(
            "Ticket order paid: event=%s order=%s tickets=%s total=%s fee=%s",
            order.event_id,
            order.pk,
            order.ticket_count,
            order.total,
            order.platform_fee,
        )
        return "paid"

    def _refunded(self, order: OrderDTO, *, when: datetime) -> None:
        self._orders.mark(pk=order.pk, status=OrderStatus.REFUNDED, when=when)
        self._orders.void_tickets(order_pk=order.pk)
        logger.info(
            "Ticket order refunded: event=%s order=%s", order.event_id, order.pk
        )


class TicketPanelService(TicketPanelServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: TicketRepos,
        payments: TicketPaymentsProtocol,
    ) -> None:
        self._transaction = transaction
        self._ticket_types = repos.ticket_types
        self._orders = repos.orders
        self._accounts = repos.accounts
        self._plans = repos.plans
        self._payments = payments

    def fees_for(self, *, sphere_id: int, price: int) -> FeeBreakdownDTO:
        return FeeBreakdownDTO(
            price=price,
            platform_fee=platform_fee(
                price, plan=plan_kind(self._plans, sphere_id=sphere_id)
            ),
            estimated_stripe_fee=estimated_stripe_fee(price),
        )

    def page(self, *, sphere_id: int, event_id: int) -> TicketPanelDTO:
        now = datetime.now(tz=UTC)
        plan = plan_kind(self._plans, sphere_id=sphere_id)
        types = self._ticket_types.list_for_event(
            event_id=event_id, now=now, include_archived=True
        )
        orders = self._orders.list_for_event(event_id=event_id)
        paid = [order for order in orders if order.status is OrderStatus.PAID]
        bps = PLATFORM_FEE_BPS[plan]
        return TicketPanelDTO(
            payout_status=payout_status(self._accounts.read(sphere_id=sphere_id)),
            payments_available=self._payments.enabled,
            platform_fee_percent=f"{bps / 100:g}",
            rows=[
                TicketTypeRowDTO(
                    ticket_type=ticket_type,
                    fees=self.fees_for(sphere_id=sphere_id, price=ticket_type.price),
                )
                for ticket_type in types
                if not ticket_type.is_archived
            ],
            archived=[ticket_type for ticket_type in types if ticket_type.is_archived],
            summary=TicketSalesSummaryDTO(
                orders=len(paid),
                tickets=sum(order.ticket_count for order in paid),
                gross=sum(order.total for order in paid),
                platform_fees=sum(order.platform_fee for order in paid),
                estimated_stripe_fees=sum(
                    estimated_stripe_fee(order.total) for order in paid
                ),
            ),
            orders=orders,
        )

    def read_type(self, *, event_id: int, pk: int) -> TicketTypeDTO:
        ticket_type = self._ticket_types.read(
            event_id=event_id, pk=pk, now=datetime.now(tz=UTC)
        )
        if ticket_type is None:
            raise NotFoundError
        return ticket_type

    def create_type(self, *, event_id: int, data: TicketTypeData) -> TicketTypeDTO:
        with self._transaction.atomic():
            return self._ticket_types.create(
                {
                    **data,
                    "event_id": event_id,
                    "currency": DEFAULT_CURRENCY,
                    "order": self._ticket_types.next_order(event_id=event_id),
                }
            )

    def update_type(self, *, event_id: int, pk: int, data: TicketTypeData) -> None:
        with self._transaction.atomic():
            if not self._ticket_types.update(event_id=event_id, pk=pk, data=data):
                raise NotFoundError

    def set_archived(self, *, event_id: int, pk: int, archived: bool) -> None:
        with self._transaction.atomic():
            if not self._ticket_types.set_archived(
                event_id=event_id, pk=pk, archived=archived
            ):
                raise NotFoundError

    def refund(self, *, event_id: int, order_pk: int) -> RefundOutcome:
        order = self._orders.read_for_event(event_id=event_id, pk=order_pk)
        if order is None:
            raise NotFoundError
        if order.status is not OrderStatus.PAID or not order.stripe_payment_intent_id:
            return RefundOutcome.NOT_REFUNDABLE
        try:
            self._payments.refund(
                account_id=order.stripe_account_id,
                payment_intent_id=order.stripe_payment_intent_id,
            )
        except PaymentProviderError:
            return RefundOutcome.PROVIDER_ERROR
        # The charge.refunded webhook would do this too; doing it now means
        # the organizer sees the refund on the page they are looking at.
        with self._transaction.atomic():
            self._orders.mark(
                pk=order.pk, status=OrderStatus.REFUNDED, when=datetime.now(tz=UTC)
            )
            self._orders.void_tickets(order_pk=order.pk)
        logger.info(
            "Ticket order refunded from panel: event=%s order=%s", event_id, order.pk
        )
        return RefundOutcome.REFUNDED
