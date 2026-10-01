"""Business invariants for encounters."""

from datetime import timedelta

ENCOUNTER_DEFAULT_DURATION = timedelta(hours=2)

# NOTE: every invitee address gets mail from our domain. Bounds the distinct
# new addresses a creator invites per day, across all their encounters and
# surviving removal or deletion; re-inviting an address already counted is
# free, so the cap limits whom we mail, not how often.
INVITEES_PER_CREATOR_PER_DAY = 100
INVITEE_WINDOW = timedelta(days=1)
# NOTE: a throwaway account costs nothing, so the full allowance waits until
# an account has been around a week.
NEW_CREATOR_AGE = timedelta(days=7)
INVITEES_PER_NEW_CREATOR_PER_DAY = 10
# NOTE: the address cap leaves re-mailing free, so this bounds the messages
# themselves: invites and change notices to invitees over the last day. Both
# stay above MAX_INVITEES, so one edit of a full list always fits.
CALENDAR_MAILS_PER_CREATOR_PER_DAY = 500
CALENDAR_MAILS_PER_NEW_CREATOR_PER_DAY = 100
# NOTE: invitees of an encounter long over serve no list a guest will open.
INVITEE_RETENTION_AFTER_END = timedelta(days=30)
