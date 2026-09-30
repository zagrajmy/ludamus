"""Business invariants for encounters."""

from datetime import timedelta

ENCOUNTER_DEFAULT_DURATION = timedelta(hours=2)

# NOTE: every invitee address gets mail from our domain. Counted over all of a
# creator's encounters, removed invitees included, so swapping the list or
# spreading it over encounters cannot turn the form into a bulk mailer.
INVITEES_PER_CREATOR_PER_DAY = 100
INVITEE_WINDOW = timedelta(days=1)
