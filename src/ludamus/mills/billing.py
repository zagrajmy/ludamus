"""The sphere's plan: which one it is on, buying the yearly one, and Stripe's word.

A sphere holds the yearly plan while its `SpherePlan` row says White Glove and
`paid_until` has not passed (no date: held until a maintainer says otherwise).
Stripe webhooks keep a Stripe-billed plan current; a plan a maintainer recorded
by hand (`PlanSource.MANUAL`) is theirs to change, and webhooks leave it be.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanKind, PlanPageDTO, PlanServiceProtocol, PlanSource
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import WebhookEventKind
from ludamus.specs.tickets import ACTIVE_SUBSCRIPTION_STATUSES, PLATFORM_FEE_BPS

if TYPE_CHECKING:
    from ludamus.pacts.billing import (
        PlanBillingProtocol,
        SpherePlanData,
        SpherePlanDTO,
        SpherePlanRepositoryProtocol,
    )
    from ludamus.pacts.payment_api import StripeEventLogProtocol, StripeWebhookEvent
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


def holds_yearly_plan(plan: SpherePlanDTO | None, *, now: datetime) -> bool:
    return (
        plan is not None
        and plan.kind is PlanKind.WHITE_GLOVE
        and (plan.paid_until is None or plan.paid_until > now)
    )


class PlanService(PlanServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        plans: SpherePlanRepositoryProtocol,
        event_log: StripeEventLogProtocol,
        billing: PlanBillingProtocol,
    ) -> None:
        self._transaction = transaction
        self._plans = plans
        self._event_log = event_log
        self._billing = billing

    def page(self, *, sphere_id: int) -> PlanPageDTO:
        plan = self._plans.read(sphere_id=sphere_id)
        yearly = holds_yearly_plan(plan, now=datetime.now(tz=UTC))
        kind = PlanKind.WHITE_GLOVE if yearly else PlanKind.STANDARD
        return PlanPageDTO(
            kind=kind,
            ticket_fee_percent=f"{PLATFORM_FEE_BPS[kind] / 100:g}",
            source=plan.source if plan is not None and yearly else None,
            paid_until=plan.paid_until if plan is not None and yearly else None,
            can_subscribe=self._billing.enabled and not yearly,
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
        customer_id = plan.stripe_customer_id if plan is not None else ""
        if not customer_id:
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
            email=email,
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

    def handle_webhook(self, *, payload: bytes, signature: str) -> str:
        event = self._billing.parse_webhook(payload=payload, signature=signature)
        with self._transaction.atomic():
            if not self._event_log.record(event_id=event.id, event_type=event.type):
                return "duplicate"
            return self._apply(event)

    def _apply(self, event: StripeWebhookEvent) -> str:
        customer_id = (
            event.subscription.customer_id
            if event.subscription is not None
            else event.checkout.customer_id if event.checkout is not None else ""
        )
        sphere_id = self._plans.find_sphere_by_customer(customer_id=customer_id)
        if sphere_id is None:
            return "unknown_customer"
        plan = self._plans.read(sphere_id=sphere_id)

        if (
            event.kind is WebhookEventKind.CHECKOUT_COMPLETED
            and event.checkout is not None
            and event.checkout.mode == "subscription"
        ):
            if not event.checkout.paid:
                return "ignored"
            # The invoice carries the period; until it lands, the plan is held
            # with no end date rather than shown as not bought.
            self._plans.save(
                sphere_id=sphere_id,
                data={"kind": PlanKind.WHITE_GLOVE, "source": PlanSource.STRIPE},
            )
            logger.info("Yearly plan bought: sphere=%s", sphere_id)
            return "subscribed"

        facts = event.subscription
        if facts is None or (plan is not None and plan.source is PlanSource.MANUAL):
            return "ignored"
        if event.kind is WebhookEventKind.INVOICE_PAID or (
            facts.status in ACTIVE_SUBSCRIPTION_STATUSES
            and event.kind is not WebhookEventKind.SUBSCRIPTION_DELETED
        ):
            data: SpherePlanData = {
                "kind": PlanKind.WHITE_GLOVE,
                "source": PlanSource.STRIPE,
                "stripe_subscription_id": facts.subscription_id,
            }
            # A payload without a period keeps the date we have.
            if facts.period_end is not None:
                data["paid_until"] = facts.period_end
            self._plans.save(sphere_id=sphere_id, data=data)
            logger.info(
                "Yearly plan paid: sphere=%s until=%s", sphere_id, facts.period_end
            )
            return "renewed"
        self._plans.save(sphere_id=sphere_id, data={"kind": PlanKind.STANDARD})
        logger.info("Yearly plan ended: sphere=%s status=%s", sphere_id, facts.status)
        return "ended"
