"""The sphere's plan: the panel, the billing portal, and Stripe's webhooks.

Ways the service could fail, each pinned below:

Panel
- A lapsed deal still shows its terms, or a held one shows the standard ones.
- The fee percent shown is not the rate the sphere's tickets are charged.
- The billing portal is offered to a sphere Stripe knows nothing about, or
  while Stripe billing is off.

Billing portal
- The portal is opened for a sphere without a Stripe customer.

Webhook
- An event that is not about a subscription changes a plan.
- A subscription for a customer we never created touches someone's plan.
- A paid subscription does not extend the deal, or a renewal is reported as a
  new one.
- An ended subscription keeps the deal running to the end of a period it was
  cancelled in, or dates the end into the future.
- An ended subscription that is not the one on record ends the deal.
- Ending a deal wipes its terms, so a renewal brings back nothing.
- Stripe overrides the dates of a deal a maintainer recorded by hand.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ludamus.mills.billing import PlanService
from ludamus.pacts.billing import (
    STANDARD_TICKET_FEE_BPS,
    PlanPageDTO,
    PlanSource,
    PlanTermsDTO,
    SubscriptionState,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import (
    CheckoutEvent,
    CheckoutStage,
    SubscriptionEvent,
    UnhandledEvent,
    WebhookOutcome,
)
from ludamus.specs.billing import current_terms
from tests.unit.factories import FakeTransaction
from tests.unit.ticket_fakes import NOW, SPHERE_ID, FakePlans

_CUSTOMER = "cus_sphere"
_SUBSCRIPTION = "sub_current"
_DEAL_FEE_BPS = 150
_YEARLY_PRICE = 500_000
_RETURN_URL = "/plan/"
_PAID_UNTIL = NOW + timedelta(days=365)
_LAPSED = NOW - timedelta(days=1)
_STANDARD = PlanTermsDTO(
    technical_partner=False,
    ticket_fee_bps=STANDARD_TICKET_FEE_BPS,
    yearly_price=None,
    paid_until=None,
    has_deal=False,
)


class FakePlanBilling:
    """Zagrajmy's own Stripe account, as the plan mill sees it."""

    def __init__(self):
        self.enabled = True
        self.subscriptions: dict[str, SubscriptionState] = {}
        self.event = None

    def billing_portal_url(self, *, customer_id, return_url):
        return f"https://billing.stripe.test/{customer_id}"

    def read_subscription(self, *, subscription_id):
        return self.subscriptions[subscription_id]

    def parse_webhook(self, *, payload, signature):
        return self.event


@pytest.fixture(name="plans")
def plans_fixture():
    return FakePlans()


@pytest.fixture(name="billing")
def billing_fixture():
    return FakePlanBilling()


@pytest.fixture(name="service")
def service_fixture(plans, billing):
    return PlanService(transaction=FakeTransaction(), plans=plans, billing=billing)


def _deal(plans, **overrides):
    data = {
        "technical_partner": True,
        "ticket_fee_bps": _DEAL_FEE_BPS,
        "yearly_price": _YEARLY_PRICE,
        "source": PlanSource.STRIPE,
        "paid_until": _PAID_UNTIL,
        "stripe_customer_id": _CUSTOMER,
        "stripe_subscription_id": _SUBSCRIPTION,
    }
    return plans.add(**(data | overrides))


def _deliver(service, billing, *, subscription_id=_SUBSCRIPTION, state):
    billing.subscriptions[subscription_id] = state
    billing.event = SubscriptionEvent(
        subscription_id=subscription_id, customer_id=_CUSTOMER
    )
    return service.handle_webhook(payload=b"{}", signature="sig")


def _live(paid_until=_PAID_UNTIL):
    return SubscriptionState(live=True, paid_until=paid_until)


def _dead(paid_until):
    return SubscriptionState(live=False, paid_until=paid_until)


class TestPage:
    def test_sphere_without_a_plan_row_pays_the_standard_rate(self, service):
        assert service.page(sphere_id=SPHERE_ID) == PlanPageDTO(
            terms=_STANDARD,
            ticket_fee_percent=Decimal("3.5"),
            has_billing_history=False,
        )

    def test_held_deal_shows_its_terms_and_its_rate(self, service, plans):
        _deal(plans)

        assert service.page(sphere_id=SPHERE_ID) == PlanPageDTO(
            terms=PlanTermsDTO(
                technical_partner=True,
                ticket_fee_bps=_DEAL_FEE_BPS,
                yearly_price=_YEARLY_PRICE,
                paid_until=_PAID_UNTIL,
                has_deal=True,
            ),
            ticket_fee_percent=Decimal("1.5"),
            has_billing_history=True,
        )

    def test_lapsed_deal_reads_as_standard_but_keeps_its_invoices(self, service, plans):
        _deal(plans, paid_until=_LAPSED)

        assert service.page(sphere_id=SPHERE_ID) == PlanPageDTO(
            terms=_STANDARD, ticket_fee_percent=Decimal("3.5"), has_billing_history=True
        )

    @pytest.mark.parametrize(
        ("enabled", "customer"), ((False, _CUSTOMER), (True, "")), ids=("off", "none")
    )
    def test_no_billing_history_without_stripe_billing_the_sphere(
        self, service, plans, billing, enabled, customer
    ):
        billing.enabled = enabled
        _deal(plans, source=PlanSource.MANUAL, stripe_customer_id=customer)

        assert not service.page(sphere_id=SPHERE_ID).has_billing_history


class TestBillingPortal:
    @pytest.mark.parametrize("seed", (False, True))
    def test_sphere_without_a_customer_has_no_portal(self, service, plans, seed):
        if seed:
            _deal(plans, source=PlanSource.MANUAL, stripe_customer_id="")

        with pytest.raises(NotFoundError):
            service.billing_portal_url(sphere_id=SPHERE_ID, return_url=_RETURN_URL)

    def test_portal_opens_for_the_spheres_customer(self, service, plans):
        _deal(plans)

        assert (
            service.billing_portal_url(sphere_id=SPHERE_ID, return_url=_RETURN_URL)
            == f"https://billing.stripe.test/{_CUSTOMER}"
        )


class TestWebhook:
    @pytest.mark.parametrize(
        "event",
        (
            UnhandledEvent(type="invoice.created"),
            CheckoutEvent(
                stage=CheckoutStage.COMPLETED,
                session_id="cs_tickets",
                paid=True,
                payment_intent_id="pi_1",
            ),
        ),
    )
    def test_event_not_about_a_subscription_changes_nothing(
        self, service, plans, billing, event
    ):
        lapsed = _deal(plans, paid_until=_LAPSED)
        billing.event = event

        assert service.handle_webhook(payload=b"{}", signature="sig") is (
            WebhookOutcome.NOT_OURS
        )
        assert plans.rows == {SPHERE_ID: lapsed}

    def test_subscription_of_a_customer_we_never_created_is_not_ours(
        self, service, plans, billing
    ):
        lapsed = _deal(plans, paid_until=_LAPSED)
        billing.subscriptions["sub_other"] = _live()
        billing.event = SubscriptionEvent(
            subscription_id="sub_other", customer_id="cus_other"
        )

        assert service.handle_webhook(payload=b"{}", signature="sig") is (
            WebhookOutcome.NOT_OURS
        )
        assert plans.rows == {SPHERE_ID: lapsed}

    def test_first_payment_dates_the_deal_and_records_its_subscription(
        self, service, plans, billing
    ):
        agreed = _deal(plans, paid_until=None, stripe_subscription_id="")

        outcome = _deliver(service, billing, state=_live())

        assert outcome is WebhookOutcome.SUBSCRIBED
        assert plans.rows[SPHERE_ID] == agreed.model_copy(
            update={"paid_until": _PAID_UNTIL, "stripe_subscription_id": _SUBSCRIPTION}
        )

    def test_renewal_extends_the_deal_on_record(self, service, plans, billing):
        _deal(plans, paid_until=NOW + timedelta(days=1))

        outcome = _deliver(service, billing, state=_live())

        assert outcome is WebhookOutcome.RENEWED
        assert plans.rows[SPHERE_ID].paid_until == _PAID_UNTIL

    def test_live_subscription_without_a_period_keeps_the_date_on_record(
        self, service, plans, billing
    ):
        until = NOW + timedelta(days=1)
        _deal(plans, paid_until=until)

        outcome = _deliver(service, billing, state=_live(paid_until=None))

        assert outcome is WebhookOutcome.RENEWED
        assert plans.rows[SPHERE_ID].paid_until == until

    @pytest.mark.parametrize(
        "period_end", (_PAID_UNTIL, None), ids=("mid-period", "no-period")
    )
    def test_ended_subscription_ends_the_deal_now(
        self, service, plans, billing, period_end
    ):
        _deal(plans)
        before = datetime.now(tz=UTC)

        outcome = _deliver(service, billing, state=_dead(period_end))

        ended = plans.rows[SPHERE_ID]
        after = datetime.now(tz=UTC)
        assert outcome is WebhookOutcome.ENDED
        assert ended.paid_until is not None
        assert before <= ended.paid_until <= after
        assert not current_terms(ended, now=after).has_deal

    def test_subscription_ended_after_its_period_keeps_that_end(
        self, service, plans, billing
    ):
        _deal(plans)

        outcome = _deliver(service, billing, state=_dead(_LAPSED))

        assert outcome is WebhookOutcome.ENDED
        assert plans.rows[SPHERE_ID].paid_until == _LAPSED

    def test_ended_deal_keeps_its_terms_for_a_renewal(self, service, plans, billing):
        _deal(plans)
        _deliver(service, billing, state=_dead(_PAID_UNTIL))

        outcome = _deliver(service, billing, state=_live())

        assert outcome is WebhookOutcome.RENEWED
        terms = current_terms(plans.rows[SPHERE_ID], now=datetime.now(tz=UTC))
        assert (terms.has_deal, terms.ticket_fee_bps) == (True, _DEAL_FEE_BPS)

    def test_old_subscription_ending_leaves_the_current_deal(
        self, service, plans, billing
    ):
        current = _deal(plans)

        outcome = _deliver(
            service, billing, subscription_id="sub_old", state=_dead(_LAPSED)
        )

        assert outcome is WebhookOutcome.STALE
        assert plans.rows == {SPHERE_ID: current}

    @pytest.mark.parametrize("paid_until", (None, _LAPSED), ids=("open", "lapsed"))
    @pytest.mark.parametrize("live", (True, False))
    def test_deal_recorded_by_hand_is_left_alone(
        self, service, plans, billing, paid_until, live
    ):
        manual = _deal(plans, source=PlanSource.MANUAL, paid_until=paid_until)

        outcome = _deliver(
            service, billing, state=SubscriptionState(live=live, paid_until=_PAID_UNTIL)
        )

        assert outcome is WebhookOutcome.STALE
        assert plans.rows == {SPHERE_ID: manual}
