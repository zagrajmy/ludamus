"""Push every sync-enabled event's agenda into its Konwencik tab.

Manual entry point for ``KonwencikExportService.run_sweep``. The primary path
is the in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` run this on a cron instead. Each run rewrites the whole
tab from the current schedule, so running it repeatedly is free and one
integration's failure does not stop the rest.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from ludamus.inits.services import Services

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Export the agenda of every sync-enabled event to Konwencik."

    def handle(self, *_args: object, **_options: object) -> None:
        exported = Services().konwencik_export.run_sweep(now=datetime.now(UTC))
        logger.info("export_konwencik: exported %s integration(s)", exported)
        self.stdout.write(
            self.style.SUCCESS(f"Exported {exported} integration(s) to Konwencik.")
        )
