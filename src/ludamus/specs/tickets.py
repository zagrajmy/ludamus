from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanKind
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    FeeBreakdownDTO,
    OfferState,
    OrderStatus,
    PayoutStatus,
    TicketOfferDTO,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ludamus.pacts.tickets import PayoutAccountDTO, TicketTypeDTO

_BPS = 10_000

# Zagrajmy's share of every ticket order, in basis points (350 = 3.5%), taken
# as the Stripe application fee. The brief sets one rate for all tickets; a
# plan that should pay less per ticket changes its line here.
PLATFORM_FEE_BPS: Mapping[PlanKind, int] = MappingProxyType(
    {PlanKind.STANDARD: 350, PlanKind.WHITE_GLOVE: 350}
)

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

# At or below this many left, the shop says how many.
FEW_TICKETS_LEFT = 20

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


def platform_fee(total: int, *, plan: PlanKind) -> int:
    if total <= 0:
        message = f"A fee needs a positive total, got {total}."
        raise ValueError(message)
    return _share(total, PLATFORM_FEE_BPS[plan])


def platform_fee_percent(plan: PlanKind) -> Decimal:
    return Decimal(PLATFORM_FEE_BPS[plan]) / 100


def estimated_stripe_fee(total: int) -> int:
    return _share(total, STRIPE_FEE_ESTIMATE_BPS) + STRIPE_FEE_ESTIMATE_FIXED


def fee_breakdown(price: int, *, plan: PlanKind) -> FeeBreakdownDTO:
    return FeeBreakdownDTO(
        price=price,
        platform_fee=platform_fee(price, plan=plan),
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


def payout_status(account: PayoutAccountDTO | None) -> PayoutStatus:
    if account is None:
        return PayoutStatus.NOT_CONNECTED
    if account.charges_enabled:
        return PayoutStatus.ACTIVE
    return PayoutStatus.INCOMPLETE
