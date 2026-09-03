"""Business invariants for chronology."""

# A convention day ends when people go to sleep, not at midnight: a session
# that runs from Friday 22:00 into the small hours is Friday's programme, and
# a reader at 02:00 is still living Friday. Days on every schedule layout turn
# over at this hour.
PROGRAMME_DAY_STARTS_AT_HOUR = 6


def resolve_facilitator_session_edit(
    *, event_override: bool | None, sphere_default: bool
) -> bool:
    if event_override is None:
        return sphere_default
    return event_override
