"""Delete staff case mail older than the privacy policy keeps it.

Manual entry point for ``CaseMailRetentionService.forget_expired``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` this command is the floor instead, run by
external cron. Safe to run repeatedly.
"""

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand


class Command(SweepCommand):
    help = "Delete staff case mail three years after it came or went."
    sweep = "forget_case_mail"
