"""What a visitor may start from a feed: an event, an encounter, both or none.

The feed's create control renders whatever this returns: nothing for no
option, a direct link for one, and a dialog that asks which for two.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from ludamus.gates.web.django.access import panel_access
from ludamus.pacts.sphere import Capability

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest


class CreateOption(StrEnum):
    EVENT = "event"
    ENCOUNTER = "encounter"


def create_options(request: RootRequest) -> tuple[CreateOption, ...]:
    """List what the visitor may create in the current sphere, event first.

    An event needs the panel's write capability, the same check the panel's
    event form makes before it saves. An encounter follows the sphere's
    encounters policy.

    Returns:
        The options in the order the dialog shows them.
    """
    user_id = request.context.current_user_id
    may_create_event = panel_access(request).allows(Capability.PANEL_WRITE)
    may_create_encounter = (
        user_id is not None
        and request.services.encounters.can_create(
            sphere_id=request.context.current_sphere_id, user_id=user_id
        )
    )
    return tuple(
        option
        for option, allowed in (
            (CreateOption.EVENT, may_create_event),
            (CreateOption.ENCOUNTER, may_create_encounter),
        )
        if allowed
    )
