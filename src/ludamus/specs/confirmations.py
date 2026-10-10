"""Invariants of the confirmation view's grouping."""

from ludamus.pacts.legacy import SessionStatus

# Groups are keyed by (status, is_scheduled). A placed session is its own
# group, and the only one whose rows can be confirmed.
SCHEDULED_GROUP = (SessionStatus.ACCEPTED, True)

# Reading order inside one contact email: what can be confirmed first, then
# what is settled. Unplaced accepted and pending never appear — they are
# counted rather than listed.
STATUS_ORDER = (
    SCHEDULED_GROUP,
    (SessionStatus.ON_HOLD, False),
    (SessionStatus.REJECTED, False),
)

# The other half of that rule: unplaced and in one of these states means a
# count, not a row. Nothing to tick, and pending detail may still change.
COUNTED_UNPLACED = (SessionStatus.PENDING, SessionStatus.ACCEPTED)
