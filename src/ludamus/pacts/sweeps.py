"""A periodic sweep, as both of its runners see it.

The DBOS schedule and the management command run the same sweeps; each row
says once what runs, when, and how its result reads, so the two runners cannot
drift apart.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime


@dataclass(frozen=True)
class Sweep:
    """One sweep: run at an instant, reported in one sentence.

    `command` names the management command that runs it by hand; `workflow`
    names the DBOS workflow and schedule, which the system database stores, so
    it stays as deployed. `report` holds `{handled}` where the count goes.
    """

    command: str
    workflow: str
    cron: str
    run: Callable[[datetime], int]
    report: str

    def summary(self, handled: int) -> str:
        return self.report.format(handled=handled)
