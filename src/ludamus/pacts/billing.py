"""What a sphere pays Zagrajmy, and what it gets for it.

Two things a sphere's plan holds, kept apart on purpose:

- **Terms:** the money. Every sphere pays a share of the tickets it sells here
  (`STANDARD_TICKET_FEE_BPS` unless a deal says less) and, if a deal says so,
  a fixed yearly price on top or instead.
- **Technical Partner:** the outcome. The Zagrajmy team runs the technical side
  of the convention with the organizers: setup, the programme, help during the
  event. It is agreed per convention, never bought by clicking.

A maintainer records a deal in the admin. Its terms hold until `paid_until`
(open-ended without one). A deal billed through a Stripe subscription
(`PlanSource.STRIPE`) has `paid_until` kept current by Stripe's webhooks; one
paid by bank transfer (`PlanSource.MANUAL`) is left alone.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.payment_api import StripeWebhookEvent, WebhookOutcome

# Zagrajmy's share of every ticket order, in basis points (350 = 3.5%), taken
# as the Stripe application fee. A deal may lower it, never raise it.
STANDARD_TICKET_FEE_BPS = 350


class PlanSource(StrEnum):
    STRIPE = "stripe"
    MANUAL = "manual"


class SpherePlanDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sphere_id: int
    technical_partner: bool
    # None: the standard rate.
    ticket_fee_bps: int | None
    # Minor units (grosze); None: no fixed price.
    yearly_price: int | None
    source: PlanSource
    paid_until: datetime | None
    stripe_customer_id: str
    stripe_subscription_id: str


class PlanTermsDTO(BaseModel):
    """What applies to a sphere right now: its deal while it lasts, else none."""

    technical_partner: bool
    ticket_fee_bps: int
    yearly_price: int | None
    # When the deal ends; None for no deal, or a deal without an end.
    paid_until: datetime | None
    has_deal: bool


class SubscriptionState(BaseModel):
    """A deal's Stripe subscription as Stripe has it now."""

    # Stripe still bills it: paid up, or a failed renewal it is retrying.
    live: bool
    # The end of the period paid for; None if Stripe has no period on it.
    paid_until: datetime | None


class PlanPageDTO(BaseModel):
    """The plan as the sphere panel shows it."""

    terms: PlanTermsDTO
    # Zagrajmy's share of each ticket order, in percent.
    ticket_fee_percent: Decimal
    # The sphere has a Stripe customer, so the billing portal has something
    # to show: invoices, the card on file.
    has_billing_history: bool


class SpherePlanData(TypedDict, total=False):
    paid_until: datetime | None
    stripe_subscription_id: str


class SpherePlanRepositoryProtocol(Protocol):
    @staticmethod
    def read(*, sphere_id: int) -> SpherePlanDTO | None: ...
    @staticmethod
    def save(*, sphere_id: int, data: SpherePlanData) -> SpherePlanDTO: ...
    @staticmethod
    def lock_by_customer(*, customer_id: str) -> SpherePlanDTO | None: ...


class PlanBillingProtocol(Protocol):
    """Zagrajmy's own Stripe account, billing spheres for their deals."""

    @property
    def enabled(self) -> bool: ...
    def billing_portal_url(self, *, customer_id: str, return_url: str) -> str: ...
    def read_subscription(self, *, subscription_id: str) -> SubscriptionState: ...
    def parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> StripeWebhookEvent: ...


class PlanServiceProtocol(Protocol):
    def page(self, *, sphere_id: int) -> PlanPageDTO: ...
    def billing_portal_url(self, *, sphere_id: int, return_url: str) -> str: ...
    def handle_webhook(self, *, payload: bytes, signature: str) -> WebhookOutcome: ...
