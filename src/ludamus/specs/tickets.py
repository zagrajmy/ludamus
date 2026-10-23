from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanKind

if TYPE_CHECKING:
    from collections.abc import Mapping

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

# Stripe states that still honour the yearly plan: a renewal that failed is
# retried (past_due) before the subscription ends.
ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing", "past_due"})
