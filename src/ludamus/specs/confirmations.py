"""Invariants of the confirmation view's grouping."""

from ludamus.pacts.legacy import SessionStatus

# A placed session is its own group: "scheduled" is not a SessionStatus value
# (the status behind it is always ACCEPTED), but it is the distinction the
# organizer works by, and the only group whose rows can be confirmed.
SCHEDULED_STATUS = "scheduled"

# Reading order inside one contact email: what can be confirmed first, then
# what is still undecided, then what is settled and negative.
STATUS_ORDER = (
    SCHEDULED_STATUS,
    str(SessionStatus.ON_HOLD),
    str(SessionStatus.REJECTED),
    str(SessionStatus.ACCEPTED),
    str(SessionStatus.PENDING),
)
