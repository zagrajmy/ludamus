"""Email unverified users a fresh verification link.

Manual entry point for ``EmailVerificationReminderService.send_due_reminders``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` run this daily via external cron instead.
Selects active users with a non-blank, unverified address whose last
verification mail is older than the re-nag interval (or was never sent) and
routes each through ``request_verification``, so the sweep shares the resend
throttle and mints live links. Safe to run repeatedly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand

from ludamus.inits.services import Services

if TYPE_CHECKING:
    from django.core.management.base import CommandParser

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Email unverified users a fresh email-verification link."
    dry_run_help = "Print how many users would be reminded and send nothing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help=self.dry_run_help)

    def handle(self, *_args: object, **options: object) -> None:
        service = Services().email_verification_reminder
        now = datetime.now(UTC)
        if options["dry_run"]:
            due = service.count_due(now=now)
            self.stdout.write(f"Would send verification reminders to {due} user(s).")
            return
        sent = service.send_due_reminders(now=now)
        logger.info("send_verification_reminders: reminded %s user(s)", sent)
        self.stdout.write(
            self.style.SUCCESS(f"Sent verification reminders to {sent} user(s).")
        )
