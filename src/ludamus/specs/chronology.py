"""Business invariants for chronology."""


def resolve_facilitator_session_edit(
    *, event_override: bool | None, sphere_default: bool
) -> bool:
    if event_override is None:
        return sphere_default
    return event_override
