"""Open the chats of encounters that were made before encounter chats were.

An encounter's chat follows each signup and cancellation; an encounter
nobody has signed up for or left since has none yet. Run once after
deploying encounter chats. Running it again changes nothing.
"""

from __future__ import annotations

from typing import TypedDict, Unpack

from django.core.management.base import BaseCommand

from ludamus.gates.cli.django import wiring


class _Options(TypedDict, total=False):
    verbosity: int


class Command(BaseCommand):
    help = "Open a chat for every encounter that has someone to talk to."

    def handle(self, *_args: *tuple[()], **_options: Unpack[_Options]) -> None:
        synced = wiring.services().parley_encounter_chats.open_existing_chats()
        self.stdout.write(f"Synced the chats of {synced} encounters.")
