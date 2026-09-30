"""Business invariants for encounters."""

from datetime import timedelta

ENCOUNTER_DEFAULT_DURATION = timedelta(hours=2)

# NOTE: every invitee address gets mail from our domain. Bounds the distinct
# new addresses a creator invites per day, across all their encounters and
# surviving removal or deletion; re-inviting an address already counted is
# free, so the cap limits whom we mail, not how often.
INVITEES_PER_CREATOR_PER_DAY = 100
INVITEE_WINDOW = timedelta(days=1)
