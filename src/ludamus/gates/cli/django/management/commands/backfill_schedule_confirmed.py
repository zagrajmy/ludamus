"""Copy schedule confirmations the session column missed, and say how many.

Run on production before AgendaItem.session_confirmed is dropped
(https://github.com/zagrajmy/ludamus/issues/1340): agenda items confirmed by
code that wrote only that column lose the confirmation otherwise. A second
run reports 0.
"""

from __future__ import annotations

from typing import TypedDict, Unpack

from django.core.management.base import BaseCommand

from ludamus.gates.cli.django import wiring


class _Options(TypedDict, total=False):
    verbosity: int


class Command(BaseCommand):
    help = "Copy schedule confirmations from agenda items onto their sessions."

    def handle(self, *_args: *tuple[()], **_options: Unpack[_Options]) -> None:
        copied = wiring.services().session_confirmation.backfill_schedule_confirmed()
        self.stdout.write(f"Confirmed the schedule of {copied} sessions.")
