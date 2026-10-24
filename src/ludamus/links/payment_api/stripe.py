"""Stripe, the payment provider: the only module that speaks its API.

Two clients over one SDK. `StripeConnect` acts on organizers' connected
accounts (onboarding, ticket Checkout, refunds); `StripeBilling` acts on
Zagrajmy's own account (the yearly plan). Each verifies its own webhook
endpoint's signature and flattens the payload into a `StripeWebhookEvent`.

Unconfigured (no API key) both report `enabled = False` and refuse every call
with `PaymentProviderError`, so a deployment without Stripe shows "payments
are not available" instead of failing on first click.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import stripe
from pydantic import BaseModel, Field, JsonValue, ValidationError

from ludamus.pacts.billing import PlanBillingProtocol, SubscriptionState
from ludamus.pacts.payment_api import (
    AccountEvent,
    AccountState,
    CheckoutEvent,
    CheckoutStage,
    InvalidWebhookError,
    PaymentProviderError,
    RefundEvent,
    SubscriptionEvent,
    UnhandledEvent,
)
from ludamus.pacts.tickets import CheckoutSessionDTO, TicketPaymentsProtocol

if TYPE_CHECKING:
    from collections.abc import Generator

    from ludamus.pacts.payment_api import StripeWebhookEvent
    from ludamus.pacts.tickets import CheckoutRequest

logger = logging.getLogger(__name__)

# Under the SDK's 80 s: a refund holds its order's row lock while it waits,
# and a webhook for that order waits on the lock.
_TIMEOUT_SECONDS = 20
# Stripe's own default: a signature older than this is a replay.
_SIGNATURE_TOLERANCE_SECONDS = 300
_PAID_STATUSES = frozenset({"paid", "no_payment_required"})
# Subscription states Stripe still bills: a failed renewal is retried
# (past_due) before the subscription ends.
_LIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing", "past_due"})
_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)


def build_client(api_key: str) -> stripe.StripeClient | None:
    # requests rather than the SDK's pick: it honours the egress proxy and is
    # what the tests intercept.
    return (
        stripe.StripeClient(
            api_key, http_client=stripe.RequestsClient(timeout=_TIMEOUT_SECONDS)
        )
        if api_key
        else None
    )


def _require(client: stripe.StripeClient | None) -> stripe.StripeClient:
    if client is None:
        message = "Stripe is not configured on this deployment."
        raise PaymentProviderError(message)
    return client


@contextmanager
def _call(what: str) -> Generator[None]:
    """Turn any SDK failure into the one error mills know about."""
    try:
        yield
    except stripe.StripeError as exc:
        logger.warning("Stripe %s failed: %s: %s", what, type(exc).__name__, exc)
        raise PaymentProviderError(str(exc)) from exc


class StripeConnect(TicketPaymentsProtocol):
    def __init__(
        self,
        *,
        client: stripe.StripeClient | None,
        webhook_secret: str,
        idempotency_namespace: str,
    ) -> None:
        self._client = client
        self._webhook_secret = webhook_secret
        self._namespace = idempotency_namespace

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def create_account(self, *, sphere_id: int, email: str) -> str:
        client = _require(self._client)
        with _call("account create"):
            account = client.v1.accounts.create(
                params={
                    "email": email,
                    # A full Stripe account the organizer owns: Stripe's fee
                    # comes off their balance (the brief's "on top of"), and
                    # disputes are between them and Stripe.
                    "controller": {
                        "fees": {"payer": "account"},
                        "losses": {"payments": "stripe"},
                        "stripe_dashboard": {"type": "full"},
                    },
                    "metadata": {"sphere_id": str(sphere_id)},
                },
                # Two managers clicking at once get one account, not two.
                options={
                    "idempotency_key": f"{self._namespace}-payout-account-{sphere_id}"
                },
            )
        return account.id

    def onboarding_url(
        self, *, account_id: str, refresh_url: str, return_url: str
    ) -> str:
        client = _require(self._client)
        with _call("account link"):
            link = client.v1.account_links.create(
                params={
                    "account": account_id,
                    "refresh_url": refresh_url,
                    "return_url": return_url,
                    "type": "account_onboarding",
                }
            )
        return link.url

    def read_account(self, *, account_id: str) -> AccountState:
        client = _require(self._client)
        with _call("account read"):
            account = client.v1.accounts.retrieve(account_id)
        return AccountState(
            details_submitted=bool(account.details_submitted),
            charges_enabled=bool(account.charges_enabled),
            payouts_enabled=bool(account.payouts_enabled),
        )

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSessionDTO:
        client = _require(self._client)
        reference = str(request.order_pk)
        with _call("checkout create"):
            session = client.v1.checkout.sessions.create(
                params={
                    "mode": "payment",
                    "line_items": [
                        {
                            "quantity": line.quantity,
                            "price_data": {
                                "currency": request.currency,
                                "unit_amount": line.unit_amount,
                                "product_data": {"name": line.name},
                            },
                        }
                        for line in request.lines
                    ],
                    "payment_intent_data": {
                        "application_fee_amount": request.application_fee,
                        "metadata": {"ticket_order": reference},
                    },
                    "customer_email": request.customer_email,
                    "client_reference_id": reference,
                    "metadata": {"ticket_order": reference},
                    "success_url": request.success_url,
                    "cancel_url": request.cancel_url,
                    "expires_at": int(request.expires_at.timestamp()),
                },
                options={"stripe_account": request.account_id},
            )
        if not session.url:
            message = "Stripe returned a Checkout Session without a URL."
            raise PaymentProviderError(message)
        return CheckoutSessionDTO(id=session.id, url=session.url)

    def expire_checkout(self, *, account_id: str, session_id: str) -> None:
        client = _require(self._client)
        with _call("checkout expire"):
            client.v1.checkout.sessions.expire(
                session_id, options={"stripe_account": account_id}
            )

    def refund(self, *, account_id: str, payment_intent_id: str) -> None:
        # No idempotency key: Stripe would replay a refused refund for a day;
        # the order's status guard is what stops a double refund.
        self._refund(payment_intent_id, options={"stripe_account": account_id})

    def refund_once(self, *, account_id: str, payment_intent_id: str) -> None:
        # No order guards this one: a refund that went through but timed out
        # must replay as done when the webhook retries, not fail as a second.
        self._refund(
            payment_intent_id,
            options={
                "stripe_account": account_id,
                "idempotency_key": f"{self._namespace}-refund-{payment_intent_id}",
            },
        )

    def _refund(
        self, payment_intent_id: str, *, options: stripe.RequestOptions
    ) -> None:
        client = _require(self._client)
        with _call("refund"):
            client.v1.refunds.create(
                params={
                    "payment_intent": payment_intent_id,
                    # A refunded ticket was not sold: Zagrajmy's share goes
                    # back to the organizer too.
                    "refund_application_fee": True,
                },
                options=options,
            )

    def parse_webhook(self, *, payload: bytes, signature: str) -> StripeWebhookEvent:
        return parse_event(
            payload=payload, signature=signature, secret=self._webhook_secret
        )


class StripeBilling(PlanBillingProtocol):
    def __init__(
        self,
        *,
        client: stripe.StripeClient | None,
        webhook_secret: str,
        yearly_price_id: str,
        idempotency_namespace: str,
    ) -> None:
        self._client = client
        self._webhook_secret = webhook_secret
        self._yearly_price_id = yearly_price_id
        self._namespace = idempotency_namespace

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self._yearly_price_id)

    def create_customer(self, *, sphere_id: int, name: str, email: str) -> str:
        client = _require(self._client)
        with _call("customer create"):
            customer = client.v1.customers.create(
                params={
                    "name": name,
                    "email": email,
                    "metadata": {"sphere_id": str(sphere_id)},
                },
                options={
                    "idempotency_key": f"{self._namespace}-sphere-customer-{sphere_id}"
                },
            )
        return customer.id

    def create_plan_checkout(
        self, *, sphere_id: int, customer_id: str, success_url: str, cancel_url: str
    ) -> str:
        client = _require(self._client)
        with _call("plan checkout"):
            session = client.v1.checkout.sessions.create(
                params={
                    "mode": "subscription",
                    "customer": customer_id,
                    "line_items": [{"price": self._yearly_price_id, "quantity": 1}],
                    "client_reference_id": str(sphere_id),
                    # Polish organizations need a VAT invoice with their NIP.
                    "tax_id_collection": {"enabled": True},
                    "billing_address_collection": "required",
                    "customer_update": {"name": "auto", "address": "auto"},
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                }
            )
        if not session.url:
            message = "Stripe returned a Checkout Session without a URL."
            raise PaymentProviderError(message)
        return session.url

    def billing_portal_url(self, *, customer_id: str, return_url: str) -> str:
        client = _require(self._client)
        with _call("billing portal"):
            portal = client.v1.billing_portal.sessions.create(
                params={"customer": customer_id, "return_url": return_url}
            )
        return portal.url

    def has_live_subscription(self, *, customer_id: str) -> bool:
        client = _require(self._client)
        with _call("subscription list"):
            subscriptions = client.v1.subscriptions.list(
                params={"customer": customer_id, "limit": 100}
            )
        return any(
            subscription.status in _LIVE_SUBSCRIPTION_STATUSES
            for subscription in subscriptions.data
        )

    def read_subscription(self, *, subscription_id: str) -> SubscriptionState:
        client = _require(self._client)
        with _call("subscription read"):
            subscription = client.v1.subscriptions.retrieve(subscription_id)
        period_ends = [item.current_period_end for item in subscription.items.data]
        return SubscriptionState(
            live=subscription.status in _LIVE_SUBSCRIPTION_STATUSES,
            paid_until=(
                datetime.fromtimestamp(max(period_ends), tz=UTC)
                if period_ends
                else None
            ),
        )

    def parse_webhook(self, *, payload: bytes, signature: str) -> StripeWebhookEvent:
        return parse_event(
            payload=payload, signature=signature, secret=self._webhook_secret
        )


class _Ref(BaseModel):
    # An expandable field Stripe sent expanded: the resource, carrying its id.
    id: str = ""


type _IdOrResource = str | _Ref | None


def _id(value: _IdOrResource) -> str:
    return value if isinstance(value, str) else "" if value is None else value.id


class _CheckoutSession(BaseModel):
    id: str
    mode: str = ""
    payment_status: str = ""
    payment_intent: _IdOrResource = None
    customer: _IdOrResource = None
    subscription: _IdOrResource = None


class _Charge(BaseModel):
    payment_intent: _IdOrResource = None
    refunded: bool = False


class _Account(BaseModel):
    id: str
    details_submitted: bool = False
    charges_enabled: bool = False
    payouts_enabled: bool = False


class _Subscription(BaseModel):
    id: str
    customer: _IdOrResource = None


class _EnvelopeData(BaseModel):
    resource: dict[str, JsonValue] = Field(alias="object")


class _Envelope(BaseModel):
    type: str
    account: str | None = None
    data: _EnvelopeData


def parse_event(*, payload: bytes, signature: str, secret: str) -> StripeWebhookEvent:
    if not secret:
        message = "No webhook secret configured."
        raise InvalidWebhookError(message)
    try:
        stripe.WebhookSignature.verify_header(
            payload.decode(), signature, secret, _SIGNATURE_TOLERANCE_SECONDS
        )
        return _event(_Envelope.model_validate_json(payload))
    # SignatureVerificationError is a StripeError; its own class is untyped.
    except (stripe.StripeError, UnicodeDecodeError, ValidationError) as exc:
        raise InvalidWebhookError(str(exc)) from exc


def _event(envelope: _Envelope) -> StripeWebhookEvent:
    raw = envelope.data.resource
    if envelope.type in CheckoutStage:
        return _checkout_event(CheckoutStage(envelope.type), raw)
    if envelope.type in _SUBSCRIPTION_EVENTS:
        subscription = _Subscription.model_validate(raw)
        return SubscriptionEvent(
            subscription_id=subscription.id, customer_id=_id(subscription.customer)
        )
    match envelope.type:
        case "charge.refunded":
            charge = _Charge.model_validate(raw)
            return RefundEvent(
                payment_intent_id=_id(charge.payment_intent),
                fully_refunded=charge.refunded,
            )
        case "account.updated":
            account = _Account.model_validate(raw)
            return AccountEvent(
                account_id=envelope.account or account.id,
                state=AccountState(
                    details_submitted=account.details_submitted,
                    charges_enabled=account.charges_enabled,
                    payouts_enabled=account.payouts_enabled,
                ),
            )
    return UnhandledEvent(type=envelope.type)


def _checkout_event(
    stage: CheckoutStage, raw: dict[str, JsonValue]
) -> CheckoutEvent | SubscriptionEvent | UnhandledEvent:
    session = _CheckoutSession.model_validate(raw)
    match session.mode:
        case "payment":
            return CheckoutEvent(
                stage=stage,
                session_id=session.id,
                paid=session.payment_status in _PAID_STATUSES,
                payment_intent_id=_id(session.payment_intent),
            )
        case "subscription" if stage is CheckoutStage.COMPLETED and (
            subscription_id := _id(session.subscription)
        ):
            # The yearly plan bought: what it now is, Stripe is asked.
            return SubscriptionEvent(
                subscription_id=subscription_id, customer_id=_id(session.customer)
            )
    # A setup-mode session, say, or a subscription not yet made.
    return UnhandledEvent(type=stage)
