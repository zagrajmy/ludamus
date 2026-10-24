from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, create_model

from ludamus.gates.mcp.registry import (
    ToolError,
    ToolProtocol,
    json_schema,
    validate_arguments,
)
from ludamus.pacts.mcp import ToolScope

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import JsonDict, OrganizerToolProtocol
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


def require_event(
    *, services: ServicesProtocol, actor: ActorContext, event_id: int
) -> EventDTO:
    return services.events.require_in_sphere(
        sphere_id=actor_sphere(actor), event_id=event_id
    )


class _SphereTarget(BaseModel):
    sphere_id: int = Field(description="Sphere primary key (see list_spheres)")


class _EventTarget(_SphereTarget):
    event_id: int = Field(
        description="Primary key of the event this call acts on (see get_event)"
    )


class MaintainerTool(ToolProtocol):
    """An organizer tool opened to maintainers, in every sphere.

    An organizer token carries one sphere and one event; a maintainer token
    carries neither. This takes them as arguments and runs the organizer
    tool's own code with them, so each operation has one implementation
    whichever endpoint calls it. Which sphere and event the call may touch is
    still checked where the organizer tool checks it — `token_event` and
    `require_event` refuse an event outside the sphere.
    """

    scope = ToolScope.MAINTAINER

    def __init__(self, tool: OrganizerToolProtocol) -> None:
        self._tool = tool
        self.name = tool.name
        self.description = tool.maintainer_description or tool.description
        self._target = _EventTarget if tool.needs_event else _SphereTarget
        if clash := self._target.model_fields.keys() & tool.input_model.model_fields:
            message = f"{tool.name} already takes {', '.join(sorted(clash))}"
            raise ValueError(message)
        # Built once so tools/list and validation see a single model: errors
        # in the sphere/event and in the tool's own fields come back together.
        self._input_model: type[BaseModel] = create_model(
            f"Maintainer{type(tool).__name__}Input",
            __base__=(tool.input_model, self._target),
        )

    def input_schema(self) -> JsonDict:
        return json_schema(self._input_model)

    def audit_arguments(self, arguments: JsonDict) -> JsonDict:
        # The actor on the audit line is the maintainer's, with no sphere or
        # event, and batch tools log only counts and row ids: the target has
        # to ride in the arguments or the line never says where it wrote.
        target: JsonDict = {
            name: arguments[name]
            for name in ("sphere_id", "event_id")
            if name in arguments
        }
        return {**target, **self._tool.audit_arguments(arguments)}

    def run(
        self, *, services: ServicesProtocol, actor: ActorContext, arguments: JsonDict
    ) -> str:
        validate_arguments(self._input_model, arguments)
        # The tool's own keys are ignored here, and both target fields are
        # required, so `model_fields_set` names exactly the keys to strip.
        target = self._target.model_validate(arguments)
        return self._tool.run(
            services=services,
            actor=replace(
                actor,
                sphere_id=target.sphere_id,
                event_id=target.event_id if isinstance(target, _EventTarget) else None,
            ),
            arguments={
                name: value
                for name, value in arguments.items()
                if name not in target.model_fields_set
            },
        )
