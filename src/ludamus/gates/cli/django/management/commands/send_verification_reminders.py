"""Email unverified users a fresh verification link.

Manual entry point for ``EmailVerificationService.send_due_reminders``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` run this daily via external cron instead.
Selects active users holding an address nobody has proven — an unverified
``email`` or a ``pending_email`` — whose last verification mail is older than
the re-nag interval (or was never sent), and mints each a live link through
the same path the resend button uses. Safe to run repeatedly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, Unpack

from django.core.management.base import BaseCommand

from ludamus.gates.cli.django import wiring
from ludamus.gates.cli.django.management.commands._sweep import run_sweep

if TYPE_CHECKING:
    from django.core.management.base import CommandParser


class _Options(TypedDict, total=False):
    dry_run: bool


class Command(BaseCommand):
    help = "Email unverified users a fresh email-verification link."
    dry_run_help = "Print how many users would be reminded and send nothing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help=self.dry_run_help)

    def handle(self, *_args: *tuple[()], **options: Unpack[_Options]) -> None:
        if not options.get("dry_run"):
            run_sweep(self, "send_verification_reminders")
            return
        due = wiring.services().email_verification.count_due(now=datetime.now(UTC))
        self.stdout.write(f"Would send verification reminders to {due} user(s).")
