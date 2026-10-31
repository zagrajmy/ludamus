"""What a sphere's deal gives it right now, written before the code.

How it could go wrong, and the test that holds each line:

- a sphere with no plan row, or a row naming only a Stripe customer, reads as
  having a deal;
- a deal still applies once `paid_until` has passed, or on the very moment it
  passes;
- an open-ended deal (no `paid_until`) reads as lapsed;
- a Stripe-billed deal reads as held before its first invoice is paid, when it
  has no date yet, and so never lapses if that invoice is never paid;
- a deal that sets no fee charges nothing instead of the standard rate, or a
  deal's own fee is overridden by the standard one;
- a deal of only a yearly price or only Technical Partner reads as no deal.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ludamus.pacts.billing import (
    STANDARD_TICKET_FEE_BPS,
    PlanSource,
    PlanTermsDTO,
    SpherePlanDTO,
)
from ludamus.specs.billing import current_terms

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
_NO_DEAL = PlanTermsDTO(
    technical_partner=False,
    ticket_fee_bps=STANDARD_TICKET_FEE_BPS,
    yearly_price=None,
    paid_until=None,
    has_deal=False,
)


def _plan(**overrides: object) -> SpherePlanDTO:
    fields: dict[str, object] = {
        "sphere_id": 1,
        "technical_partner": False,
        "ticket_fee_bps": None,
        "yearly_price": None,
        "source": PlanSource.MANUAL,
        "paid_until": None,
        "stripe_customer_id": "",
        "stripe_subscription_id": "",
    }
    fields.update(overrides)
    return SpherePlanDTO.model_validate(fields)


class TestCurrentTerms:
    def test_sphere_without_a_plan_pays_the_standard_rate(self) -> None:
        assert current_terms(None, now=NOW) == _NO_DEAL

    @pytest.mark.parametrize("source", PlanSource)
    def test_row_naming_only_a_stripe_customer_is_no_deal(
        self, source: PlanSource
    ) -> None:
        plan = _plan(
            source=source,
            stripe_customer_id="cus_1",
            paid_until=NOW + timedelta(days=1),
        )

        assert current_terms(plan, now=NOW) == _NO_DEAL

    @pytest.mark.parametrize(
        "paid_until",
        (
            pytest.param(NOW - timedelta(days=1), id="lapsed"),
            pytest.param(NOW, id="lapses-this-moment"),
        ),
    )
    def test_deal_past_its_end_gives_way_to_the_standard_terms(
        self, paid_until: datetime
    ) -> None:
        plan = _plan(
            technical_partner=True,
            ticket_fee_bps=100,
            yearly_price=500_000,
            paid_until=paid_until,
        )

        assert current_terms(plan, now=NOW) == _NO_DEAL

    @pytest.mark.parametrize(
        "paid_until",
        (
            pytest.param(None, id="open-ended"),
            pytest.param(NOW + timedelta(seconds=1), id="last-second"),
        ),
    )
    def test_deal_holds_until_its_end(self, paid_until: datetime | None) -> None:
        plan = _plan(technical_partner=True, ticket_fee_bps=100, paid_until=paid_until)

        assert current_terms(plan, now=NOW) == PlanTermsDTO(
            technical_partner=True,
            ticket_fee_bps=100,
            yearly_price=None,
            paid_until=paid_until,
            has_deal=True,
        )

    def test_stripe_deal_awaiting_its_first_paid_invoice_is_no_deal(self) -> None:
        plan = _plan(
            source=PlanSource.STRIPE,
            technical_partner=True,
            ticket_fee_bps=100,
            stripe_customer_id="cus_1",
        )

        assert current_terms(plan, now=NOW) == _NO_DEAL

    def test_stripe_deal_holds_once_an_invoice_dates_it(self) -> None:
        paid_until = NOW + timedelta(days=365)
        plan = _plan(
            source=PlanSource.STRIPE, ticket_fee_bps=100, paid_until=paid_until
        )

        terms = current_terms(plan, now=NOW)

        assert (terms.has_deal, terms.ticket_fee_bps) == (True, 100)

    @pytest.mark.parametrize(
        "terms",
        (
            pytest.param({"technical_partner": True}, id="technical-partner"),
            pytest.param({"yearly_price": 500_000}, id="yearly-price"),
        ),
    )
    def test_deal_that_sets_no_fee_pays_the_standard_rate(
        self, terms: dict[str, object]
    ) -> None:
        terms_now = current_terms(_plan(**terms), now=NOW)

        assert terms_now.has_deal
        assert terms_now.ticket_fee_bps == STANDARD_TICKET_FEE_BPS

    def test_deal_of_only_a_fee_waiver_charges_nothing(self) -> None:
        terms = current_terms(_plan(ticket_fee_bps=0), now=NOW)

        assert (terms.has_deal, terms.ticket_fee_bps) == (True, 0)
