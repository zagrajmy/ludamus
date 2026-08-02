"""Email organizers a reminder to print their event materials.

Manual entry point for ``PrintablesReminderService.send_due_reminders``. The
primary path is the in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` run this daily via external cron instead.
Finds every event starting within the reminder lead time whose organizers
have not opened a print page and have not already been reminded, then emails
each sphere manager a link to the panel's print-materials hub. Safe to run
repeatedly — each event is reminded once.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from ludamus.inits.services import Services

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Email organizers to print their materials before the event starts."

    def handle(self, *_args: object, **_options: object) -> None:
        reminded = Services().printables_reminder.send_due_reminders(
            now=datetime.now(UTC)
        )
        logger.info("send_printables_reminders: reminded %s event(s)", reminded)
        self.stdout.write(
            self.style.SUCCESS(f"Sent printables reminders for {reminded} event(s).")
        )
