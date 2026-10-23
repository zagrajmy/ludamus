"""What a sphere pays Zagrajmy: its plan, and the Stripe billing behind it.

Every sphere is on the standard plan unless it holds the yearly one. The
standard plan costs nothing up front; Zagrajmy earns a share of the tickets
the sphere sells here (`pacts.tickets`). The yearly plan is for conventions
that run their programme on Zagrajmy but sell tickets somewhere else, so there
is no ticket to take a share of: the sphere pays once a year instead.

The yearly plan is bought self-serve through Stripe Checkout and lives on as a
Stripe subscription; a maintainer may also record one paid by bank transfer
(`PlanSource.MANUAL`) in the admin.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.payment_api import StripeWebhookEvent


class PlanKind(StrEnum):
    STANDARD = "standard"
    WHITE_GLOVE = "white_glove"


class PlanSource(StrEnum):
    STRIPE = "stripe"
    MANUAL = "manual"


class SpherePlanDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: PlanKind
    source: PlanSource
    paid_until: datetime | None
    stripe_customer_id: str
    stripe_subscription_id: str


class PlanPageDTO(BaseModel):
    """The plan as the sphere panel shows it."""

    kind: PlanKind
    source: PlanSource | None
    paid_until: datetime | None
    # The yearly plan can be bought: Stripe billing is configured here and the
    # sphere does not already hold the plan.
    can_subscribe: bool
    # The sphere has a Stripe customer, so the billing portal has something
    # to show: invoices, the card on file, cancelling.
    can_manage: bool


class SpherePlanData(TypedDict, total=False):
    kind: PlanKind
    source: PlanSource
    paid_until: datetime | None
    stripe_customer_id: str
    stripe_subscription_id: str


class SpherePlanRepositoryProtocol(Protocol):
    @staticmethod
    def read(*, sphere_id: int) -> SpherePlanDTO | None: ...
    @staticmethod
    def save(*, sphere_id: int, data: SpherePlanData) -> SpherePlanDTO: ...
    @staticmethod
    def find_sphere_by_customer(*, customer_id: str) -> int | None: ...


class PlanBillingProtocol(Protocol):
    """Zagrajmy's own Stripe account, billing spheres for the yearly plan."""

    @property
    def enabled(self) -> bool: ...
    def create_customer(self, *, sphere_id: int, name: str, email: str) -> str: ...
    def create_plan_checkout(
        self,
        *,
        sphere_id: int,
        customer_id: str,
        email: str,
        success_url: str,
        cancel_url: str,
    ) -> str: ...
    def billing_portal_url(self, *, customer_id: str, return_url: str) -> str: ...
    def parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> StripeWebhookEvent: ...


class PlanServiceProtocol(Protocol):
    def page(self, *, sphere_id: int) -> PlanPageDTO: ...
    def start_yearly_checkout(
        self,
        *,
        sphere_id: int,
        sphere_name: str,
        email: str,
        success_url: str,
        cancel_url: str,
    ) -> str: ...
    def billing_portal_url(self, *, sphere_id: int, return_url: str) -> str: ...
    def handle_webhook(self, *, payload: bytes, signature: str) -> str: ...
