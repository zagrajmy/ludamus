"""Delete encounter invitees no list shows once the daily cap stops counting them.

Manual entry point for ``EncounterService.purge_stale_invitees``. The primary
path is the in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` this command is the floor instead, run by external
cron. Safe to run repeatedly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand
from ludamus.inits.builders import build_encounters, build_sites

if TYPE_CHECKING:
    from datetime import datetime


class Command(SweepCommand):
    help = "Delete removed or orphaned encounter invitees past the daily window."

    @staticmethod
    def sweep(*, now: datetime) -> int:
        return build_encounters(build_sites()).purge_stale_invitees(now=now)

    @staticmethod
    def report(handled: int) -> str:
        return f"Purged {handled} stale encounter invitee(s)."
