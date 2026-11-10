"""The shape every periodic sweep command shares.

Each of these commands is the manual entry point for one sweep the DBOS
schedule normally runs; with ``SCHEDULER_MODE=cron`` they are the
zero-dependency floor instead. The sweep itself, and the sentence that reports
it, come from the one table both runners read (``inits.sweeps``), so a command
says only which sweep it runs and how to describe it in ``--help``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import ClassVar

from django.core.management.base import BaseCommand

from ludamus.gates.cli.django import wiring

logger = logging.getLogger(__name__)


def run_sweep(command: BaseCommand, sweep_command: str) -> None:
    # The log and the console say the same sentence the DBOS schedule logs:
    # an operator reading any of them should not have to translate.
    sweep = wiring.sweep(sweep_command)
    summary = sweep.summary(sweep.run(datetime.now(UTC)))
    logger.info("%s", summary)
    command.stdout.write(command.style.SUCCESS(summary))


class SweepCommand(BaseCommand):
    """One sweep, run now, reported once."""

    sweep: ClassVar[str]

    def handle(self, *_args: object, **_options: object) -> None:
        run_sweep(self, self.sweep)
