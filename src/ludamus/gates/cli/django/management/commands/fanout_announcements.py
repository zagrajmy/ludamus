"""Fan out published, not-yet-notified announcements to their subscribers.

Manual entry point for ``AnnouncementFanoutService.fanout_due``. The primary
path is the in-system DBOS workflow (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` run this every few minutes via external cron instead.
Safe to run repeatedly — the ``notified_at`` claim delivers each announcement
at most once.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from ludamus.inits.builders import build_announcement_fanout

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Deliver published announcements to their subscribers' bells."

    def handle(self, *_args: str, **_options: int | str | bool | None) -> None:
        notified = build_announcement_fanout().fanout_due()
        logger.info("fanout_announcements: notified %s subscriber(s)", notified)
        self.stdout.write(
            self.style.SUCCESS(f"Notified {notified} subscriber(s) of announcements.")
        )
