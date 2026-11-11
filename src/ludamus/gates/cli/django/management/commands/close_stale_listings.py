"""Close board listings that have been open for longer than the listing lifetime.

Manual entry point for ``ListingService.close_stale``. The primary path is the
in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` this command is the floor instead, run by external
cron. Safe to run repeatedly.
"""

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand


class Command(SweepCommand):
    help = "Close board listings open past their lifetime."
    sweep = "close_stale_listings"
