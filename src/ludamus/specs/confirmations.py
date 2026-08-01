"""Invariants of the confirmation view's grouping."""

from ludamus.pacts.legacy import SessionStatus

# A placed session is its own group: "scheduled" is not a SessionStatus value
# (the status behind it is always ACCEPTED), but it is the distinction the
# organizer works by, and the only group whose rows can be confirmed.
SCHEDULED_STATUS = "scheduled"

# Reading order inside one contact email: what can be confirmed first, then
# what is settled. Accepted and pending never appear — an unplaced session in
# either state is counted rather than listed, and a placed one is "scheduled".
STATUS_ORDER = (
    SCHEDULED_STATUS,
    str(SessionStatus.ON_HOLD),
    str(SessionStatus.REJECTED),
)

# The other half of that rule: unplaced and in one of these states means a
# count, not a row. Nothing to tick, and pending detail may still change.
COUNTED_UNPLACED = (SessionStatus.PENDING, SessionStatus.ACCEPTED)
