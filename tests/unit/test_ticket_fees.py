"""Fee and availability math for ticket sales, written before the code.

How it could go wrong, and the test that holds each line:

- the 3.5% share rounds the wrong way on a half grosz, or drifts through floats
  on a large order;
- Stripe's fixed 0,30 is charged once per ticket instead of once per order;
- a fee comes out larger than the order, or a non-positive total gets a fee;
- the yearly plan reads a different rate than the brief sets;
- a capped ticket type shows a negative "left", or counts lapsed holds;
- a type is offered before its sales open, after they close, or while sold out.
"""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ludamus.mills.tickets import estimated_stripe_fee, offer_for, platform_fee
from ludamus.pacts.billing import PlanKind
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    MIN_TICKET_PRICE,
    OfferState,
    TicketTypeDTO,
)

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def _ticket_type(**overrides: object) -> TicketTypeDTO:
    fields: dict[str, object] = {
        "pk": 1,
        "event_id": 1,
        "name": "Weekend pass",
        "description": "",
        "price": 5000,
        "currency": "pln",
        "quantity": None,
        "sales_start": None,
        "sales_end": None,
        "is_archived": False,
        "order": 0,
        "sold": 0,
        "held": 0,
    }
    fields.update(overrides)
    return TicketTypeDTO.model_validate(fields)


class TestPlatformFee:
    @pytest.mark.parametrize(
        ("total", "plan", "fee"),
        (
            pytest.param(5000, PlanKind.STANDARD, 175, id="three-and-a-half-percent"),
            # 3.5% of 1,00 zł is 3.5 gr.
            pytest.param(100, PlanKind.STANDARD, 4, id="half-a-grosz-rounds-up"),
            # 3.5% of 2,10 zł is 7.35 gr.
            pytest.param(210, PlanKind.STANDARD, 7, id="below-half-rounds-down"),
            # 3.5% of 10 000 000 000 001,00 zł is …003.5 gr: exact in integers.
            pytest.param(
                10**15 + 100, PlanKind.STANDARD, 35 * 10**12 + 4, id="large-order"
            ),
            # The brief: Zagrajmy takes 3.5% from all tickets.
            pytest.param(5000, PlanKind.WHITE_GLOVE, 175, id="yearly-plan-same-share"),
        ),
    )
    def test_share(self, total: int, plan: PlanKind, fee: int) -> None:
        assert platform_fee(total, plan=plan) == fee

    @pytest.mark.parametrize("total", (0, -100))
    def test_refuses_a_total_that_is_not_positive(self, total: int) -> None:
        with pytest.raises(ValueError, match="positive"):
            platform_fee(total, plan=PlanKind.STANDARD)

    @given(st.integers(min_value=MIN_TICKET_PRICE, max_value=10**12))
    def test_never_exceeds_the_order(self, total: int) -> None:
        fee = platform_fee(total, plan=PlanKind.STANDARD)
        assert 0 < fee < total


class TestEstimatedStripeFee:
    def test_is_rate_plus_fixed_once_per_order(self) -> None:
        three_tickets = 15000
        # 2.9% of 150,00 zł plus one 0,30, not three.
        expected = 435 + 30

        assert estimated_stripe_fee(three_tickets) == expected

    def test_cheapest_ticket_still_leaves_the_organizer_money(self) -> None:
        total = MIN_TICKET_PRICE
        kept = (
            total
            - platform_fee(total, plan=PlanKind.STANDARD)
            - estimated_stripe_fee(total)
        )
        assert kept > 0


class TestOfferFor:
    def test_uncapped_type_on_sale_has_no_remaining_count(self) -> None:
        offer = offer_for(_ticket_type(), now=NOW)

        assert offer.state is OfferState.ON_SALE
        assert offer.remaining is None
        assert offer.max_quantity == MAX_TICKETS_PER_ORDER

    def test_capped_type_counts_sold_and_held(self) -> None:
        offer = offer_for(_ticket_type(quantity=10, sold=4, held=3), now=NOW)
        left = 10 - 4 - 3

        assert offer.remaining == left
        assert offer.max_quantity == left

    def test_oversold_type_reads_sold_out_not_negative(self) -> None:
        # An organizer may lower the cap below what is already sold.
        offer = offer_for(_ticket_type(quantity=5, sold=7), now=NOW)

        assert offer.state is OfferState.SOLD_OUT
        assert offer.remaining == 0
        assert offer.max_quantity == 0

    def test_before_sales_open(self) -> None:
        offer = offer_for(_ticket_type(sales_start=NOW + timedelta(minutes=1)), now=NOW)

        assert offer.state is OfferState.NOT_YET
        assert offer.max_quantity == 0

    def test_after_sales_close(self) -> None:
        offer = offer_for(_ticket_type(sales_end=NOW), now=NOW)

        assert offer.state is OfferState.ENDED
        assert offer.max_quantity == 0

    def test_closed_window_reads_ended_even_when_sold_out(self) -> None:
        # Once sales are over, nothing a buyer can do changes that; "sold out"
        # would hint that waiting for a returned ticket might help.
        offer = offer_for(
            _ticket_type(quantity=1, sold=1, sales_end=NOW - timedelta(days=1)), now=NOW
        )

        assert offer.state is OfferState.ENDED

    def test_type_without_its_own_end_closes_with_the_event(self) -> None:
        offer = offer_for(_ticket_type(), now=NOW, closes_at=NOW)

        assert offer.state is OfferState.ENDED
