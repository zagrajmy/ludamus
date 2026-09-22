"""Push every sync-enabled event's agenda into its Konwencik tab.

Manual entry point for ``KonwencikExportService.run_sweep``. The primary path
is the in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` run this on a cron instead. Each run rewrites the whole
tab from the current schedule, so running it repeatedly is free and one
integration's failure does not stop the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand
from ludamus.inits.services import Services

if TYPE_CHECKING:
    from datetime import datetime


class Command(SweepCommand):
    help = "Export the agenda of every sync-enabled event to Konwencik."

    @staticmethod
    def sweep(*, now: datetime) -> int:
        return Services().konwencik_export.run_sweep(now=now)

    @staticmethod
    def report(handled: int) -> str:
        return f"Exported {handled} integration(s) to Konwencik."
