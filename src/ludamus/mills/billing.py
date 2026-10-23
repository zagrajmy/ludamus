"""The sphere's plan: which one it is on, buying the yearly one, and Stripe's word.

`specs.billing.effective_plan` says which plan a sphere holds. Stripe webhooks
keep a Stripe-billed plan current; a plan a maintainer recorded by hand
(`PlanSource.MANUAL`) is theirs to change, and webhooks leave it be.

Stripe does not deliver events in order, so each one is checked against the
subscription the sphere has on record: an event about another (an older,
cancelled) subscription changes nothing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanKind, PlanPageDTO, PlanServiceProtocol, PlanSource
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import (
    CheckoutEvent,
    CheckoutMode,
    CheckoutStage,
    InvoicePaidEvent,
    SubscriptionChangedEvent,
    WebhookOutcome,
)
from ludamus.specs.billing import ACTIVE_SUBSCRIPTION_STATUSES, effective_plan
from ludamus.specs.tickets import platform_fee_percent

if TYPE_CHECKING:
    from ludamus.pacts.billing import (
        PlanBillingProtocol,
        SpherePlanData,
        SpherePlanDTO,
        SpherePlanRepositoryProtocol,
    )
    from ludamus.pacts.payment_api import StripeWebhookEvent
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


class PlanService(PlanServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        plans: SpherePlanRepositoryProtocol,
        billing: PlanBillingProtocol,
    ) -> None:
        self._transaction = transaction
        self._plans = plans
        self._billing = billing

    def page(self, *, sphere_id: int) -> PlanPageDTO:
        plan = self._plans.read(sphere_id=sphere_id)
        kind = effective_plan(plan, now=datetime.now(tz=UTC))
        yearly = plan if kind is PlanKind.WHITE_GLOVE else None
        return PlanPageDTO(
            kind=kind,
            ticket_fee_percent=platform_fee_percent(kind),
            source=yearly.source if yearly else None,
            paid_until=yearly.paid_until if yearly else None,
            can_subscribe=self._billing.enabled and yearly is None,
            can_manage=self._billing.enabled
            and plan is not None
            and bool(plan.stripe_customer_id),
        )

    def start_yearly_checkout(
        self,
        *,
        sphere_id: int,
        sphere_name: str,
        email: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        plan = self._plans.read(sphere_id=sphere_id)
        if not (customer_id := plan.stripe_customer_id if plan is not None else ""):
            # Created before Checkout, so every webhook that follows (the
            # invoice may beat the session) finds the sphere by customer.
            customer_id = self._billing.create_customer(
                sphere_id=sphere_id, name=sphere_name, email=email
            )
            with self._transaction.atomic():
                self._plans.save(
                    sphere_id=sphere_id, data={"stripe_customer_id": customer_id}
                )
        return self._billing.create_plan_checkout(
            sphere_id=sphere_id,
            customer_id=customer_id,
            success_url=success_url,
            cancel_url=cancel_url,
        )

    def billing_portal_url(self, *, sphere_id: int, return_url: str) -> str:
        plan = self._plans.read(sphere_id=sphere_id)
        if plan is None or not plan.stripe_customer_id:
            raise NotFoundError
        return self._billing.billing_portal_url(
            customer_id=plan.stripe_customer_id, return_url=return_url
        )

    def handle_webhook(self, *, payload: bytes, signature: str) -> WebhookOutcome:
        event = self._billing.parse_webhook(payload=payload, signature=signature)
        with self._transaction.atomic():
            return self._apply(event)

    def _apply(self, event: StripeWebhookEvent) -> WebhookOutcome:
        match event:
            case CheckoutEvent(
                mode=CheckoutMode.SUBSCRIPTION, stage=CheckoutStage.COMPLETED, paid=True
            ):
                return self._subscribed(event)
            case InvoicePaidEvent():
                return self._invoice_paid(event)
            case SubscriptionChangedEvent():
                return self._subscription_changed(event)
        return WebhookOutcome.NOT_OURS

    def _find(self, customer_id: str) -> tuple[int, SpherePlanDTO] | None:
        sphere_id = self._plans.find_sphere_by_customer(customer_id=customer_id)
        if sphere_id is None or (plan := self._plans.read(sphere_id=sphere_id)) is None:
            return None
        return sphere_id, plan

    def _subscribed(self, event: CheckoutEvent) -> WebhookOutcome:
        if (found := self._find(event.customer_id)) is None:
            return WebhookOutcome.NOT_OURS
        sphere_id, plan = found
        if plan.stripe_subscription_id == event.subscription_id:
            # The invoice landed first and already recorded this subscription.
            return WebhookOutcome.STALE
        # A new subscription replaces whatever was on record, a lapsed manual
        # deal included. Held with no end date until its first invoice says.
        self._plans.save(
            sphere_id=sphere_id,
            data={
                "kind": PlanKind.WHITE_GLOVE,
                "source": PlanSource.STRIPE,
                "paid_until": None,
                "stripe_subscription_id": event.subscription_id,
            },
        )
        logger.info("Yearly plan bought: sphere=%s", sphere_id)
        return WebhookOutcome.SUBSCRIBED

    def _invoice_paid(self, event: InvoicePaidEvent) -> WebhookOutcome:
        if (
            not event.subscription_id
            or (found := self._find(event.customer_id)) is None
        ):
            # A one-off invoice is not the yearly plan.
            return WebhookOutcome.NOT_OURS
        sphere_id, plan = found
        if not _is_current(plan, subscription_id=event.subscription_id):
            return WebhookOutcome.STALE
        data: SpherePlanData = {
            "kind": PlanKind.WHITE_GLOVE,
            "source": PlanSource.STRIPE,
            "stripe_subscription_id": event.subscription_id,
        }
        # A payload without a period keeps the date we have.
        if event.period_end is not None:
            data["paid_until"] = event.period_end
        self._plans.save(sphere_id=sphere_id, data=data)
        logger.info("Yearly plan paid: sphere=%s until=%s", sphere_id, event.period_end)
        return WebhookOutcome.RENEWED

    def _subscription_changed(self, event: SubscriptionChangedEvent) -> WebhookOutcome:
        if (found := self._find(event.customer_id)) is None:
            return WebhookOutcome.NOT_OURS
        sphere_id, plan = found
        if not _is_current(plan, subscription_id=event.subscription_id):
            return WebhookOutcome.STALE
        if not event.deleted and event.status in ACTIVE_SUBSCRIPTION_STATUSES:
            # Renewal dates come with the invoice; nothing else to record.
            return WebhookOutcome.STALE
        self._plans.save(sphere_id=sphere_id, data={"kind": PlanKind.STANDARD})
        logger.info("Yearly plan ended: sphere=%s status=%s", sphere_id, event.status)
        return WebhookOutcome.ENDED


def _is_current(plan: SpherePlanDTO, *, subscription_id: str) -> bool:
    # A maintainer's deal is theirs; a subscription other than the one on
    # record is an old one, reported late.
    return plan.source is not PlanSource.MANUAL and plan.stripe_subscription_id in {
        "",
        subscription_id,
    }
