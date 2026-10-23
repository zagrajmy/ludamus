"""Ticket sales: what an event sells, who bought it, and where the money goes.

An event sells tickets only when an organizer adds ticket types to it; an event
without any is free and none of this shows. Buyers pay through Stripe Checkout
on the sphere's own connected Stripe account (its `PayoutAccount`), and
Zagrajmy keeps a share of each order as Stripe's application fee. See
docs/rfc/0002-ticketing.md.

Money is integer minor units (grosze) everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts.billing import SpherePlanRepositoryProtocol
    from ludamus.pacts.legacy import EventDTO
    from ludamus.pacts.payment_api import (
        AccountState,
        StripeWebhookEvent,
        WebhookOutcome,
    )

DEFAULT_CURRENCY = "pln"
# Minor units per unit, as a power of ten: grosze to złoty is scaleb(-2).
MONEY_DECIMAL_PLACES = 2
# Stripe's smallest PLN charge is 2,00 zł; a cheaper ticket could never be paid.
MIN_TICKET_PRICE = 200
TICKET_TYPE_NAME_MAX_LENGTH = 120
TICKET_TYPE_DESCRIPTION_MAX_LENGTH = 500
MAX_TICKETS_PER_ORDER = 10
# Stripe refuses a charge over 999 999,99 zł; a full order must stay under it.
MAX_TICKET_PRICE = 99_999_999 // MAX_TICKETS_PER_ORDER
TICKET_CODE_LENGTH = 10


class OrderStatus(StrEnum):
    # Seats held while the buyer is in Stripe Checkout, until `hold_until`.
    PENDING = "pending"
    # Checkout finished with a delayed payment method; seats stay held until
    # Stripe says it settled or failed.
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    EXPIRED = "expired"
    FAILED = "failed"
    REFUNDED = "refunded"


# Seats an order of these statuses takes: sold outright, or held however long
# the money takes to settle. A PENDING order also holds its seats, but only
# until its hold (and the webhook grace after it) passes.
SOLD_STATUSES = frozenset({OrderStatus.PAID})
SETTLING_STATUSES = frozenset({OrderStatus.AWAITING_PAYMENT})
CHECKOUT_STATUSES = frozenset({OrderStatus.PENDING})
# The orders the panel lists: abandoned checkouts are noise there.
LEDGER_STATUSES = frozenset(
    {OrderStatus.PAID, OrderStatus.REFUNDED, OrderStatus.AWAITING_PAYMENT}
)


class AbandonOutcome(StrEnum):
    CANCELLED = "cancelled"
    # Paid, expired or failed already: the order page says which.
    SETTLED = "settled"
    # Stripe would not expire the session, or could not be reached; its
    # webhook will settle the order.
    UNCONFIRMED = "unconfirmed"


class PayoutStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    # An account exists but Stripe still wants details before it may charge.
    INCOMPLETE = "incomplete"
    ACTIVE = "active"


class OfferState(StrEnum):
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"
    NOT_YET = "not_yet"
    ENDED = "ended"


class CheckoutOutcome(StrEnum):
    STARTED = "started"
    NOTHING_SELECTED = "nothing_selected"
    TOO_MANY = "too_many"
    NOT_ON_SALE = "not_on_sale"
    SOLD_OUT = "sold_out"
    SALES_CLOSED = "sales_closed"
    PROVIDER_ERROR = "provider_error"


class RefundOutcome(StrEnum):
    REFUNDED = "refunded"
    NOT_REFUNDABLE = "not_refundable"
    PROVIDER_ERROR = "provider_error"


# --- payout account ---------------------------------------------------------


class PayoutAccountDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stripe_account_id: str
    details_submitted: bool
    charges_enabled: bool
    payouts_enabled: bool


class PayoutPageDTO(BaseModel):
    status: PayoutStatus
    # Stripe is configured on this deployment at all.
    available: bool
    payouts_enabled: bool


class PayoutAccountRepositoryProtocol(Protocol):
    @staticmethod
    def read(*, sphere_id: int) -> PayoutAccountDTO | None: ...
    @staticmethod
    def create_or_read(*, sphere_id: int, stripe_account_id: str) -> PayoutAccountDTO:
        """Store the account; if a concurrent request stored one, return that."""

    @staticmethod
    def update_state(*, stripe_account_id: str, state: AccountState) -> bool: ...


# --- ticket types -----------------------------------------------------------


class TicketTypeDTO(BaseModel):
    pk: int
    event_id: int
    name: str
    description: str
    price: int
    currency: str
    # None: no cap of its own, the event sells as many as are bought.
    quantity: int | None
    sales_start: datetime | None
    sales_end: datetime | None
    is_archived: bool
    order: int
    # Seats in paid orders, and seats held by orders still in Checkout.
    sold: int
    held: int


class TicketTypeData(TypedDict):
    name: str
    description: str
    price: int
    quantity: int | None
    sales_start: datetime | None
    sales_end: datetime | None


class TicketTypeCreateData(TicketTypeData):
    event_id: int
    currency: str
    order: int


class TicketOfferDTO(BaseModel):
    """A ticket type as a buyer sees it."""

    ticket_type: TicketTypeDTO
    state: OfferState
    # None when the type has no cap; never negative.
    remaining: int | None
    # Few enough left that the shop says how many.
    few_left: bool
    max_quantity: int


class EventShopDTO(BaseModel):
    offers: list[TicketOfferDTO]
    # The sphere's Stripe account can take payments right now.
    accepting_payments: bool
    viewer_ticket_count: int

    @property
    def has_tickets(self) -> bool:
        return bool(self.offers)

    @property
    def on_sale(self) -> bool:
        return self.accepting_payments and any(
            offer.state is OfferState.ON_SALE for offer in self.offers
        )


# --- orders and tickets -----------------------------------------------------


class OrderLineDTO(BaseModel):
    ticket_type_id: int
    ticket_type_name: str
    quantity: int
    unit_price: int

    @property
    def subtotal(self) -> int:
        return self.quantity * self.unit_price


class TicketDTO(BaseModel):
    pk: int
    code: str
    ticket_type_name: str
    is_void: bool


class OrderDTO(BaseModel):
    pk: int
    event_id: int
    event_name: str
    event_slug: str
    buyer_id: int | None
    buyer_name: str
    email: str
    status: OrderStatus
    currency: str
    total: int
    platform_fee: int
    stripe_account_id: str
    stripe_checkout_session_id: str
    stripe_payment_intent_id: str
    hold_until: datetime
    paid_at: datetime | None
    refunded_at: datetime | None
    creation_time: datetime
    lines: list[OrderLineDTO]
    tickets: list[TicketDTO]

    @property
    def ticket_count(self) -> int:
        return sum(line.quantity for line in self.lines)


class BuyerOrderDTO(BaseModel):
    """An order as its buyer's order page shows it."""

    order: OrderDTO
    # Stripe has not said yet whether it was paid.
    confirming: bool
    # Stripe is likely to say within seconds, so the page checks back. Card
    # and BLIK settle that fast; a bank transfer can take days, and a hold
    # past its end means the webhook is late, so neither is polled.
    polling: bool


class OwnedTicketDTO(BaseModel):
    """A ticket on its holder's "My tickets" page."""

    code: str
    ticket_type_name: str
    order_pk: int
    event_name: str
    event_slug: str
    event_start: datetime
    event_end: datetime


class OrderLineData(TypedDict):
    ticket_type_id: int
    quantity: int
    unit_price: int


class OrderChanges(TypedDict, total=False):
    # What a move records besides the status.
    stripe_payment_intent_id: str
    paid_at: datetime
    refunded_at: datetime


class OrderCreateData(TypedDict):
    event_id: int
    buyer_id: int
    email: str
    currency: str
    total: int
    platform_fee: int
    stripe_account_id: str
    hold_until: datetime
    lines: list[OrderLineData]


class PaidTotalsDTO(BaseModel):
    """What an event's paid orders add up to."""

    orders: int
    tickets: int
    gross: int
    platform_fees: int


class OrderRowDTO(BaseModel):
    """An order as the panel lists it."""

    pk: int
    buyer_name: str
    email: str
    status: OrderStatus
    currency: str
    total: int
    creation_time: datetime
    lines: list[OrderLineDTO]


class TicketSalesSummaryDTO(BaseModel):
    """An event's takings, as the panel totals them over paid orders."""

    orders: int
    tickets: int
    gross: int
    platform_fees: int
    # Our estimate of Stripe's processing fees; the real figure is in the
    # organizer's Stripe dashboard.
    estimated_stripe_fees: int

    @property
    def estimated_fees(self) -> int:
        return self.platform_fees + self.estimated_stripe_fees

    @property
    def estimated_net(self) -> int:
        return self.gross - self.estimated_fees


class FeeBreakdownDTO(BaseModel):
    price: int
    platform_fee: int
    estimated_stripe_fee: int

    @property
    def estimated_net(self) -> int:
        return self.price - self.platform_fee - self.estimated_stripe_fee


class TicketTypeRowDTO(BaseModel):
    ticket_type: TicketTypeDTO
    fees: FeeBreakdownDTO


class TicketPanelDTO(BaseModel):
    payout_status: PayoutStatus
    payments_available: bool
    platform_fee_percent: Decimal
    rows: list[TicketTypeRowDTO]
    archived: list[TicketTypeDTO]
    summary: TicketSalesSummaryDTO
    # The newest orders; `more_orders` says older ones were left out.
    orders: list[OrderRowDTO]
    more_orders: bool


class CheckoutLine(BaseModel):
    name: str
    unit_amount: int
    quantity: int


class CheckoutRequest(BaseModel):
    account_id: str
    order_pk: int
    currency: str
    lines: list[CheckoutLine]
    application_fee: int
    customer_email: str
    success_url: str
    cancel_url: str
    expires_at: datetime


class CheckoutSessionDTO(BaseModel):
    id: str
    url: str


class CheckoutStartDTO(BaseModel):
    outcome: CheckoutOutcome
    url: str = ""


@dataclass(frozen=True)
class CheckoutUrls:
    """Where Stripe sends the buyer back, given the order's pk."""

    success: Callable[[int], str]
    cancel: Callable[[int], str]


class TicketTypeRepositoryProtocol(Protocol):
    # `holds_after`: a pending order's seats count as held while its
    # `hold_until` is later than this.
    @staticmethod
    def list_for_event(
        *, event_id: int, holds_after: datetime, include_archived: bool = False
    ) -> list[TicketTypeDTO]: ...
    @staticmethod
    def lock_for_event(
        *, event_id: int, holds_after: datetime
    ) -> list[TicketTypeDTO]: ...
    @staticmethod
    def read(
        *, event_id: int, pk: int, holds_after: datetime
    ) -> TicketTypeDTO | None: ...
    @staticmethod
    def create(data: TicketTypeCreateData) -> TicketTypeDTO: ...
    @staticmethod
    def update(*, event_id: int, pk: int, data: TicketTypeData) -> bool: ...
    @staticmethod
    def set_archived(*, event_id: int, pk: int, archived: bool) -> bool: ...
    @staticmethod
    def next_order(*, event_id: int) -> int: ...


class TicketOrderRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: OrderCreateData) -> OrderDTO: ...
    @staticmethod
    def attach_checkout(*, pk: int, session_id: str) -> None: ...
    @staticmethod
    def read_for_buyer(*, buyer_id: int, pk: int) -> OrderDTO | None: ...
    @staticmethod
    def lock_for_event(*, event_id: int, pk: int) -> OrderDTO | None: ...
    @staticmethod
    def lock_by_checkout(*, session_id: str) -> OrderDTO | None: ...
    @staticmethod
    def lock_by_payment_intent(*, payment_intent_id: str) -> OrderDTO | None: ...
    @staticmethod
    def list_for_event(*, event_id: int, limit: int) -> list[OrderRowDTO]: ...
    @staticmethod
    def paid_totals(*, event_id: int) -> PaidTotalsDTO: ...

    @staticmethod
    def move(
        *,
        pk: int,
        to: OrderStatus,
        allowed_from: frozenset[OrderStatus],
        changes: OrderChanges,
    ) -> bool:
        """Write only if the order is still in one of `allowed_from`; say if it did."""

    @staticmethod
    def issue_tickets(*, order: OrderDTO, codes: list[str]) -> None: ...
    @staticmethod
    def void_tickets(*, order_pk: int) -> None: ...
    @staticmethod
    def count_valid_tickets(*, event_id: int, holder_id: int) -> int: ...
    @staticmethod
    def list_owned_tickets(
        *, sphere_id: int, holder_id: int
    ) -> list[OwnedTicketDTO]: ...


class TicketPaymentsProtocol(Protocol):
    """Organizers' connected Stripe accounts: onboarding, Checkout, refunds."""

    @property
    def enabled(self) -> bool: ...
    def create_account(self, *, sphere_id: int, email: str) -> str: ...
    def onboarding_url(
        self, *, account_id: str, refresh_url: str, return_url: str
    ) -> str: ...
    def read_account(self, *, account_id: str) -> AccountState: ...
    def create_checkout(self, request: CheckoutRequest) -> CheckoutSessionDTO: ...
    def expire_checkout(self, *, account_id: str, session_id: str) -> None: ...
    def refund(self, *, account_id: str, payment_intent_id: str) -> None: ...
    def refund_once(self, *, account_id: str, payment_intent_id: str) -> None:
        """Refund keyed by the payment: a retry replays the first answer."""

    def parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> StripeWebhookEvent: ...


# --- services ---------------------------------------------------------------


@dataclass
class TicketRepos:
    ticket_types: TicketTypeRepositoryProtocol
    orders: TicketOrderRepositoryProtocol
    accounts: PayoutAccountRepositoryProtocol
    plans: SpherePlanRepositoryProtocol


class PayoutServiceProtocol(Protocol):
    def page(self, *, sphere_id: int) -> PayoutPageDTO: ...
    def onboarding_url(
        self, *, sphere_id: int, email: str, refresh_url: str, return_url: str
    ) -> str: ...
    def resume_onboarding_url(
        self, *, sphere_id: int, refresh_url: str, return_url: str
    ) -> str | None: ...
    def refresh(self, *, sphere_id: int) -> PayoutPageDTO: ...


class TicketSalesServiceProtocol(Protocol):
    def shop(self, *, event: EventDTO, viewer_id: int | None) -> EventShopDTO: ...
    def start_checkout(
        self,
        *,
        event: EventDTO,
        buyer_id: int,
        email: str,
        quantities: dict[int, int],
        urls: CheckoutUrls,
    ) -> CheckoutStartDTO: ...
    def order(self, *, buyer_id: int, event_id: int, pk: int) -> BuyerOrderDTO: ...
    def abandon_checkout(
        self, *, buyer_id: int, event_id: int, pk: int
    ) -> AbandonOutcome: ...
    def owned_tickets(
        self, *, sphere_id: int, holder_id: int
    ) -> list[OwnedTicketDTO]: ...
    def handle_webhook(self, *, payload: bytes, signature: str) -> WebhookOutcome: ...


class TicketPanelServiceProtocol(Protocol):
    def page(self, *, sphere_id: int, event_id: int) -> TicketPanelDTO: ...
    def read_type(self, *, event_id: int, pk: int) -> TicketTypeDTO: ...
    def create_type(self, *, event_id: int, data: TicketTypeData) -> TicketTypeDTO: ...
    def update_type(self, *, event_id: int, pk: int, data: TicketTypeData) -> None: ...
    def set_archived(self, *, event_id: int, pk: int, archived: bool) -> None: ...
    def refund(self, *, event_id: int, order_pk: int) -> RefundOutcome: ...
