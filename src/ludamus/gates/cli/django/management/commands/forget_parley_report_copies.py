"""Clear what reports copied of chat messages written over a year ago.

Manual entry point for ``ParleyReportRetentionService.forget_expired_copies``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` this command is the floor instead, run by
external cron. Safe to run repeatedly.
"""

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand


class Command(SweepCommand):
    help = "Clear reported chat messages' copied words a year after writing."
    sweep = "forget_parley_report_copies"
