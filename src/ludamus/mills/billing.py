"""The sphere's plan: which one it is on, buying the yearly one, and Stripe's word.

`specs.billing.effective_plan` says which plan a sphere holds. Stripe webhooks
keep a Stripe-billed plan current; a plan a maintainer recorded by hand
(`PlanSource.MANUAL`) is theirs while it lasts, and webhooks leave it be.

Stripe does not deliver events in order, so an event only says which
subscription changed. What it is now is read back from Stripe and written under
the plan's row lock: whichever delivery comes last writes the latest state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanKind, PlanPageDTO, PlanServiceProtocol, PlanSource
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import SubscriptionEvent, WebhookOutcome
from ludamus.specs.billing import effective_plan
from ludamus.specs.tickets import platform_fee_percent

if TYPE_CHECKING:
    from ludamus.pacts.billing import (
        PlanBillingProtocol,
        SpherePlanDTO,
        SpherePlanRepositoryProtocol,
        SubscriptionState,
    )
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
        """Say where to send the buyer: Checkout, or wherever the plan they hold is.

        A second subscription would bill the sphere twice, so one Stripe already
        has (paid a moment ago, its webhook not here yet) sends them to manage it.
        """
        plan = self._plans.read(sphere_id=sphere_id)
        customer_id = plan.stripe_customer_id if plan is not None else ""
        held = effective_plan(plan, now=datetime.now(tz=UTC)) is PlanKind.WHITE_GLOVE
        if held and not customer_id:
            logger.info("Yearly plan already held by hand: sphere=%s", sphere_id)
            return cancel_url
        if customer_id and (
            held or self._billing.has_live_subscription(customer_id=customer_id)
        ):
            return self._billing.billing_portal_url(
                customer_id=customer_id, return_url=cancel_url
            )
        if not customer_id:
            # Created before Checkout, so every webhook that follows finds the
            # sphere by customer.
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
        match self._billing.parse_webhook(payload=payload, signature=signature):
            case SubscriptionEvent(subscription_id=subscription_id):
                return self._sync(subscription_id)
        return WebhookOutcome.NOT_OURS

    def _sync(self, subscription_id: str) -> WebhookOutcome:
        # Read before locking: no row lock waits on Stripe.
        state = self._billing.read_subscription(subscription_id=subscription_id)
        with self._transaction.atomic():
            plan = self._plans.lock_by_customer(customer_id=state.customer_id)
            if plan is None:
                return WebhookOutcome.NOT_OURS
            return self._record(plan=plan, subscription_id=subscription_id, state=state)

    def _record(
        self, *, plan: SpherePlanDTO, subscription_id: str, state: SubscriptionState
    ) -> WebhookOutcome:
        if (
            plan.source is PlanSource.MANUAL
            and effective_plan(plan, now=datetime.now(tz=UTC)) is PlanKind.WHITE_GLOVE
        ):
            # A maintainer's deal is theirs while it lasts.
            return WebhookOutcome.STALE
        on_record = plan.stripe_subscription_id == subscription_id
        if state.live:
            self._plans.save(
                sphere_id=plan.sphere_id,
                data={
                    "kind": PlanKind.WHITE_GLOVE,
                    "source": PlanSource.STRIPE,
                    "paid_until": state.paid_until,
                    "stripe_subscription_id": subscription_id,
                },
            )
            logger.info(
                "Yearly plan paid: sphere=%s until=%s", plan.sphere_id, state.paid_until
            )
            return WebhookOutcome.RENEWED if on_record else WebhookOutcome.SUBSCRIBED
        if on_record and plan.kind is PlanKind.WHITE_GLOVE:
            self._plans.save(sphere_id=plan.sphere_id, data={"kind": PlanKind.STANDARD})
            logger.info("Yearly plan ended: sphere=%s", plan.sphere_id)
            return WebhookOutcome.ENDED
        # An ended subscription other than the one on record: an old one.
        return WebhookOutcome.STALE
