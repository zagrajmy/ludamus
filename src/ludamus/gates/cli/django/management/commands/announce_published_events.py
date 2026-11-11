"""Tell sphere subscribers about the events their spheres just published.

Manual entry point for ``SphereSubscriptionService.announce_published_events``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` run this hourly via external cron instead.
Safe to run repeatedly — each event is announced once.
"""

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand


class Command(SweepCommand):
    help = "Notify sphere subscribers about newly published events."
    sweep = "announce_published_events"
