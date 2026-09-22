"""Expire lapsed waiting-list offers and roll freed seats to the next party.

Manual entry point for the sweep in ``WaitlistPromotionService
.expire_lapsed_offers``. The primary path is the in-system DBOS schedule
(``inits.dbos_scheduler``); with ``SCHEDULER_MODE=cron`` this command
is the zero-dependency floor instead, run periodically by external cron. Safe
to run repeatedly; already resolved offers are no-ops.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand
from ludamus.inits.services import Services

if TYPE_CHECKING:
    from datetime import datetime


class Command(SweepCommand):
    help = "Expire lapsed waiting-list offers and promote the next waiter."

    @staticmethod
    def sweep(*, now: datetime) -> int:
        return Services().waitlist_promotion.expire_lapsed_offers(now=now)

    @staticmethod
    def report(handled: int) -> str:
        return f"Processed {handled} lapsed offer(s)."
