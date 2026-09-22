"""Tell sphere subscribers about the events their spheres just published.

Manual entry point for ``SphereSubscriptionService.announce_published_events``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` run this hourly via external cron instead.
Safe to run repeatedly — each event is announced once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand
from ludamus.inits.services import Services

if TYPE_CHECKING:
    from datetime import datetime


class Command(SweepCommand):
    help = "Notify sphere subscribers about newly published events."

    @staticmethod
    def sweep(*, now: datetime) -> int:
        return Services().sphere_subscriptions.announce_published_events(now=now)

    @staticmethod
    def report(handled: int) -> str:
        return f"Announced {handled} event(s) to subscribers."
