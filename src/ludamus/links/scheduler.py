"""Offer-expiry scheduler.

Durable-enough floor: the offer deadline is stored on
`SessionParticipation.offer_expires_at`, so a cron-driven `expire_offers`
management command finds and expires lapsed offers — surviving restarts without
a broker. `schedule_expiry` only records intent. The trigger sits behind
`OfferExpirySchedulerProtocol`, so swapping in DBOS later is a drop-in change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class CronSweepOfferScheduler:
    @staticmethod
    def schedule_expiry(*, participation_id: int, run_at: datetime) -> None:
        logger.info(
            "Offer expiry registered: participation=%s run_at=%s",
            participation_id,
            run_at.isoformat(),
        )
