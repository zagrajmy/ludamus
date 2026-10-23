"""The payment provider port: what a Stripe webhook tells us, and how it fails.

Two Stripe surfaces talk to us. Organizers' connected accounts sell tickets
(`pacts.tickets`), Zagrajmy's own account bills the yearly plan
(`pacts.billing`). Both deliver webhooks; the adapter verifies and flattens
each one into a `StripeWebhookEvent` so no mill ever reads Stripe's JSON.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class PaymentProviderError(Exception):
    """The provider refused or could not be reached; nothing was charged."""


class InvalidWebhookError(Exception):
    """The payload is not signed by Stripe with our secret, or is not JSON."""


class WebhookEventKind(StrEnum):
    CHECKOUT_COMPLETED = "checkout.session.completed"
    CHECKOUT_ASYNC_SUCCEEDED = "checkout.session.async_payment_succeeded"
    CHECKOUT_ASYNC_FAILED = "checkout.session.async_payment_failed"
    CHECKOUT_EXPIRED = "checkout.session.expired"
    CHARGE_REFUNDED = "charge.refunded"
    ACCOUNT_UPDATED = "account.updated"
    INVOICE_PAID = "invoice.paid"
    SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    SUBSCRIPTION_DELETED = "customer.subscription.deleted"


class AccountState(BaseModel):
    details_submitted: bool
    charges_enabled: bool
    payouts_enabled: bool


class CheckoutSessionFacts(BaseModel):
    session_id: str
    # "payment" for a ticket order, "subscription" for the yearly plan.
    mode: str
    paid: bool
    payment_intent_id: str = ""
    customer_id: str = ""


class RefundFacts(BaseModel):
    payment_intent_id: str
    fully_refunded: bool


class SubscriptionFacts(BaseModel):
    customer_id: str
    subscription_id: str
    # Stripe's subscription status ("active", "past_due", "canceled", …);
    # "active" for a paid invoice, which proves the period it covers.
    status: str
    period_end: datetime | None


class StripeWebhookEvent(BaseModel):
    """One verified webhook, with the facts its kind carries and nothing else.

    `kind` is None for an event type we subscribe to by accident or Stripe
    adds later: acknowledged, recorded, ignored.
    """

    id: str
    type: str
    kind: WebhookEventKind | None
    # The connected account the event happened on; empty on our own account.
    account_id: str = ""
    checkout: CheckoutSessionFacts | None = None
    refund: RefundFacts | None = None
    account: AccountState | None = None
    subscription: SubscriptionFacts | None = None


class StripeEventLogProtocol(Protocol):
    @staticmethod
    def record(*, event_id: str, event_type: str) -> bool:
        """Remember a delivered event; False when it was already seen."""
