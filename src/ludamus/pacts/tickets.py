"""Ticket sales: what an event sells, who bought it, and where the money goes.

An event sells tickets only when an organizer adds ticket types to it; an event
without any is free and none of this shows. Buyers pay through Stripe Checkout
on the sphere's own connected Stripe account (its `PayoutAccount`), and
Zagrajmy keeps a share of each order as Stripe's application fee. See
docs/rfc/0002-ticketing.md.

Buying needs no account. An order's page lives at a secret `reference`, which
Stripe sends the buyer back to and the order mail repeats; whoever has it sees
the order until it is claimed into an account, and from then on only that
account does. Claiming needs the order's email: an account verified for it
claims at once, any other account through a link mailed to that address.

Money is integer minor units (grosze) everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts.billing import SpherePlanRepositoryProtocol
    from ludamus.pacts.crowd import UserRepositoryProtocol
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
# Well under the integer column's limit, and over any convention's attendance.
MAX_TICKET_QUANTITY = 1_000_000
TICKET_CODE_LENGTH = 10
ORDER_REFERENCE_MAX_LENGTH = 32
# A guest's network, keyed (`TicketOrder.guest_client`): HMAC-SHA256, in hex.
GUEST_CLIENT_LENGTH = 64
ORDER_CLAIM_LINK_MAX_AGE = timedelta(days=1)


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
# Orders whose seats are still taken, one way or the other.
HOLDING_STATUSES = CHECKOUT_STATUSES | SETTLING_STATUSES
# Orders we gave up on: their seats are free again.
ABANDONED_STATUSES = frozenset({OrderStatus.EXPIRED, OrderStatus.FAILED})
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
    # A guest's network holds as many unpaid orders as one may.
    TOO_MANY_HOLDS = "too_many_holds"
    PROVIDER_ERROR = "provider_error"


class ClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    ALREADY_YOURS = "already_yours"
    # The account is not verified for the order's email: a link went there.
    CONFIRMATION_SENT = "confirmation_sent"
    # A link went there a few minutes ago, for this account or another; no
    # second one until `CLAIM_MAIL_INTERVAL` passes.
    CONFIRMATION_HELD = "confirmation_held"


class ConfirmOutcome(StrEnum):
    CLAIMED = "claimed"
    ALREADY_YOURS = "already_yours"
    # Expired, tampered with, or made for another account or order.
    LINK_INVALID = "link_invalid"


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


class OrderDTO(BaseModel):
    pk: int
    reference: str
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
    claim_mailed_at: datetime | None
    creation_time: datetime
    lines: list[OrderLineDTO]
    tickets: list[TicketDTO]

    @property
    def ticket_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_guest(self) -> bool:
        """No account holds it: its link is all there is to it."""
        return self.buyer_id is None


class OrderPageState(StrEnum):
    """What the buyer's order page tells them."""

    PAID = "paid"
    # Card or BLIK, settled within seconds: the page checks back on its own.
    CONFIRMING = "confirming"
    # A bank transfer, which can take days: the buyer comes back later.
    AWAITING_TRANSFER = "awaiting_transfer"
    # The hold passed with no word from Stripe: its webhook is late.
    CONFIRMATION_LATE = "confirmation_late"
    REFUNDED = "refunded"
    NOT_COMPLETED = "not_completed"

    @property
    def awaiting_stripe(self) -> bool:
        return self in {
            OrderPageState.CONFIRMING,
            OrderPageState.AWAITING_TRANSFER,
            OrderPageState.CONFIRMATION_LATE,
        }


class BuyerOrderDTO(BaseModel):
    order: OrderDTO
    state: OrderPageState
    # Signing in on the page may keep it (`specs.tickets.claimable`).
    claimable: bool


class OwnedTicketDTO(BaseModel):
    """A ticket on its holder's "My tickets" page."""

    code: str
    ticket_type_name: str
    event_name: str
    event_slug: str
    event_start: datetime


class NewTicketData(TypedDict):
    ticket_type_id: int
    code: str


class OrderLineData(TypedDict):
    ticket_type_id: int
    quantity: int
    unit_price: int


class OrderChanges(TypedDict, total=False):
    # What a move records besides the status.
    email: str
    guest_client: str
    stripe_payment_intent_id: str
    paid_at: datetime
    refunded_at: datetime


class OrderCreateData(TypedDict):
    reference: str
    event_id: int
    # None: a guest, until they claim it.
    buyer_id: int | None
    # The guest's network, keyed; empty for an account's order.
    guest_client: str
    # Empty for a guest: Checkout asks for it.
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
    # Empty: Checkout asks the buyer.
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
class CheckoutBuyer:
    """Who is buying: an account, or a guest known only by their network."""

    user_id: int | None
    # The account's address, or empty: Checkout asks the buyer.
    email: str
    # Empty for an account; for a guest, their keyed network.
    guest_client: str


@dataclass(frozen=True)
class CheckoutUrls:
    """Where Stripe sends the buyer back, given the order's reference."""

    success: Callable[[str], str]
    cancel: Callable[[str], str]


class OrderMailEvent(BaseModel):
    pk: int
    name: str
    slug: str


class OrderLinkMail(BaseModel):
    """The mail that hands a buyer their order page, so a guest can find it."""

    order_pk: int
    email: str
    event: OrderMailEvent
    reference: str
    # Paid: the tickets are on the page; else the money is still on its way.
    paid: bool
    # No account holds the order: the mail says how to keep it in one.
    is_guest: bool


class ClaimConfirmationMail(BaseModel):
    """Asks the order's email to let an account take the order."""

    order_pk: int
    email: str
    event: OrderMailEvent
    reference: str
    token: str


class TicketMailerProtocol(Protocol):
    # Both send after the surrounding transaction commits, and never raise.
    @staticmethod
    def send_order_link(mail: OrderLinkMail) -> None: ...
    @staticmethod
    def send_claim_confirmation(mail: ClaimConfirmationMail) -> None: ...


class OrderClaimPayload(BaseModel):
    order_pk: int
    user_id: int


class OrderClaimCodecProtocol(Protocol):
    @staticmethod
    def dumps(payload: OrderClaimPayload) -> str: ...
    @staticmethod
    def loads(token: str) -> OrderClaimPayload | None:
        """None for a forged or expired (`ORDER_CLAIM_LINK_MAX_AGE`) token."""


class ClaimResultDTO(BaseModel):
    outcome: ClaimOutcome
    # The order's email: where a confirmation link went, if one did.
    order_email: str


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
    def read_by_reference(*, reference: str) -> OrderDTO | None: ...
    @staticmethod
    def lock_by_reference(*, reference: str) -> OrderDTO | None: ...
    @staticmethod
    def claim(*, pk: int, buyer_id: int) -> None:
        """Give the order, and every ticket it issued, to `buyer_id`."""

    @staticmethod
    def mark_claim_mailed(*, pk: int, at: datetime) -> None: ...

    @staticmethod
    def count_guest_holds(
        *, event_id: int, guest_client: str, holds_after: datetime
    ) -> int:
        """Count a guest network's orders on the event that still hold seats."""

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
    def issue_tickets(*, order: OrderDTO, tickets: list[NewTicketData]) -> None: ...
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
    users: UserRepositoryProtocol


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

    # `buyer`: the account buying, or None and the guest's keyed network.
    def start_checkout(
        self,
        *,
        event: EventDTO,
        buyer: CheckoutBuyer,
        quantities: dict[int, int],
        urls: CheckoutUrls,
    ) -> CheckoutStartDTO: ...

    # `viewer_id`: who is looking, None for nobody signed in. An order a guest
    # bought is anyone's with its reference; a claimed one only its holder's.
    def order(
        self, *, event_id: int, reference: str, viewer_id: int | None
    ) -> BuyerOrderDTO: ...
    def abandon_checkout(
        self, *, event_id: int, reference: str, viewer_id: int | None
    ) -> AbandonOutcome: ...
    def claim_order(
        self, *, event_id: int, reference: str, user_id: int
    ) -> ClaimResultDTO: ...
    def confirm_claim(
        self, *, event_id: int, reference: str, token: str, user_id: int
    ) -> ConfirmOutcome: ...
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
