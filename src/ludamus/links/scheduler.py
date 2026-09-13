"""Cron-mode scheduler floors: record intent, let a sweep do the work.

Durable-enough without a broker: the work's due-state lives in the database
(`SessionParticipation.offer_expires_at`; `Announcement.notified_at IS NULL`),
so cron-driven management commands (`expire_offers`, `fanout_announcements`)
find and process it — surviving restarts. `schedule_*` only records intent.
Each trigger sits behind its protocol, so DBOS is a drop-in swap.
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


class CronSweepAnnouncementFanout:
    @staticmethod
    def schedule_fanout(*, announcement_id: int) -> None:
        logger.info("Announcement fanout registered: announcement=%s", announcement_id)
