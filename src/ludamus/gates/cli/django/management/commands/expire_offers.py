"""Expire lapsed waiting-list offers and roll freed seats to the next party.

Manual entry point for the sweep in ``WaitlistPromotionService
.expire_lapsed_offers``. The primary path is the in-system DBOS schedule
(``inits.dbos_scheduler``); with ``OFFER_EXPIRY_SCHEDULER=cron`` this command
is the zero-dependency floor instead, run periodically by external cron. Safe
to run repeatedly; already resolved offers are no-ops.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from ludamus.inits.services import Services

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Expire lapsed waiting-list offers and promote the next waiter."

    def handle(self, *_args: object, **_options: object) -> None:
        expired = Services().waitlist_promotion.expire_lapsed_offers(
            now=datetime.now(UTC)
        )
        logger.info("expire_offers: processed %s lapsed offer(s)", expired)
        self.stdout.write(self.style.SUCCESS(f"Processed {expired} lapsed offer(s)."))
