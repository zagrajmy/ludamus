from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.mcp.registry import ToolError

if TYPE_CHECKING:
    from ludamus.pacts.legacy import EventDTO
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol


def actor_sphere(actor: ActorContext) -> int:
    if actor.sphere_id is None:
        raise ToolError("Organizer token has no sphere")
    return actor.sphere_id


def token_event(*, services: ServicesProtocol, actor: ActorContext) -> EventDTO:
    if actor.event_id is None:
        raise ToolError("Organizer token has no event")
    return services.events.require_in_sphere(
        sphere_id=actor_sphere(actor), event_id=actor.event_id
    )
