"""Business invariants for sessions."""


def resolve_event_toggle(*, event_override: bool | None, sphere_default: bool) -> bool:
    # A sphere sets the default for its events; an event's own setting, when
    # it has one, wins. Facilitator self-edit and required spaces both work so.
    if event_override is None:
        return sphere_default
    return event_override
