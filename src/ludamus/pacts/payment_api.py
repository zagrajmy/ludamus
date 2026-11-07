"""The payment provider port: what a Stripe webhook tells us, and how it fails.

Two Stripe surfaces talk to us. Organizers' connected accounts sell tickets
(`pacts.tickets`), Zagrajmy's own account bills spheres' deals
(`pacts.billing`). Both deliver webhooks; the adapter verifies each one and
turns it into exactly one of the event types below, so no mill reads Stripe's
JSON or checks which optional field happens to be set.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class PaymentProviderError(Exception):
    """The provider refused or could not be reached; nothing was charged."""


class InvalidWebhookError(Exception):
    """The payload is not signed by Stripe with our secret, or is not JSON."""


class CheckoutStage(StrEnum):
    COMPLETED = "checkout.session.completed"
    ASYNC_SUCCEEDED = "checkout.session.async_payment_succeeded"
    ASYNC_FAILED = "checkout.session.async_payment_failed"
    EXPIRED = "checkout.session.expired"


class WebhookOutcome(StrEnum):
    """What a delivery did; logged and returned to Stripe as the response body."""

    PAID = "paid"
    AWAITING_PAYMENT = "awaiting_payment"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    # One of our orders refunded in part from the Stripe dashboard: its
    # tickets stay valid, the organizer decides the rest.
    PARTLY_REFUNDED = "partly_refunded"
    ACCOUNT_UPDATED = "account_updated"
    SUBSCRIBED = "subscribed"
    RENEWED = "renewed"
    ENDED = "ended"
    # The order or plan is already past this step: a redelivery, or events
    # arriving out of order.
    STALE = "stale"
    # Nothing of ours: another product on the organizer's account, an account
    # or customer we never created, an event type we do not act on.
    NOT_OURS = "not_ours"


class AccountState(BaseModel):
    details_submitted: bool
    charges_enabled: bool
    payouts_enabled: bool


class CheckoutEvent(BaseModel):
    """A ticket order's Checkout Session."""

    stage: CheckoutStage
    session_id: str
    paid: bool
    payment_intent_id: str
    # What the buyer typed into Checkout; empty until they did.
    email: str = ""


class RefundEvent(BaseModel):
    payment_intent_id: str
    fully_refunded: bool


class AccountEvent(BaseModel):
    account_id: str
    state: AccountState


class SubscriptionEvent(BaseModel):
    # Only which one, and whose: events arrive out of order, so what the
    # subscription is now is read from Stripe, never from the event.
    subscription_id: str
    customer_id: str


class UnhandledEvent(BaseModel):
    type: str


type StripeWebhookEvent = (
    CheckoutEvent | RefundEvent | AccountEvent | SubscriptionEvent | UnhandledEvent
)
