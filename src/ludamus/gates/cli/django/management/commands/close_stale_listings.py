"""Close board listings that have been open for longer than the listing lifetime.

Manual entry point for ``ListingService.close_stale``. The primary path is the
in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` this command is the floor instead, run by external
cron. Safe to run repeatedly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand
from ludamus.inits.builders import build_listings

if TYPE_CHECKING:
    from datetime import datetime


class Command(SweepCommand):
    help = "Close board listings open past their lifetime."

    @staticmethod
    def sweep(*, now: datetime) -> int:
        return build_listings().close_stale(now)

    @staticmethod
    def report(handled: int) -> str:
        return f"Closed {handled} stale listing(s)."
