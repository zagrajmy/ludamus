"""The sphere's Plan & payouts page and the Stripe hand-offs behind it.

How it could go wrong: a comms member (or a stranger) connects a Stripe
account or buys a plan; a second click creates a second connected account; the
account is created with the platform paying Stripe's fees or carrying the
losses; the yearly plan is bought without a customer the webhooks can find.
"""

from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus
from urllib.parse import parse_qs

import pytest
import responses
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import PayoutAccount, SphereMembership, SpherePlan
from ludamus.pacts.billing import PlanKind, PlanPageDTO, PlanSource
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.tickets import PayoutPageDTO, PayoutStatus
from tests.integration.stripe_helpers import ACCOUNT_ID, API, connected_account
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.multiverse.helpers import (
    READ_ONLY_ROLE_ERROR,
    assert_not_a_sphere_manager,
    sphere_sidebar_context,
)

pytestmark = pytest.mark.usefixtures("stripe_settings")

BILLING_URL = reverse("multiverse:panel:billing")
CONNECT_URL = reverse("multiverse:panel:billing-connect")
RETURN_URL = reverse("multiverse:panel:billing-return")
RESUME_URL = reverse("multiverse:panel:billing-resume")
SUBSCRIBE_URL = reverse("multiverse:panel:billing-subscribe")
PORTAL_ACTION_URL = reverse("multiverse:panel:billing-portal")
ONBOARDING_URL = "https://connect.stripe.com/setup/e/acct_test/abc"
PORTAL_URL = "https://billing.stripe.com/p/session/test_portal"
PAID_UNTIL = datetime(2099, 1, 1, tzinfo=UTC)
STRIPE_DOWN = (
    messages.ERROR,
    "Stripe didn't respond. Nothing was changed; try again in a moment.",
)


@pytest.fixture(name="manager")
def manager_fixture(client, active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.MANAGER
    )
    client.force_login(active_user)
    return client


@pytest.fixture(name="comms")
def comms_fixture(client, active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.COMMS
    )
    client.force_login(active_user)
    return client


def _stripe_down(stripe_api, method, path):
    stripe_api.add(
        method,
        f"{API}{path}",
        json={"error": {"type": "api_error", "message": "down"}},
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def _without_email(user):
    user.email = ""
    user.save()


def _mock_onboarding(stripe_api):
    stripe_api.add(
        responses.POST, f"{API}/accounts", json={"id": ACCOUNT_ID, "object": "account"}
    )
    stripe_api.add(
        responses.POST,
        f"{API}/account_links",
        json={"object": "account_link", "url": ONBOARDING_URL},
    )


class TestBillingPage:
    def test_redirects_anonymous_user_to_login(self, client):
        response = client.get(BILLING_URL)

        assert_login_required(response, BILLING_URL)

    def test_refuses_a_stranger(self, authenticated_client):
        response = authenticated_client.get(BILLING_URL)

        assert_not_a_sphere_manager(response)

    def test_new_sphere_is_on_the_standard_plan_with_nothing_connected(self, manager):
        response = manager.get(BILLING_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/billing.html",
            context_data={
                **sphere_sidebar_context(active_nav="billing"),
                "plan": PlanPageDTO(
                    kind=PlanKind.STANDARD,
                    source=None,
                    paid_until=None,
                    can_subscribe=True,
                    has_billing_history=False,
                    ticket_fee_percent=Decimal("3.5"),
                ),
                "payouts": PayoutPageDTO(
                    status=PayoutStatus.NOT_CONNECTED,
                    available=True,
                    payouts_enabled=False,
                ),
                "can_manage": True,
            },
        )

    def test_back_from_checkout_before_the_webhook_says_it_is_on_its_way(self, manager):
        response = manager.get(f"{BILLING_URL}?subscribed=1")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/billing.html",
            context_data={
                **sphere_sidebar_context(active_nav="billing"),
                "plan": PlanPageDTO(
                    kind=PlanKind.STANDARD,
                    source=None,
                    paid_until=None,
                    can_subscribe=True,
                    has_billing_history=False,
                    ticket_fee_percent=Decimal("3.5"),
                ),
                "payouts": PayoutPageDTO(
                    status=PayoutStatus.NOT_CONNECTED,
                    available=True,
                    payouts_enabled=False,
                ),
                "can_manage": True,
            },
            messages=[
                (
                    messages.INFO,
                    (
                        "Thank you! Stripe is confirming the payment; the plan"
                        " switches over within a minute."
                    ),
                )
            ],
        )

    def test_back_from_checkout_after_the_webhook_says_nothing_more(
        self, manager, sphere
    ):
        SpherePlan.objects.create(
            sphere=sphere,
            kind=PlanKind.WHITE_GLOVE,
            source=PlanSource.STRIPE,
            paid_until=PAID_UNTIL,
            stripe_customer_id="cus_paid",
        )

        response = manager.get(f"{BILLING_URL}?subscribed=1")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/billing.html",
            context_data={
                **sphere_sidebar_context(active_nav="billing"),
                "plan": PlanPageDTO(
                    kind=PlanKind.WHITE_GLOVE,
                    source=PlanSource.STRIPE,
                    paid_until=PAID_UNTIL,
                    can_subscribe=False,
                    has_billing_history=True,
                    ticket_fee_percent=Decimal("3.5"),
                ),
                "payouts": PayoutPageDTO(
                    status=PayoutStatus.NOT_CONNECTED,
                    available=True,
                    payouts_enabled=False,
                ),
                "can_manage": True,
            },
        )

    def test_without_stripe_nothing_can_be_bought(self, manager, settings):
        settings.STRIPE_SECRET_KEY = ""

        response = manager.get(BILLING_URL)

        context = response.context_data
        assert (context["plan"].can_subscribe, context["payouts"].available) == (
            False,
            False,
        )


class TestConnect:
    def test_creates_an_account_the_organizer_owns(self, manager, sphere, stripe_api):
        _mock_onboarding(stripe_api)

        response = manager.post(CONNECT_URL)

        assert_response(response, HTTPStatus.FOUND, url=ONBOARDING_URL)
        assert PayoutAccount.objects.get().sphere_id == sphere.pk
        sent = parse_qs(stripe_api.calls[0].request.body)
        assert {
            key: value for key, value in sent.items() if key.startswith("controller")
        } == {
            "controller[fees][payer]": ["account"],
            "controller[losses][payments]": ["stripe"],
            "controller[stripe_dashboard][type]": ["full"],
        }
        link = parse_qs(stripe_api.calls[1].request.body)
        assert link["return_url"] == [f"http://testserver{RETURN_URL}"]
        assert link["refresh_url"] == [f"http://testserver{RESUME_URL}"]

    def test_without_an_email_nothing_is_created(
        self, manager, active_user, stripe_api
    ):
        _without_email(active_user)

        response = manager.post(CONNECT_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=BILLING_URL,
            messages=[
                (
                    messages.ERROR,
                    "Add an email address to your profile first: Stripe needs one.",
                )
            ],
        )
        assert not stripe_api.calls
        assert not PayoutAccount.objects.exists()

    def test_deployment_without_stripe_creates_nothing(self, manager, settings):
        settings.STRIPE_SECRET_KEY = ""

        response = manager.post(CONNECT_URL)

        assert_response(
            response, HTTPStatus.FOUND, url=BILLING_URL, messages=[STRIPE_DOWN]
        )
        assert not PayoutAccount.objects.exists()

    def test_stale_link_reuses_the_account(self, manager, sphere, stripe_api):
        connected_account(sphere, charges_enabled=False)
        _mock_onboarding(stripe_api)

        response = manager.get(RESUME_URL)

        assert_response(response, HTTPStatus.FOUND, url=ONBOARDING_URL)
        assert [call.request.url for call in stripe_api.calls] == [
            f"{API}/account_links"
        ]
        assert PayoutAccount.objects.count() == 1

    def test_stale_link_creates_no_account(self, manager, stripe_api):
        response = manager.get(RESUME_URL)

        assert_response(response, HTTPStatus.FOUND, url=BILLING_URL)
        assert not stripe_api.calls
        assert not PayoutAccount.objects.exists()

    def test_stale_link_while_stripe_is_down_goes_back_to_the_page(
        self, manager, sphere, stripe_api
    ):
        connected_account(sphere, charges_enabled=False)
        _stripe_down(stripe_api, responses.POST, "/account_links")

        response = manager.get(RESUME_URL)

        assert_response(
            response, HTTPStatus.FOUND, url=BILLING_URL, messages=[STRIPE_DOWN]
        )
        assert PayoutAccount.objects.count() == 1

    def test_comms_member_cannot_resume_even_by_get(self, comms, sphere, stripe_api):
        connected_account(sphere, charges_enabled=False)

        response = comms.get(RESUME_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert not stripe_api.calls

    def test_stripe_down_changes_nothing(self, manager, stripe_api):
        stripe_api.add(
            responses.POST,
            f"{API}/accounts",
            json={"error": {"type": "api_error", "message": "down"}},
            status=HTTPStatus.BAD_REQUEST,
        )

        response = manager.post(CONNECT_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=BILLING_URL,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Stripe didn't respond. Nothing was changed; try again in"
                        " a moment."
                    ),
                )
            ],
        )
        assert not PayoutAccount.objects.exists()

    def test_return_reads_the_account_from_stripe(self, manager, sphere, stripe_api):
        account = connected_account(sphere, charges_enabled=False)
        stripe_api.add(
            responses.GET,
            f"{API}/accounts/{ACCOUNT_ID}",
            json={
                "id": ACCOUNT_ID,
                "object": "account",
                "details_submitted": True,
                "charges_enabled": True,
                "payouts_enabled": True,
            },
        )

        response = manager.get(RETURN_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=BILLING_URL,
            messages=[
                (messages.SUCCESS, "Stripe is connected. You can sell tickets now.")
            ],
        )
        account.refresh_from_db()
        assert account.charges_enabled

    def test_return_with_details_missing_asks_to_continue_later(
        self, manager, sphere, stripe_api
    ):
        account = connected_account(sphere, charges_enabled=False)
        stripe_api.add(
            responses.GET,
            f"{API}/accounts/{ACCOUNT_ID}",
            json={
                "id": ACCOUNT_ID,
                "object": "account",
                "details_submitted": True,
                "charges_enabled": False,
                "payouts_enabled": False,
            },
        )

        response = manager.get(RETURN_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=BILLING_URL,
            messages=[
                (
                    messages.INFO,
                    (
                        "Stripe still needs a few details. Continue the setup"
                        " whenever you have them at hand."
                    ),
                )
            ],
        )
        account.refresh_from_db()
        assert (account.details_submitted, account.charges_enabled) == (True, False)

    def test_return_while_stripe_is_down_keeps_what_was_known(
        self, manager, sphere, stripe_api
    ):
        account = connected_account(sphere, charges_enabled=False)
        _stripe_down(stripe_api, responses.GET, f"/accounts/{ACCOUNT_ID}")

        response = manager.get(RETURN_URL)

        assert_response(
            response, HTTPStatus.FOUND, url=BILLING_URL, messages=[STRIPE_DOWN]
        )
        account.refresh_from_db()
        assert (account.details_submitted, account.charges_enabled) == (False, False)


class TestSubscribe:
    def test_creates_the_customer_before_checkout(self, manager, sphere, stripe_api):
        stripe_api.add(
            responses.POST,
            f"{API}/customers",
            json={"id": "cus_new", "object": "customer"},
        )
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions",
            json={
                "id": "cs_plan",
                "object": "checkout.session",
                "url": "https://checkout.stripe.com/c/pay/cs_plan",
            },
        )

        response = manager.post(SUBSCRIBE_URL)

        assert_response(
            response, HTTPStatus.FOUND, url="https://checkout.stripe.com/c/pay/cs_plan"
        )
        assert SpherePlan.objects.get(sphere=sphere).stripe_customer_id == "cus_new"
        sent = parse_qs(stripe_api.calls[1].request.body)
        assert (sent["mode"], sent["customer"], sent["line_items[0][price]"]) == (
            ["subscription"],
            ["cus_new"],
            ["price_yearly_test"],
        )
        assert "Stripe-Account" not in stripe_api.calls[1].request.headers

    def test_without_an_email_nothing_is_bought(self, manager, active_user, stripe_api):
        _without_email(active_user)

        response = manager.post(SUBSCRIBE_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=BILLING_URL,
            messages=[
                (
                    messages.ERROR,
                    "Add an email address to your profile first: invoices go there.",
                )
            ],
        )
        assert not stripe_api.calls
        assert not SpherePlan.objects.exists()

    def test_stripe_down_creates_no_customer(self, manager, stripe_api):
        _stripe_down(stripe_api, responses.POST, "/customers")

        response = manager.post(SUBSCRIBE_URL)

        assert_response(
            response, HTTPStatus.FOUND, url=BILLING_URL, messages=[STRIPE_DOWN]
        )
        assert not SpherePlan.objects.exists()

    def test_comms_member_cannot_buy_the_plan(self, comms, stripe_api):
        response = comms.post(SUBSCRIBE_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert not stripe_api.calls

    def test_a_subscription_stripe_holds_goes_to_the_portal(
        self, manager, sphere, stripe_api
    ):
        SpherePlan.objects.create(sphere=sphere, stripe_customer_id="cus_paid")
        stripe_api.add(
            responses.GET,
            f"{API}/subscriptions",
            json={
                "object": "list",
                "url": "/v1/subscriptions",
                "has_more": False,
                "data": [{"id": "sub_1", "object": "subscription", "status": "active"}],
            },
        )
        stripe_api.add(
            responses.POST,
            f"{API}/billing_portal/sessions",
            json={"object": "billing_portal.session", "url": PORTAL_URL},
        )

        response = manager.post(SUBSCRIBE_URL)

        assert_response(response, HTTPStatus.FOUND, url=PORTAL_URL)
        assert [call.request.path_url.split("?")[0] for call in stripe_api.calls] == [
            "/v1/subscriptions",
            "/v1/billing_portal/sessions",
        ]

    def test_a_cancelled_subscription_lets_the_plan_be_bought_again(
        self, manager, sphere, stripe_api
    ):
        SpherePlan.objects.create(sphere=sphere, stripe_customer_id="cus_lapsed")
        stripe_api.add(
            responses.GET,
            f"{API}/subscriptions",
            json={
                "object": "list",
                "url": "/v1/subscriptions",
                "has_more": False,
                "data": [
                    {"id": "sub_old", "object": "subscription", "status": "unpaid"}
                ],
            },
        )
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions",
            json={
                "id": "cs_plan",
                "object": "checkout.session",
                "url": "https://checkout.stripe.com/c/pay/cs_plan",
            },
        )

        response = manager.post(SUBSCRIBE_URL)

        assert_response(
            response, HTTPStatus.FOUND, url="https://checkout.stripe.com/c/pay/cs_plan"
        )
        assert parse_qs(stripe_api.calls[1].request.body)["customer"] == ["cus_lapsed"]

    def test_a_plan_held_by_hand_buys_nothing(self, manager, sphere, stripe_api):
        SpherePlan.objects.create(
            sphere=sphere, kind=PlanKind.WHITE_GLOVE, source=PlanSource.MANUAL
        )

        response = manager.post(SUBSCRIBE_URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"http://testserver{BILLING_URL}"
        )
        assert not stripe_api.calls


class TestBillingPortal:
    def test_opens_stripes_portal_for_the_spheres_customer(
        self, manager, sphere, stripe_api
    ):
        SpherePlan.objects.create(sphere=sphere, stripe_customer_id="cus_paid")
        stripe_api.add(
            responses.POST,
            f"{API}/billing_portal/sessions",
            json={"object": "billing_portal.session", "url": PORTAL_URL},
        )

        response = manager.post(PORTAL_ACTION_URL)

        assert_response(response, HTTPStatus.FOUND, url=PORTAL_URL)
        assert parse_qs(stripe_api.calls[0].request.body) == {
            "customer": ["cus_paid"],
            "return_url": [f"http://testserver{BILLING_URL}"],
        }

    def test_sphere_that_never_paid_has_no_portal(self, manager, stripe_api):
        response = manager.post(PORTAL_ACTION_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=BILLING_URL,
            messages=[(messages.ERROR, "This sphere has no billing history yet.")],
        )
        assert not stripe_api.calls

    def test_stripe_down_says_so(self, manager, sphere, stripe_api):
        SpherePlan.objects.create(sphere=sphere, stripe_customer_id="cus_paid")
        _stripe_down(stripe_api, responses.POST, "/billing_portal/sessions")

        response = manager.post(PORTAL_ACTION_URL)

        assert_response(
            response, HTTPStatus.FOUND, url=BILLING_URL, messages=[STRIPE_DOWN]
        )

    def test_comms_member_cannot_open_it(self, comms, sphere, stripe_api):
        SpherePlan.objects.create(sphere=sphere, stripe_customer_id="cus_paid")

        response = comms.post(PORTAL_ACTION_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert not stripe_api.calls
