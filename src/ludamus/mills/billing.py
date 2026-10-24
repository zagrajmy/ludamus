"""The sphere's plan: what its deal gives it, and Stripe's word on the price.

`specs.billing.current_terms` says what a sphere's deal gives it. A maintainer
records the deal; a deal billed through a Stripe subscription has its
`paid_until` kept current by Stripe's webhooks, and one paid by bank transfer
(`PlanSource.MANUAL`) is theirs while it lasts, and webhooks leave it be.

Stripe does not deliver events in order, so an event only says which
subscription changed. What it is now is read back from Stripe while the plan's
row is locked, so concurrent deliveries write in the order they read and the
last one writes the latest state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanPageDTO, PlanServiceProtocol, PlanSource
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import SubscriptionEvent, WebhookOutcome
from ludamus.specs.billing import current_terms
from ludamus.specs.tickets import platform_fee_percent

if TYPE_CHECKING:
    from ludamus.pacts.billing import (
        PlanBillingProtocol,
        SpherePlanData,
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
        terms = current_terms(plan, now=datetime.now(tz=UTC))
        return PlanPageDTO(
            terms=terms,
            ticket_fee_percent=platform_fee_percent(terms.ticket_fee_bps),
            has_billing_history=self._billing.enabled
            and plan is not None
            and bool(plan.stripe_customer_id),
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
            case SubscriptionEvent() as event:
                return self._sync(event)
        return WebhookOutcome.NOT_OURS

    def _sync(self, event: SubscriptionEvent) -> WebhookOutcome:
        with self._transaction.atomic():
            plan = self._plans.lock_by_customer(customer_id=event.customer_id)
            if plan is None:
                return WebhookOutcome.NOT_OURS
            if plan.source is PlanSource.MANUAL:
                # A deal paid by transfer: its dates are the maintainer's.
                return WebhookOutcome.STALE
            # SAFETY: read under the lock, so a delivery that read an older
            # state cannot commit after one that read a newer state.
            state = self._billing.read_subscription(
                subscription_id=event.subscription_id
            )
            return self._record(
                plan=plan, subscription_id=event.subscription_id, state=state
            )

    def _record(
        self, *, plan: SpherePlanDTO, subscription_id: str, state: SubscriptionState
    ) -> WebhookOutcome:
        on_record = plan.stripe_subscription_id == subscription_id
        if state.live:
            data: SpherePlanData = {"stripe_subscription_id": subscription_id}
            # Without a period Stripe says nothing of the end: an unset date
            # would read as an open-ended deal, so the one on record stays.
            if state.paid_until is not None:
                data["paid_until"] = state.paid_until
            self._plans.save(sphere_id=plan.sphere_id, data=data)
            logger.info(
                "Deal paid: sphere=%s until=%s", plan.sphere_id, state.paid_until
            )
            return WebhookOutcome.RENEWED if on_record else WebhookOutcome.SUBSCRIBED
        if on_record:
            # The deal lapses now; its terms stay on record for a renewal.
            now = datetime.now(tz=UTC)
            ended = now if state.paid_until is None else min(state.paid_until, now)
            self._plans.save(sphere_id=plan.sphere_id, data={"paid_until": ended})
            logger.info("Deal ended: sphere=%s", plan.sphere_id)
            return WebhookOutcome.ENDED
        # An ended subscription other than the one on record: an old one.
        return WebhookOutcome.STALE
