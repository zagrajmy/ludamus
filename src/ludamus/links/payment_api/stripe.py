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

from ludamus.pacts.billing import PlanBillingProtocol
from ludamus.pacts.payment_api import (
    AccountState,
    CheckoutSessionFacts,
    InvalidWebhookError,
    PaymentProviderError,
    RefundFacts,
    StripeWebhookEvent,
    SubscriptionFacts,
    WebhookEventKind,
)
from ludamus.pacts.tickets import CheckoutSessionDTO, TicketPaymentsProtocol

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from ludamus.pacts.tickets import CheckoutRequest

logger = logging.getLogger(__name__)

# Stripe's own default: a signature older than this is a replay.
_SIGNATURE_TOLERANCE_SECONDS = 300
_PAID_STATUSES = frozenset({"paid", "no_payment_required"})


def build_client(api_key: str) -> stripe.StripeClient | None:
    # requests rather than the SDK's pick: it honours the egress proxy and is
    # what the tests intercept.
    return (
        stripe.StripeClient(api_key, http_client=stripe.RequestsClient())
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
        self, *, client: stripe.StripeClient | None, webhook_secret: str
    ) -> None:
        self._client = client
        self._webhook_secret = webhook_secret

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
                options={"idempotency_key": f"payout-account-{sphere_id}-{email}"},
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
                options={
                    "stripe_account": request.account_id,
                    # A retried request for the same order reuses its session.
                    "idempotency_key": f"ticket-order-{reference}",
                },
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
        client = _require(self._client)
        with _call("refund"):
            client.v1.refunds.create(
                params={
                    "payment_intent": payment_intent_id,
                    # A refunded ticket was not sold: Zagrajmy's share goes
                    # back to the organizer too.
                    "refund_application_fee": True,
                },
                options={
                    "stripe_account": account_id,
                    "idempotency_key": f"refund-{payment_intent_id}",
                },
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
    ) -> None:
        self._client = client
        self._webhook_secret = webhook_secret
        self._yearly_price_id = yearly_price_id

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
                options={"idempotency_key": f"sphere-customer-{sphere_id}"},
            )
        return customer.id

    def create_plan_checkout(
        self,
        *,
        sphere_id: int,
        customer_id: str,
        email: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        client = _require(self._client)
        logger.info("Yearly plan checkout for sphere %s (%s)", sphere_id, email)
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

    def parse_webhook(self, *, payload: bytes, signature: str) -> StripeWebhookEvent:
        return parse_event(
            payload=payload, signature=signature, secret=self._webhook_secret
        )


class _Ref(BaseModel):
    # An expandable field Stripe sent expanded: the resource, carrying its id.
    id: str = ""


type _IdOrObject = str | _Ref | None


def _id(value: _IdOrObject) -> str:
    return value if isinstance(value, str) else "" if value is None else value.id


class _CheckoutObject(BaseModel):
    id: str
    mode: str = ""
    payment_status: str = ""
    payment_intent: _IdOrObject = None
    customer: _IdOrObject = None


class _ChargeObject(BaseModel):
    payment_intent: _IdOrObject = None
    refunded: bool = False


class _AccountObject(BaseModel):
    id: str
    details_submitted: bool = False
    charges_enabled: bool = False
    payouts_enabled: bool = False


class _Period(BaseModel):
    end: int | None = None


class _InvoiceLine(BaseModel):
    period: _Period = _Period()


class _InvoiceLines(BaseModel):
    data: list[_InvoiceLine] = []


class _SubscriptionDetails(BaseModel):
    subscription: _IdOrObject = None


class _InvoiceParent(BaseModel):
    subscription_details: _SubscriptionDetails | None = None


class _InvoiceObject(BaseModel):
    customer: _IdOrObject = None
    # Pre-2025 API versions name the subscription here; later ones under
    # parent.subscription_details.
    subscription: _IdOrObject = None
    parent: _InvoiceParent | None = None
    lines: _InvoiceLines = _InvoiceLines()


class _SubscriptionItem(BaseModel):
    current_period_end: int | None = None


class _SubscriptionItems(BaseModel):
    data: list[_SubscriptionItem] = []


class _SubscriptionObject(BaseModel):
    id: str
    customer: _IdOrObject = None
    status: str = ""
    # The period moved onto subscription items in 2025 API versions; older
    # payloads carry it on the subscription itself.
    current_period_end: int | None = None
    items: _SubscriptionItems = _SubscriptionItems()


class _EnvelopeData(BaseModel):
    resource: dict[str, JsonValue] = Field(alias="object")


class _Envelope(BaseModel):
    id: str
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
        return _flatten(_Envelope.model_validate_json(payload))
    # SignatureVerificationError is a StripeError; its own class is untyped.
    except (stripe.StripeError, UnicodeDecodeError, ValidationError) as exc:
        raise InvalidWebhookError(str(exc)) from exc


def _flatten(envelope: _Envelope) -> StripeWebhookEvent:
    try:
        kind: WebhookEventKind | None = WebhookEventKind(envelope.type)
    except ValueError:
        kind = None
    event = StripeWebhookEvent(
        id=envelope.id, type=envelope.type, kind=kind, account_id=envelope.account or ""
    )
    raw = envelope.data.resource
    match kind:
        case (
            WebhookEventKind.CHECKOUT_COMPLETED
            | WebhookEventKind.CHECKOUT_ASYNC_SUCCEEDED
            | WebhookEventKind.CHECKOUT_ASYNC_FAILED
            | WebhookEventKind.CHECKOUT_EXPIRED
        ):
            session = _CheckoutObject.model_validate(raw)
            event.checkout = CheckoutSessionFacts(
                session_id=session.id,
                mode=session.mode,
                paid=session.payment_status in _PAID_STATUSES,
                payment_intent_id=_id(session.payment_intent),
                customer_id=_id(session.customer),
            )
        case WebhookEventKind.CHARGE_REFUNDED:
            charge = _ChargeObject.model_validate(raw)
            event.refund = RefundFacts(
                payment_intent_id=_id(charge.payment_intent),
                fully_refunded=charge.refunded,
            )
        case WebhookEventKind.ACCOUNT_UPDATED:
            account = _AccountObject.model_validate(raw)
            event.account_id = event.account_id or account.id
            event.account = AccountState(
                details_submitted=account.details_submitted,
                charges_enabled=account.charges_enabled,
                payouts_enabled=account.payouts_enabled,
            )
        case WebhookEventKind.INVOICE_PAID:
            invoice = _InvoiceObject.model_validate(raw)
            details = invoice.parent.subscription_details if invoice.parent else None
            event.subscription = SubscriptionFacts(
                customer_id=_id(invoice.customer),
                subscription_id=_id(details.subscription if details else None)
                or _id(invoice.subscription),
                status="active",
                period_end=_latest(line.period.end for line in invoice.lines.data),
            )
        case (
            WebhookEventKind.SUBSCRIPTION_UPDATED
            | WebhookEventKind.SUBSCRIPTION_DELETED
        ):
            subscription = _SubscriptionObject.model_validate(raw)
            event.subscription = SubscriptionFacts(
                customer_id=_id(subscription.customer),
                subscription_id=subscription.id,
                status=subscription.status,
                period_end=_latest(
                    [
                        *(item.current_period_end for item in subscription.items.data),
                        subscription.current_period_end,
                    ]
                ),
            )
        case None:
            pass
    return event


def _latest(timestamps: Iterable[int | None]) -> datetime | None:
    values = [value for value in timestamps if value is not None]
    return datetime.fromtimestamp(max(values), tz=UTC) if values else None
