"""Open the chats of parties that were made before party chats were.

A party's chat follows each change to who is in it; a party nobody has
joined or left since has none yet. Run once after deploying party chats.
Running it again changes nothing.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from ludamus.gates.cli.django import wiring


class Command(BaseCommand):
    help = "Open a chat for every party that has someone to talk to."

    def handle(self, *_args: object, **_options: object) -> None:
        synced = wiring.services().parley_party_chats.open_existing_chats()
        self.stdout.write(f"Synced the chats of {synced} parties.")
