"""Tell sphere subscribers about the events their spheres just published.

Manual entry point for ``SphereSubscriptionService.announce_published_events``.
The primary path is the in-system DBOS schedule (``inits.dbos_scheduler``);
with ``SCHEDULER_MODE=cron`` run this hourly via external cron instead.
Safe to run repeatedly — each event is announced once.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from ludamus.inits.services import Services

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Notify sphere subscribers about newly published events."

    def handle(self, *_args: object, **_options: object) -> None:
        announced = Services().sphere_subscriptions.announce_published_events(
            now=datetime.now(UTC)
        )
        logger.info("announce_published_events: announced %s event(s)", announced)
        self.stdout.write(
            self.style.SUCCESS(f"Announced {announced} event(s) to subscribers.")
        )
