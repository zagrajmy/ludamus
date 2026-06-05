"""Expire lapsed waiting-list offers and roll freed seats to the next party.

The zero-dependency floor for offer-and-claim (#327) when
``OFFER_EXPIRY_SCHEDULER`` is left at its ``cron`` default: the offer deadline
lives on ``SessionParticipation.offer_expires_at``, so running this command
periodically (e.g. every few minutes via cron) finds every offer past its
deadline and expires it via ``WaitlistPromotionService.expire_offer`` — which
drops the lapsed party and re-runs promotion. Safe to run repeatedly; already
resolved offers are no-ops. (The ``dbos`` scheduler does this in-process.)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from ludamus.adapters.db.django.models import SessionParticipation
from ludamus.inits.services import Services
from ludamus.pacts.legacy import SessionParticipationStatus

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Expire lapsed waiting-list offers and promote the next waiter."

    def handle(self, *_args: object, **_options: object) -> None:
        service = Services().waitlist_promotion
        now = datetime.now(UTC)
        # One representative participation per lapsed party (the service expands
        # to the whole party from the shared claim token).
        lapsed = (
            SessionParticipation.objects.filter(
                status=SessionParticipationStatus.OFFERED, offer_expires_at__lt=now
            )
            .values_list("claim_token", "id")
            .order_by("claim_token", "id")
        )
        seen: set[str] = set()
        expired = 0
        for claim_token, participation_id in lapsed:
            if claim_token in seen:
                continue
            seen.add(claim_token)
            service.expire_offer(participation_id=participation_id)
            expired += 1
        logger.info("expire_offers: processed %s lapsed offer(s)", expired)
        self.stdout.write(self.style.SUCCESS(f"Processed {expired} lapsed offer(s)."))
