"""Email organizers a reminder to print their event materials.

Manual entry point for ``PrintablesReminderService.send_due_reminders``. The
primary path is the in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` run this daily via external cron instead.
Finds every event starting within the reminder lead time whose organizers
have not opened the print page and have not already been reminded, then emails
each sphere manager a link to the event's print page. Safe to run
repeatedly — each event is reminded once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand
from ludamus.inits.services import Services

if TYPE_CHECKING:
    from datetime import datetime


class Command(SweepCommand):
    help = "Email organizers to print their materials before the event starts."

    @staticmethod
    def sweep(*, now: datetime) -> int:
        return Services().printables_reminder.send_due_reminders(now=now)

    @staticmethod
    def report(handled: int) -> str:
        return f"Sent printables reminders for {handled} event(s)."
