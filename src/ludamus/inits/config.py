"""Settings the composition root acts on, each read and checked in one place.

`edges.settings` only loads the environment; what a value means for the wiring
is decided here, and a value the wiring cannot act on stops the process instead
of quietly selecting a default.
"""

from enum import StrEnum

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SchedulerMode(StrEnum):
    # DBOS runs the timers and sweeps in-process; cron leaves the sweeps to the
    # management commands, run by an external cron.
    DBOS = "dbos"
    CRON = "cron"


def scheduler_mode() -> SchedulerMode:
    raw: str = settings.SCHEDULER_MODE
    try:
        return SchedulerMode(raw)
    except ValueError:
        choices = ", ".join(mode.value for mode in SchedulerMode)
        msg = f"SCHEDULER_MODE must be one of {choices}, not {raw!r}."
        raise ImproperlyConfigured(msg) from None


def credentials_key() -> str:
    key: str = settings.CREDENTIALS_ENCRYPTION_KEY
    return key
