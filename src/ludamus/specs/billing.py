from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.billing import STANDARD_TICKET_FEE_BPS, PlanTermsDTO

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.billing import SpherePlanDTO

_NO_DEAL = PlanTermsDTO(
    technical_partner=False,
    ticket_fee_bps=STANDARD_TICKET_FEE_BPS,
    yearly_price=None,
    paid_until=None,
    has_deal=False,
)


def current_terms(plan: SpherePlanDTO | None, *, now: datetime) -> PlanTermsDTO:
    """Say what a sphere's deal gives it right now; the only way to read one.

    A deal holds while `paid_until` has not passed. No date means held until
    someone says otherwise: a maintainer's open-ended deal. A row that only
    names a Stripe customer, with no terms on it, is no deal.
    """
    if plan is None or (plan.paid_until is not None and plan.paid_until <= now):
        return _NO_DEAL
    if (
        not plan.technical_partner
        and plan.ticket_fee_bps is None
        and plan.yearly_price is None
    ):
        return _NO_DEAL
    return PlanTermsDTO(
        technical_partner=plan.technical_partner,
        ticket_fee_bps=(
            STANDARD_TICKET_FEE_BPS
            if plan.ticket_fee_bps is None
            else plan.ticket_fee_bps
        ),
        yearly_price=plan.yearly_price,
        paid_until=plan.paid_until,
        has_deal=True,
    )
