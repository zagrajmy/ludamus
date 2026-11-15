"""Print the average monthly active accounts over the last six full months.

What UKE may ask for under DSA Art. 24(3). It counts accounts that signed in
or enrolled each month, so it is a floor: visitors who never sign in also
receive the service. docs/agents/moderation.md says how to answer with it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict, Unpack

from django.core.management.base import BaseCommand

from ludamus.gates.cli.django import wiring


class _Options(TypedDict, total=False):
    verbosity: int


class Command(BaseCommand):
    help = "Average monthly active accounts over the last six full months."

    def handle(self, *_args: *tuple[()], **_options: Unpack[_Options]) -> None:
        report = wiring.services().active_recipients.monthly_average(
            now=datetime.now(tz=UTC)
        )
        for start, count in report.months:
            self.stdout.write(f"{start:%Y-%m}\t{count}")
        self.stdout.write(f"average\t{report.average:.1f}")
