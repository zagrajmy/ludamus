"""The shape every periodic sweep command shares.

Each of these commands is the manual entry point for one sweep the DBOS
schedule normally runs (``inits.dbos_scheduler``); with ``SCHEDULER_MODE=cron``
they are the zero-dependency floor instead. All of them do the same three
things — run the sweep at now, log what it touched, print that same sentence
to whoever ran it — so a command says only what differs: the call and the
wording.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class SweepCommand(BaseCommand):
    """One sweep, run now, reported once."""

    @staticmethod
    @abstractmethod
    def sweep(*, now: datetime) -> int:
        """Run the sweep.

        Returns:
            How much it handled, which is what gets reported.
        """

    @staticmethod
    @abstractmethod
    def report(handled: int) -> str:
        """Phrase the result for whoever ran the command.

        Returns:
            One sentence, already counting in this sweep's own units.
        """

    def handle(self, *_args: object, **_options: object) -> None:
        # The log and the console say the same sentence: an operator reading
        # either one should not have to translate between two phrasings.
        summary = self.report(self.sweep(now=datetime.now(UTC)))
        logger.info("%s", summary)
        self.stdout.write(self.style.SUCCESS(summary))
