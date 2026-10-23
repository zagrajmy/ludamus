"""The sphere's plan: the panel, buying the yearly plan, and Stripe's webhooks.

Ways the service could fail, each pinned below:

Panel
- A lapsed yearly plan still shows as held, or a held one offers to sell it
  again.
- The billing portal is offered to a sphere Stripe knows nothing about, or
  the plan is offered for sale while Stripe billing is off.

Buying the yearly plan
- A sphere holding the plan by a maintainer's hand is sent to pay for it.
- A sphere Stripe already bills (held, or paid a moment ago with the webhook
  still on its way) is sent to Checkout and billed twice.
- A second Stripe customer is created for a sphere that has one.
- A new customer is not recorded on the sphere, so its webhooks find nothing.
- The portal is opened for a sphere without a Stripe customer.

Webhook
- An event that is not about a yearly-plan subscription changes a plan.
- A subscription for a customer we never created touches someone's plan.
- A paid subscription does not grant the plan, or a renewal is reported as a
  new one.
- An ended subscription that is not the one on record takes the plan away.
- An end redelivered after the plan already ended reports it ended again.
- Stripe overrides a plan a maintainer recorded by hand while it lasts.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from ludamus.mills.billing import PlanService
from ludamus.pacts.billing import (
    PlanKind,
    PlanPageDTO,
    PlanSource,
    SpherePlanDTO,
    SubscriptionState,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import (
    CheckoutEvent,
    CheckoutMode,
    CheckoutStage,
    SubscriptionEvent,
    UnhandledEvent,
    WebhookOutcome,
)
from tests.unit.factories import FakeTransaction
from tests.unit.ticket_fakes import NOW, SPHERE_ID, FakePlans

_CUSTOMER = "cus_sphere"
_SUBSCRIPTION = "sub_current"
_FEE_PERCENT = Decimal("3.5")
_SUCCESS_URL = "/plan/thanks/"
_CANCEL_URL = "/plan/"
_PAID_UNTIL = NOW + timedelta(days=365)
_LAPSED = NOW - timedelta(days=1)


class FakePlanBilling:
    """Zagrajmy's own Stripe account, as the plan mill sees it."""

    def __init__(self):
        self.enabled = True
        self.live_customers: set[str] = set()
        self.subscriptions: dict[str, SubscriptionState] = {}
        self.event = None

    def create_customer(self, *, sphere_id, name, email):
        return f"cus_new_{sphere_id}"

    def create_plan_checkout(self, *, sphere_id, customer_id, success_url, cancel_url):
        return f"https://checkout.stripe.test/{customer_id}"

    def billing_portal_url(self, *, customer_id, return_url):
        return f"https://billing.stripe.test/{customer_id}"

    def has_live_subscription(self, *, customer_id):
        return customer_id in self.live_customers

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


def _yearly(plans, **overrides):
    data = {
        "kind": PlanKind.WHITE_GLOVE,
        "source": PlanSource.STRIPE,
        "paid_until": _PAID_UNTIL,
        "stripe_customer_id": _CUSTOMER,
        "stripe_subscription_id": _SUBSCRIPTION,
    }
    return plans.add(**(data | overrides))


def _start(service):
    return service.start_yearly_checkout(
        sphere_id=SPHERE_ID,
        sphere_name="Konwent",
        email="org@example.com",
        success_url=_SUCCESS_URL,
        cancel_url=_CANCEL_URL,
    )


def _subscription_checkout(*, subscription_id=_SUBSCRIPTION, **overrides):
    fields = {
        "stage": CheckoutStage.COMPLETED,
        "mode": CheckoutMode.SUBSCRIPTION,
        "session_id": "cs_plan",
        "paid": True,
        "payment_intent_id": "",
        "customer_id": _CUSTOMER,
        "subscription_id": subscription_id,
    }
    return CheckoutEvent(**(fields | overrides))


def _deliver(service, billing, event, *, live, customer_id=_CUSTOMER):
    billing.subscriptions[event.subscription_id] = SubscriptionState(
        customer_id=customer_id, live=live, paid_until=_PAID_UNTIL
    )
    billing.event = event
    return service.handle_webhook(payload=b"{}", signature="sig")


class TestPage:
    def test_sphere_without_a_plan_row_is_on_standard_and_may_subscribe(self, service):
        assert service.page(sphere_id=SPHERE_ID) == PlanPageDTO(
            kind=PlanKind.STANDARD,
            source=None,
            paid_until=None,
            can_subscribe=True,
            can_manage=False,
            ticket_fee_percent=_FEE_PERCENT,
        )

    def test_held_yearly_plan_is_managed_not_sold_again(self, service, plans):
        _yearly(plans)

        assert service.page(sphere_id=SPHERE_ID) == PlanPageDTO(
            kind=PlanKind.WHITE_GLOVE,
            source=PlanSource.STRIPE,
            paid_until=_PAID_UNTIL,
            can_subscribe=False,
            can_manage=True,
            ticket_fee_percent=_FEE_PERCENT,
        )

    def test_lapsed_yearly_plan_reads_as_standard(self, service, plans):
        _yearly(plans, paid_until=_LAPSED)

        assert service.page(sphere_id=SPHERE_ID) == PlanPageDTO(
            kind=PlanKind.STANDARD,
            source=None,
            paid_until=None,
            can_subscribe=True,
            can_manage=True,
            ticket_fee_percent=_FEE_PERCENT,
        )

    def test_nothing_is_sold_or_managed_while_billing_is_off(
        self, service, plans, billing
    ):
        billing.enabled = False
        _yearly(plans, paid_until=_LAPSED)

        page = service.page(sphere_id=SPHERE_ID)

        assert (page.can_subscribe, page.can_manage) == (False, False)


class TestStartYearlyCheckout:
    def test_plan_held_by_a_maintainers_hand_goes_back_to_the_panel(
        self, service, plans
    ):
        held = _yearly(
            plans,
            source=PlanSource.MANUAL,
            paid_until=None,
            stripe_customer_id="",
            stripe_subscription_id="",
        )

        assert _start(service) == _CANCEL_URL
        assert plans.rows == {SPHERE_ID: held}

    def test_plan_stripe_already_bills_goes_to_the_portal(self, service, plans):
        _yearly(plans)

        assert _start(service) == f"https://billing.stripe.test/{_CUSTOMER}"

    def test_subscription_paid_before_its_webhook_goes_to_the_portal(
        self, service, plans, billing
    ):
        plans.add(stripe_customer_id=_CUSTOMER)
        billing.live_customers.add(_CUSTOMER)

        assert _start(service) == f"https://billing.stripe.test/{_CUSTOMER}"

    def test_returning_customer_checks_out_as_the_same_customer(self, service, plans):
        lapsed = _yearly(plans, paid_until=_LAPSED)

        assert _start(service) == f"https://checkout.stripe.test/{_CUSTOMER}"
        assert plans.rows == {SPHERE_ID: lapsed}

    def test_first_purchase_records_the_new_customer_before_checkout(
        self, service, plans
    ):
        url = _start(service)

        assert url == f"https://checkout.stripe.test/cus_new_{SPHERE_ID}"
        assert plans.rows == {
            SPHERE_ID: SpherePlanDTO(
                sphere_id=SPHERE_ID,
                kind=PlanKind.STANDARD,
                source=PlanSource.STRIPE,
                paid_until=None,
                stripe_customer_id=f"cus_new_{SPHERE_ID}",
                stripe_subscription_id="",
            )
        }


class TestBillingPortal:
    @pytest.mark.parametrize("seed", (False, True))
    def test_sphere_without_a_customer_has_no_portal(self, service, plans, seed):
        if seed:
            plans.add()

        with pytest.raises(NotFoundError):
            service.billing_portal_url(sphere_id=SPHERE_ID, return_url=_CANCEL_URL)

    def test_portal_opens_for_the_spheres_customer(self, service, plans):
        _yearly(plans)

        assert (
            service.billing_portal_url(sphere_id=SPHERE_ID, return_url=_CANCEL_URL)
            == f"https://billing.stripe.test/{_CUSTOMER}"
        )


class TestWebhook:
    @pytest.mark.parametrize(
        "event",
        (
            UnhandledEvent(type="invoice.created"),
            _subscription_checkout(mode=CheckoutMode.PAYMENT),
            _subscription_checkout(stage=CheckoutStage.EXPIRED),
            _subscription_checkout(subscription_id=""),
            SubscriptionEvent(subscription_id=""),
        ),
    )
    def test_event_not_about_a_plan_subscription_changes_nothing(
        self, service, plans, billing, event
    ):
        lapsed = _yearly(plans, paid_until=_LAPSED)
        billing.event = event

        assert service.handle_webhook(payload=b"{}", signature="sig") is (
            WebhookOutcome.NOT_OURS
        )
        assert plans.rows == {SPHERE_ID: lapsed}

    def test_subscription_of_a_customer_we_never_created_is_not_ours(
        self, service, plans, billing
    ):
        lapsed = _yearly(plans, paid_until=_LAPSED)

        outcome = _deliver(
            service,
            billing,
            SubscriptionEvent(subscription_id="sub_other"),
            live=True,
            customer_id="cus_other",
        )

        assert outcome is WebhookOutcome.NOT_OURS
        assert plans.rows == {SPHERE_ID: lapsed}

    def test_paid_checkout_grants_the_yearly_plan(self, service, plans, billing):
        plans.add(stripe_customer_id=_CUSTOMER)

        outcome = _deliver(service, billing, _subscription_checkout(), live=True)

        assert outcome is WebhookOutcome.SUBSCRIBED
        assert plans.rows[SPHERE_ID] == SpherePlanDTO(
            sphere_id=SPHERE_ID,
            kind=PlanKind.WHITE_GLOVE,
            source=PlanSource.STRIPE,
            paid_until=_PAID_UNTIL,
            stripe_customer_id=_CUSTOMER,
            stripe_subscription_id=_SUBSCRIPTION,
        )

    def test_renewal_extends_the_plan_on_record(self, service, plans, billing):
        _yearly(plans, paid_until=NOW + timedelta(days=1))

        outcome = _deliver(
            service,
            billing,
            SubscriptionEvent(subscription_id=_SUBSCRIPTION),
            live=True,
        )

        assert outcome is WebhookOutcome.RENEWED
        assert plans.rows[SPHERE_ID].paid_until == _PAID_UNTIL

    def test_ended_subscription_on_record_ends_the_plan(self, service, plans, billing):
        _yearly(plans)

        outcome = _deliver(
            service,
            billing,
            SubscriptionEvent(subscription_id=_SUBSCRIPTION),
            live=False,
        )

        assert outcome is WebhookOutcome.ENDED
        assert plans.rows[SPHERE_ID].kind is PlanKind.STANDARD

    def test_end_redelivered_after_the_plan_ended_is_stale(
        self, service, plans, billing
    ):
        ended = _yearly(plans, kind=PlanKind.STANDARD)

        outcome = _deliver(
            service,
            billing,
            SubscriptionEvent(subscription_id=_SUBSCRIPTION),
            live=False,
        )

        assert outcome is WebhookOutcome.STALE
        assert plans.rows == {SPHERE_ID: ended}

    def test_old_subscription_ending_leaves_the_current_plan(
        self, service, plans, billing
    ):
        current = _yearly(plans)

        outcome = _deliver(
            service, billing, SubscriptionEvent(subscription_id="sub_old"), live=False
        )

        assert outcome is WebhookOutcome.STALE
        assert plans.rows == {SPHERE_ID: current}

    def test_plan_recorded_by_hand_is_left_alone_while_it_lasts(
        self, service, plans, billing
    ):
        manual = _yearly(plans, source=PlanSource.MANUAL, paid_until=None)

        outcome = _deliver(
            service, billing, SubscriptionEvent(subscription_id="sub_new"), live=True
        )

        assert outcome is WebhookOutcome.STALE
        assert plans.rows == {SPHERE_ID: manual}

    def test_lapsed_plan_recorded_by_hand_gives_way_to_stripe(
        self, service, plans, billing
    ):
        _yearly(plans, source=PlanSource.MANUAL, paid_until=_LAPSED)

        outcome = _deliver(
            service, billing, SubscriptionEvent(subscription_id="sub_new"), live=True
        )

        assert outcome is WebhookOutcome.SUBSCRIBED
        assert plans.rows[SPHERE_ID].source is PlanSource.STRIPE
        assert plans.rows[SPHERE_ID].paid_until == _PAID_UNTIL
