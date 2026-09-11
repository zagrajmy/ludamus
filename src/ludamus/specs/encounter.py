"""Business invariants for encounters."""

from datetime import timedelta

ENCOUNTER_DEFAULT_DURATION = timedelta(hours=2)
# How long one IP waits between RSVPs. Short enough that a person who mis-clicks
# is not locked out, long enough to stop a script.
ENCOUNTER_RSVP_THROTTLE_SECONDS = 60
