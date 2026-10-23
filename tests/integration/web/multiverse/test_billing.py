"""The sphere's Plan & payouts page and the Stripe hand-offs behind it.

How it could go wrong: a comms member (or a stranger) connects a Stripe
account or buys a plan; a second click creates a second connected account; the
account is created with the platform paying Stripe's fees or carrying the
losses; the yearly plan is bought without a customer the webhooks can find.
"""

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
ONBOARDING_URL = "https://connect.stripe.com/setup/e/acct_test/abc"
PORTAL_URL = "https://billing.stripe.com/p/session/test_portal"


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
