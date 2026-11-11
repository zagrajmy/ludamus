"""Fan out published, not-yet-notified announcements to their subscribers.

Manual entry point for ``AnnouncementFanoutService.fanout_due``. The primary
path is the in-system DBOS workflow (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` run this every few minutes via external cron instead.
Safe to run repeatedly — the ``notified_at`` claim delivers each announcement
at most once.
"""

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand


class Command(SweepCommand):
    help = "Deliver published announcements to their subscribers' bells."
    sweep = "fanout_announcements"
