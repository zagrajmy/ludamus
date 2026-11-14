"""Delete encounter invitees no list shows once the daily cap stops counting them.

Manual entry point for ``EncounterService.purge_stale_invitees``. The primary
path is the in-system DBOS schedule (``inits.dbos_scheduler``); with
``SCHEDULER_MODE=cron`` this command is the floor instead, run by external
cron. Safe to run repeatedly.
"""

from ludamus.gates.cli.django.management.commands._sweep import SweepCommand


class Command(SweepCommand):
    help = "Delete removed or orphaned encounter invitees past the daily window."
    sweep = "purge_encounter_invitees"
