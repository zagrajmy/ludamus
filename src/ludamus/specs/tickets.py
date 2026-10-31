from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, assert_never

from ludamus.pacts.tickets import (
    ABANDONED_STATUSES,
    MAX_TICKETS_PER_ORDER,
    CheckoutOutcome,
    FeeBreakdownDTO,
    OfferState,
    OrderPageState,
    OrderStatus,
    PayoutStatus,
    TicketOfferDTO,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ludamus.pacts.tickets import OrderDTO, PayoutAccountDTO, TicketTypeDTO

_BPS = 10_000

# Stripe's headline card rate, used only to show organizers what they keep.
# Stripe charges the real fee to their account; it varies with card country
# and payment method, so this is never sent anywhere.
STRIPE_FEE_ESTIMATE_BPS = 290
STRIPE_FEE_ESTIMATE_FIXED = 30

# Seats are held while the buyer is in Checkout, and the Checkout Session is
# told to expire at the same moment. Stripe refuses an expiry under 30 minutes
# from when it receives the request, so the margin covers the round trip.
CHECKOUT_HOLD = timedelta(minutes=31)
# A session that completed at the last minute may be reported late: its seats
# stay held this long past the hold, unless Stripe says it expired, so a slow
# webhook never finds them sold to someone else.
WEBHOOK_GRACE = timedelta(hours=1)

# NOTE: a guest's unpaid order holds seats with no account behind it; a bank
# transfer can hold them for days. One network may hold this many orders per
# event at once, so a script cannot sit on a sell-out.
GUEST_HOLDS_PER_CLIENT = 3

# At or below this many left, the shop says how many.
FEW_TICKETS_LEFT = 20
# The panel lists this many of the newest orders; Stripe's dashboard has all.
PANEL_ORDERS_SHOWN = 100

# Every move an order may make; anything else is a stale or reordered webhook.
ORDER_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = MappingProxyType(
    {
        OrderStatus.PENDING: frozenset(
            {
                OrderStatus.PAID,
                OrderStatus.AWAITING_PAYMENT,
                OrderStatus.EXPIRED,
                OrderStatus.FAILED,
            }
        ),
        OrderStatus.AWAITING_PAYMENT: frozenset({OrderStatus.PAID, OrderStatus.FAILED}),
        OrderStatus.PAID: frozenset({OrderStatus.REFUNDED}),
    }
)


def sources_of(status: OrderStatus) -> frozenset[OrderStatus]:
    """Every status an order may be in to move to `status`."""
    return frozenset(
        source for source, targets in ORDER_TRANSITIONS.items() if status in targets
    )


def _share(total: int, bps: int) -> int:
    # Integer round half up, so a 10 000 zł order is as exact as a 10 zł one.
    return (total * bps + _BPS // 2) // _BPS


def platform_fee(total: int, *, bps: int) -> int:
    """Zagrajmy's share of an order, at the sphere's rate (`specs.billing`)."""
    if total <= 0:
        message = f"A fee needs a positive total, got {total}."
        raise ValueError(message)
    return _share(total, bps)


def platform_fee_percent(bps: int) -> Decimal:
    return Decimal(bps) / 100


def estimated_stripe_fees(*, gross: int, orders: int) -> int:
    """Stripe's likely take on `orders` charges worth `gross` together."""
    return _share(gross, STRIPE_FEE_ESTIMATE_BPS) + STRIPE_FEE_ESTIMATE_FIXED * orders


def estimated_stripe_fee(total: int) -> int:
    return estimated_stripe_fees(gross=total, orders=1)


def fee_breakdown(price: int, *, bps: int) -> FeeBreakdownDTO:
    return FeeBreakdownDTO(
        price=price,
        platform_fee=platform_fee(price, bps=bps),
        estimated_stripe_fee=estimated_stripe_fee(price),
    )


def offer_for(
    ticket_type: TicketTypeDTO, *, now: datetime, closes_at: datetime
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
    if now >= (ticket_type.sales_end or closes_at):
        state = OfferState.ENDED
    elif ticket_type.sales_start is not None and now < ticket_type.sales_start:
        state = OfferState.NOT_YET
    elif remaining == 0:
        state = OfferState.SOLD_OUT
    else:
        state = OfferState.ON_SALE
    return TicketOfferDTO(
        ticket_type=ticket_type,
        state=state,
        remaining=remaining,
        few_left=remaining is not None and remaining <= FEW_TICKETS_LEFT,
        max_quantity=(
            0
            if state is not OfferState.ON_SALE
            else min(MAX_TICKETS_PER_ORDER, remaining or MAX_TICKETS_PER_ORDER)
        ),
    )


def checkout_refusal(offer: TicketOfferDTO, *, count: int) -> CheckoutOutcome | None:
    """Say why `count` seats of this offer cannot be bought now, if they cannot."""
    if offer.state is OfferState.SOLD_OUT or (
        offer.state is OfferState.ON_SALE and count > offer.max_quantity
    ):
        return CheckoutOutcome.SOLD_OUT
    if offer.state is not OfferState.ON_SALE:
        return CheckoutOutcome.NOT_ON_SALE
    return None


def order_page_state(order: OrderDTO, *, now: datetime) -> OrderPageState:
    match order.status:
        case OrderStatus.PAID:
            return OrderPageState.PAID
        case OrderStatus.PENDING if order.hold_until > now:
            return OrderPageState.CONFIRMING
        case OrderStatus.PENDING:
            return OrderPageState.CONFIRMATION_LATE
        case OrderStatus.AWAITING_PAYMENT:
            return OrderPageState.AWAITING_TRANSFER
        case OrderStatus.REFUNDED:
            return OrderPageState.REFUNDED
        case OrderStatus.EXPIRED | OrderStatus.FAILED:
            return OrderPageState.NOT_COMPLETED
        case _:
            assert_never(order.status)


def payout_status(account: PayoutAccountDTO | None) -> PayoutStatus:
    if account is None:
        return PayoutStatus.NOT_CONNECTED
    if account.charges_enabled:
        return PayoutStatus.ACTIVE
    return PayoutStatus.INCOMPLETE


def owns_order_email(*, order_email: str, verified_email: str) -> bool:
    """Say if an account proved it reads the address the order was bought with."""
    return bool(verified_email) and order_email.casefold() == verified_email.casefold()


def claimable(order: OrderDTO) -> bool:
    """Say if signing in on the order's page may keep it in an account.

    A guest's order with tickets coming, once Checkout reported the email the
    claim may have to be proven through.
    """
    return (
        order.is_guest
        and bool(order.email)
        and order.status not in ABANDONED_STATUSES | {OrderStatus.REFUNDED}
    )
