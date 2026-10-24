"""Ticket sales: the sphere's payout account, the shop, the panel, the webhook.

Every id a request supplies is scoped here, not in the view: ticket type ids
to the event the gate resolved, order references to their event and to
whoever may see them (`_viewable`), order ids to the panel's event. Stripe's
ids arrive only in signed webhooks.

An order moves only along `specs.tickets.ORDER_TRANSITIONS`, and every write
is guarded by the status it moves from, so a redelivered or reordered webhook
finds the order already past it and changes nothing.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import (
    AccountEvent,
    CheckoutEvent,
    CheckoutStage,
    PaymentProviderError,
    RefundEvent,
    WebhookOutcome,
)
from ludamus.pacts.tickets import (
    ABANDONED_STATUSES,
    DEFAULT_CURRENCY,
    MAX_TICKETS_PER_ORDER,
    TICKET_CODE_LENGTH,
    AbandonOutcome,
    BuyerOrderDTO,
    CheckoutLine,
    CheckoutOutcome,
    CheckoutRequest,
    CheckoutStartDTO,
    ClaimOutcome,
    EventShopDTO,
    OrderLinkMail,
    OrderStatus,
    PayoutPageDTO,
    PayoutServiceProtocol,
    PayoutStatus,
    RefundOutcome,
    TicketPanelDTO,
    TicketPanelServiceProtocol,
    TicketSalesServiceProtocol,
    TicketSalesSummaryDTO,
    TicketTypeRowDTO,
)
from ludamus.specs.billing import current_terms
from ludamus.specs.tickets import (
    CHECKOUT_HOLD,
    GUEST_CHECKOUT_WINDOW_SECONDS,
    GUEST_CHECKOUTS_PER_WINDOW,
    PANEL_ORDERS_SHOWN,
    WEBHOOK_GRACE,
    checkout_refusal,
    estimated_stripe_fees,
    fee_breakdown,
    offer_for,
    order_page_state,
    payout_status,
    platform_fee,
    platform_fee_percent,
    sources_of,
)

if TYPE_CHECKING:
    from ludamus.pacts import EventDTO
    from ludamus.pacts.billing import SpherePlanRepositoryProtocol
    from ludamus.pacts.legacy import CacheProtocol
    from ludamus.pacts.payment_api import StripeWebhookEvent
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.tickets import (
        CheckoutUrls,
        OrderChanges,
        OrderDTO,
        OrderLineData,
        OwnedTicketDTO,
        PayoutAccountDTO,
        PayoutAccountRepositoryProtocol,
        TicketMailerProtocol,
        TicketOrderRepositoryProtocol,
        TicketPaymentsProtocol,
        TicketRepos,
        TicketTypeData,
        TicketTypeDTO,
    )

logger = logging.getLogger(__name__)

# Unambiguous on a phone screen and read aloud at a door: no 0/O, 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _ticket_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(TICKET_CODE_LENGTH))


def _holds_after(now: datetime) -> datetime:
    return now - WEBHOOK_GRACE


def _order_reference() -> str:
    # The order page's only key for a guest: unguessable, and short in a URL.
    return secrets.token_urlsafe(16)


def _fee_bps(plans: SpherePlanRepositoryProtocol, *, sphere_id: int) -> int:
    return current_terms(
        plans.read(sphere_id=sphere_id), now=datetime.now(tz=UTC)
    ).ticket_fee_bps


def _viewable(order: OrderDTO, *, viewer_id: int | None) -> bool:
    # A guest's order is its link's; a claimed one is its holder's alone.
    return order.buyer_id is None or order.buyer_id == viewer_id


def _move(
    orders: TicketOrderRepositoryProtocol,
    *,
    pk: int,
    to: OrderStatus,
    changes: OrderChanges | None = None,
) -> bool:
    # The only way an order changes status: from wherever ORDER_TRANSITIONS
    # allows, and not at all if it has moved on since it was read.
    return orders.move(pk=pk, to=to, allowed_from=sources_of(to), changes=changes or {})


def _buyer_email(event: CheckoutEvent) -> OrderChanges:
    # What the buyer typed into Checkout: a guest's only address.
    return {"email": event.email} if event.email else {}


def _record_refund(
    orders: TicketOrderRepositoryProtocol, *, order: OrderDTO, now: datetime
) -> bool:
    if not _move(
        orders, pk=order.pk, to=OrderStatus.REFUNDED, changes={"refunded_at": now}
    ):
        return False
    logger.info("Ticket order refunded: event=%s order=%s", order.event_id, order.pk)
    return True


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
        if (account := self._accounts.read(sphere_id=sphere_id)) is None:
            account_id = self._payments.create_account(sphere_id=sphere_id, email=email)
            with self._transaction.atomic():
                account = self._accounts.create_or_read(
                    sphere_id=sphere_id, stripe_account_id=account_id
                )
            logger.info(
                "Payout account connected: sphere=%s account=%s",
                sphere_id,
                account.stripe_account_id,
            )
        return self._payments.onboarding_url(
            account_id=account.stripe_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )

    def resume_onboarding_url(
        self, *, sphere_id: int, refresh_url: str, return_url: str
    ) -> str | None:
        if (account := self._accounts.read(sphere_id=sphere_id)) is None:
            return None
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
        mailer: TicketMailerProtocol,
        cache: CacheProtocol,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._payments = payments
        self._mailer = mailer
        self._cache = cache

    def shop(self, *, event: EventDTO, viewer_id: int | None) -> EventShopDTO:
        now = datetime.now(tz=UTC)
        types = self._repos.ticket_types.list_for_event(
            event_id=event.pk, holds_after=_holds_after(now)
        )
        # Counted even with nothing on sale: tickets sold before every type
        # was taken off sale still admit their holders.
        viewer_ticket_count = (
            0
            if viewer_id is None
            else self._repos.orders.count_valid_tickets(
                event_id=event.pk, holder_id=viewer_id
            )
        )
        return EventShopDTO(
            offers=[
                offer_for(ticket_type, now=now, closes_at=event.end_time)
                for ticket_type in types
            ],
            # Most events are free: with no ticket types, the account is not read.
            accepting_payments=bool(types)
            and self._accepting_payments(
                self._repos.accounts.read(sphere_id=event.sphere_id)
            ),
            viewer_ticket_count=viewer_ticket_count,
        )

    def _accepting_payments(self, account: PayoutAccountDTO | None) -> bool:
        return self._payments.enabled and payout_status(account) is PayoutStatus.ACTIVE

    def guest_checkout_allowed(self, *, ip: str, event_id: int) -> bool:
        # NOTE: get-then-set races, so a burst may get a checkout or two past
        # the limit; it bounds a script, not a person double-clicking.
        key = f"guest_checkout:{event_id}:{ip}"
        started = self._cache.get(key)
        count = started if isinstance(started, int) else 0
        if count >= GUEST_CHECKOUTS_PER_WINDOW:
            logger.warning("Guest checkouts over the limit: event=%s", event_id)
            return False
        self._cache.set(key, count + 1, timeout=GUEST_CHECKOUT_WINDOW_SECONDS)
        return True

    def start_checkout(
        self,
        *,
        event: EventDTO,
        buyer_id: int | None,
        email: str,
        quantities: dict[int, int],
        urls: CheckoutUrls,
    ) -> CheckoutStartDTO:
        wanted = {pk: count for pk, count in quantities.items() if count > 0}
        if not wanted:
            return CheckoutStartDTO(outcome=CheckoutOutcome.NOTHING_SELECTED)
        if sum(wanted.values()) > MAX_TICKETS_PER_ORDER:
            return CheckoutStartDTO(outcome=CheckoutOutcome.TOO_MANY)
        account = self._repos.accounts.read(sphere_id=event.sphere_id)
        if account is None or not self._accepting_payments(account):
            return CheckoutStartDTO(outcome=CheckoutOutcome.SALES_CLOSED)

        with self._transaction.atomic():
            locked = self._repos.ticket_types.lock_for_event(
                event_id=event.pk, holds_after=_holds_after(datetime.now(tz=UTC))
            )
            # Read the clock after the lock: a queue of buyers in a ticket drop
            # must not eat into the margin over Stripe's 30-minute minimum.
            now = datetime.now(tz=UTC)
            types = {ticket_type.pk: ticket_type for ticket_type in locked}
            lines: list[OrderLineData] = []
            for pk, count in sorted(wanted.items()):
                # An id from another event, or archived, is simply not here.
                if (ticket_type := types.get(pk)) is None:
                    return CheckoutStartDTO(outcome=CheckoutOutcome.NOT_ON_SALE)
                offer = offer_for(ticket_type, now=now, closes_at=event.end_time)
                if (refused := checkout_refusal(offer, count=count)) is not None:
                    return CheckoutStartDTO(outcome=refused)
                lines.append(
                    {
                        "ticket_type_id": pk,
                        "quantity": count,
                        "unit_price": ticket_type.price,
                    }
                )
            total = sum(line["quantity"] * line["unit_price"] for line in lines)
            order = self._repos.orders.create(
                {
                    "reference": _order_reference(),
                    "event_id": event.pk,
                    "buyer_id": buyer_id,
                    "email": email,
                    "currency": DEFAULT_CURRENCY,
                    "total": total,
                    "platform_fee": platform_fee(
                        total,
                        bps=_fee_bps(self._repos.plans, sphere_id=event.sphere_id),
                    ),
                    "stripe_account_id": account.stripe_account_id,
                    "hold_until": now + CHECKOUT_HOLD,
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
                    success_url=urls.success(order.reference),
                    cancel_url=urls.cancel(order.reference),
                    expires_at=order.hold_until,
                )
            )
        except PaymentProviderError:
            with self._transaction.atomic():
                _move(self._repos.orders, pk=order.pk, to=OrderStatus.FAILED)
            return CheckoutStartDTO(outcome=CheckoutOutcome.PROVIDER_ERROR)
        with self._transaction.atomic():
            self._repos.orders.attach_checkout(pk=order.pk, session_id=session.id)
        logger.info(
            "Ticket checkout started: event=%s order=%s tickets=%s total=%s guest=%s",
            event.pk,
            order.pk,
            order.ticket_count,
            order.total,
            buyer_id is None,
        )
        return CheckoutStartDTO(outcome=CheckoutOutcome.STARTED, url=session.url)

    def order(
        self, *, event_id: int, reference: str, viewer_id: int | None
    ) -> BuyerOrderDTO:
        order = self._visible(
            event_id=event_id, reference=reference, viewer_id=viewer_id
        )
        return BuyerOrderDTO(
            order=order, state=order_page_state(order, now=datetime.now(tz=UTC))
        )

    def _visible(
        self, *, event_id: int, reference: str, viewer_id: int | None
    ) -> OrderDTO:
        order = self._repos.orders.read_by_reference(reference=reference)
        if (
            order is None
            or order.event_id != event_id
            or not _viewable(order, viewer_id=viewer_id)
        ):
            raise NotFoundError
        return order

    def claim_order(
        self, *, event_id: int, reference: str, user_id: int
    ) -> ClaimOutcome:
        with self._transaction.atomic():
            order = self._repos.orders.lock_by_reference(reference=reference)
            if (
                order is None
                or order.event_id != event_id
                or not _viewable(order, viewer_id=user_id)
            ):
                raise NotFoundError
            if order.buyer_id == user_id:
                return ClaimOutcome.ALREADY_YOURS
            self._repos.orders.claim(pk=order.pk, buyer_id=user_id)
        logger.info("Ticket order claimed: order=%s user=%s", order.pk, user_id)
        return ClaimOutcome.CLAIMED

    def abandon_checkout(
        self, *, event_id: int, reference: str, viewer_id: int | None
    ) -> AbandonOutcome:
        order = self._visible(
            event_id=event_id, reference=reference, viewer_id=viewer_id
        )
        if order.status is not OrderStatus.PENDING:
            return AbandonOutcome.SETTLED
        if order.stripe_checkout_session_id:
            try:
                self._payments.expire_checkout(
                    account_id=order.stripe_account_id,
                    session_id=order.stripe_checkout_session_id,
                )
            except PaymentProviderError:
                # Completed in another tab, or Stripe is down: its webhook
                # settles the order, and the hold frees the seats meanwhile.
                logger.warning("Ticket checkout not expired: order=%s", order.pk)
                return AbandonOutcome.UNCONFIRMED
        with self._transaction.atomic():
            expired = _move(self._repos.orders, pk=order.pk, to=OrderStatus.EXPIRED)
        logger.info("Ticket checkout abandoned: order=%s expired=%s", order.pk, expired)
        return AbandonOutcome.CANCELLED if expired else AbandonOutcome.SETTLED

    def owned_tickets(self, *, sphere_id: int, holder_id: int) -> list[OwnedTicketDTO]:
        return self._repos.orders.list_owned_tickets(
            sphere_id=sphere_id, holder_id=holder_id
        )

    def handle_webhook(self, *, payload: bytes, signature: str) -> WebhookOutcome:
        event = self._payments.parse_webhook(payload=payload, signature=signature)
        with self._transaction.atomic():
            return self._apply(event)

    def _apply(self, event: StripeWebhookEvent) -> WebhookOutcome:
        match event:
            case AccountEvent():
                known = self._repos.accounts.update_state(
                    stripe_account_id=event.account_id, state=event.state
                )
                return (
                    WebhookOutcome.ACCOUNT_UPDATED if known else WebhookOutcome.NOT_OURS
                )
            case RefundEvent():
                return self._refunded(event)
            case CheckoutEvent():
                return self._checkout(event)
        return WebhookOutcome.NOT_OURS

    def _refunded(self, event: RefundEvent) -> WebhookOutcome:
        order = self._repos.orders.lock_by_payment_intent(
            payment_intent_id=event.payment_intent_id
        )
        if order is None:
            return WebhookOutcome.NOT_OURS
        if not event.fully_refunded:
            logger.info("Ticket order refunded in part: order=%s", order.pk)
            return WebhookOutcome.PARTLY_REFUNDED
        if not _record_refund(
            self._repos.orders, order=order, now=datetime.now(tz=UTC)
        ):
            return WebhookOutcome.STALE
        return WebhookOutcome.REFUNDED

    def _checkout(self, event: CheckoutEvent) -> WebhookOutcome:
        order = self._repos.orders.lock_by_checkout(session_id=event.session_id)
        if order is None:
            return WebhookOutcome.NOT_OURS
        match event.stage:
            case CheckoutStage.COMPLETED if not event.paid:
                outcome = self._settle(
                    pk=order.pk,
                    to=OrderStatus.AWAITING_PAYMENT,
                    outcome=WebhookOutcome.AWAITING_PAYMENT,
                    changes={
                        "stripe_payment_intent_id": event.payment_intent_id,
                        **_buyer_email(event),
                    },
                )
                if outcome is WebhookOutcome.AWAITING_PAYMENT:
                    self._send_link(order, event=event)
                return outcome
            case CheckoutStage.COMPLETED | CheckoutStage.ASYNC_SUCCEEDED:
                outcome = self._paid(order=order, event=event)
                if (
                    outcome is WebhookOutcome.PAID
                    and event.stage is CheckoutStage.COMPLETED
                ):
                    self._send_link(order, event=event)
                return outcome
            case CheckoutStage.ASYNC_FAILED:
                # Final even if it beats the "completed" that preceded it:
                # that one then finds the order failed and holds nothing.
                return self._settle(
                    pk=order.pk, to=OrderStatus.FAILED, outcome=WebhookOutcome.FAILED
                )
            case CheckoutStage.EXPIRED:
                return self._settle(
                    pk=order.pk, to=OrderStatus.EXPIRED, outcome=WebhookOutcome.EXPIRED
                )
            case _:
                assert_never(event.stage)

    def _settle(
        self,
        *,
        pk: int,
        to: OrderStatus,
        outcome: WebhookOutcome,
        changes: OrderChanges | None = None,
    ) -> WebhookOutcome:
        moved = _move(self._repos.orders, pk=pk, to=to, changes=changes)
        return outcome if moved else WebhookOutcome.STALE

    def _send_link(self, order: OrderDTO, *, event: CheckoutEvent) -> None:
        # Once per order, when Checkout completes: a bank transfer's page is
        # worth having while the money is on its way, too.
        if not (email := event.email or order.email):
            logger.warning("Ticket order has no email to send it to: %s", order.pk)
            return
        self._mailer.send_order_link(
            OrderLinkMail(
                email=email,
                event_id=order.event_id,
                event_name=order.event_name,
                event_slug=order.event_slug,
                reference=order.reference,
                claimable=order.buyer_id is None,
            )
        )

    def _paid(self, *, order: OrderDTO, event: CheckoutEvent) -> WebhookOutcome:
        payment_intent_id = event.payment_intent_id
        if not _move(
            self._repos.orders,
            pk=order.pk,
            to=OrderStatus.PAID,
            changes={
                "stripe_payment_intent_id": payment_intent_id,
                "paid_at": datetime.now(tz=UTC),
                **_buyer_email(event),
            },
        ):
            if order.status in ABANDONED_STATUSES:
                return self._refund_late(order, payment_intent_id=payment_intent_id)
            return WebhookOutcome.STALE
        self._repos.orders.issue_tickets(
            order=order,
            tickets=[
                {"ticket_type_id": line.ticket_type_id, "code": _ticket_code()}
                for line in order.lines
                for _ in range(line.quantity)
            ],
        )
        logger.info(
            "Ticket order paid: event=%s order=%s tickets=%s total=%s fee=%s",
            order.event_id,
            order.pk,
            order.ticket_count,
            order.total,
            order.platform_fee,
        )
        self._warn_if_oversold(order)
        return WebhookOutcome.PAID

    def _refund_late(
        self, order: OrderDTO, *, payment_intent_id: str
    ) -> WebhookOutcome:
        # Stripe took money for an order we gave up on. Its seats may be gone,
        # so nothing is issued and the money goes straight back; if Stripe
        # refuses, the error answers the webhook and Stripe retries it.
        self._payments.refund_once(
            account_id=order.stripe_account_id, payment_intent_id=payment_intent_id
        )
        logger.warning(
            "Ticket order paid after it %s, refunded: event=%s order=%s",
            order.status,
            order.event_id,
            order.pk,
        )
        return WebhookOutcome.REFUNDED

    def _warn_if_oversold(self, order: OrderDTO) -> None:
        bought = {line.ticket_type_id for line in order.lines}
        for ticket_type in self._repos.ticket_types.list_for_event(
            event_id=order.event_id,
            holds_after=_holds_after(datetime.now(tz=UTC)),
            include_archived=True,
        ):
            if (
                ticket_type.pk in bought
                and ticket_type.quantity is not None
                and ticket_type.sold > ticket_type.quantity
            ):
                logger.warning(
                    "Ticket type oversold: event=%s type=%s sold=%s cap=%s",
                    order.event_id,
                    ticket_type.pk,
                    ticket_type.sold,
                    ticket_type.quantity,
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

    def page(self, *, sphere_id: int, event_id: int) -> TicketPanelDTO:
        bps = _fee_bps(self._plans, sphere_id=sphere_id)
        types = self._ticket_types.list_for_event(
            event_id=event_id,
            holds_after=_holds_after(datetime.now(tz=UTC)),
            include_archived=True,
        )
        orders = self._orders.list_for_event(
            event_id=event_id, limit=PANEL_ORDERS_SHOWN + 1
        )
        paid = self._orders.paid_totals(event_id=event_id)
        return TicketPanelDTO(
            payout_status=payout_status(self._accounts.read(sphere_id=sphere_id)),
            payments_available=self._payments.enabled,
            platform_fee_percent=platform_fee_percent(bps),
            rows=[
                TicketTypeRowDTO(
                    ticket_type=ticket_type,
                    fees=fee_breakdown(ticket_type.price, bps=bps),
                )
                for ticket_type in types
                if not ticket_type.is_archived
            ],
            archived=[ticket_type for ticket_type in types if ticket_type.is_archived],
            summary=TicketSalesSummaryDTO(
                orders=paid.orders,
                tickets=paid.tickets,
                gross=paid.gross,
                platform_fees=paid.platform_fees,
                estimated_stripe_fees=estimated_stripe_fees(
                    gross=paid.gross, orders=paid.orders
                ),
            ),
            orders=orders[:PANEL_ORDERS_SHOWN],
            more_orders=len(orders) > PANEL_ORDERS_SHOWN,
        )

    def read_type(self, *, event_id: int, pk: int) -> TicketTypeDTO:
        ticket_type = self._ticket_types.read(
            event_id=event_id, pk=pk, holds_after=_holds_after(datetime.now(tz=UTC))
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
        # Under the order's lock, so the charge.refunded webhook for this very
        # refund waits and then finds it done.
        with self._transaction.atomic():
            order = self._orders.lock_for_event(event_id=event_id, pk=order_pk)
            if order is None:
                raise NotFoundError
            if (
                order.status is not OrderStatus.PAID
                or not order.stripe_payment_intent_id
            ):
                return RefundOutcome.NOT_REFUNDABLE
            try:
                self._payments.refund(
                    account_id=order.stripe_account_id,
                    payment_intent_id=order.stripe_payment_intent_id,
                )
            except PaymentProviderError:
                return RefundOutcome.PROVIDER_ERROR
            _record_refund(self._orders, order=order, now=datetime.now(tz=UTC))
        return RefundOutcome.REFUNDED
