"""Maintainer MCP tool set.

A hand-curated surface, not an auto-export of every service: each tool is a
deliberate maintainer operation. All calls go through `ServicesProtocol`, so
business invariants hold for MCP callers exactly as they do for views.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, TypeAdapter

from ludamus.gates.mcp.registry import Tool, ToolError, ToolRegistry
from ludamus.pacts.legacy import EventDTO, EventListItemDTO
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    SphereListItemDTO,
)

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolCall, ToolProtocol
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol

_SPHERE_LIST = TypeAdapter(list[SphereListItemDTO])
_EVENT_LIST = TypeAdapter(list[EventListItemDTO])
_ANNOUNCEMENT_LIST = TypeAdapter(list[AnnouncementDTO])


class _EmptyInput(BaseModel):
    pass


def _render_sphere(services: ServicesProtocol, sphere_id: int) -> str:
    return services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


def _render_events(
    *, services: ServicesProtocol, sphere_id: int, include_unpublished: bool
) -> str:
    events = services.events.list_for_sphere(
        sphere_id, include_unpublished=include_unpublished
    )
    return _EVENT_LIST.dump_json(events, indent=2).decode()


def _render_announcements(services: ServicesProtocol, sphere_id: int) -> str:
    items = services.announcements.list_for_sphere(sphere_id)
    return _ANNOUNCEMENT_LIST.dump_json(items, indent=2).decode()


def _create_announcement(
    *, services: ServicesProtocol, sphere_id: int, body: _AnnouncementBody
) -> str:
    created = services.announcements.create(sphere_id, _announcement_data(body))
    return created.model_dump_json(indent=2)


def _update_announcement(
    *,
    services: ServicesProtocol,
    sphere_id: int,
    announcement_id: int,
    body: _AnnouncementBody,
) -> str:
    updated = services.announcements.update(
        sphere_id, announcement_id, _announcement_data(body)
    )
    return updated.model_dump_json(indent=2)


def _delete_announcement(
    *, services: ServicesProtocol, sphere_id: int, announcement_id: int
) -> str:
    services.announcements.delete(sphere_id, announcement_id)
    result: dict[str, int] = {"deleted": announcement_id}
    return json.dumps(result)


class _SphereInput(BaseModel):
    sphere_id: int = Field(description="Sphere primary key (see list_spheres)")


class ListSpheresTool(Tool[_EmptyInput]):
    name = "list_spheres"
    description = (
        "List every sphere (community site) with its id, name and domain. "
        "Call this first to discover sphere ids used by the other tools."
    )
    scope = ToolScope.MAINTAINER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        spheres = call.services.sites.list_spheres()
        return _SPHERE_LIST.dump_json(spheres, indent=2).decode()


class GetSphereTool(Tool[_SphereInput]):
    name = "get_sphere"
    description = "Read one sphere's settings and configuration."
    scope = ToolScope.MAINTAINER
    input_model = _SphereInput

    @staticmethod
    def handle(call: ToolCall[_SphereInput]) -> str:
        return _render_sphere(call.services, call.data.sphere_id)


class _ListEventsBody(BaseModel):
    include_unpublished: bool = Field(
        default=True, description="Include events that are not published yet"
    )


class _ListEventsInput(_SphereInput, _ListEventsBody):
    pass


class ListEventsTool(Tool[_ListEventsInput]):
    name = "list_events"
    description = "List a sphere's events with their status and session counts."
    scope = ToolScope.MAINTAINER
    input_model = _ListEventsInput

    @staticmethod
    def handle(call: ToolCall[_ListEventsInput]) -> str:
        return _render_events(
            services=call.services,
            sphere_id=call.data.sphere_id,
            include_unpublished=call.data.include_unpublished,
        )


class _GetEventInput(_SphereInput):
    slug: str = Field(description="Event slug (see list_events)")


class GetEventTool(Tool[_GetEventInput]):
    name = "get_event"
    description = "Read one event's full configuration by slug."
    scope = ToolScope.MAINTAINER
    input_model = _GetEventInput

    @staticmethod
    def handle(call: ToolCall[_GetEventInput]) -> str:
        event: EventDTO = call.services.events.read_by_slug(
            call.data.sphere_id, call.data.slug
        )
        return event.model_dump_json(indent=2)


class ListAnnouncementsTool(Tool[_SphereInput]):
    name = "list_announcements"
    description = "List a sphere's announcements, published and drafts."
    scope = ToolScope.MAINTAINER
    input_model = _SphereInput

    @staticmethod
    def handle(call: ToolCall[_SphereInput]) -> str:
        return _render_announcements(call.services, call.data.sphere_id)


class _AnnouncementBody(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(max_length=50000)
    is_published: bool = Field(
        default=False, description="Publish immediately; false saves a draft"
    )


class _AnnouncementContentInput(_SphereInput, _AnnouncementBody):
    pass


class CreateAnnouncementTool(Tool[_AnnouncementContentInput]):
    name = "create_announcement"
    description = "Create a sphere announcement (draft by default)."
    scope = ToolScope.MAINTAINER
    input_model = _AnnouncementContentInput

    @staticmethod
    def handle(call: ToolCall[_AnnouncementContentInput]) -> str:
        return _create_announcement(
            services=call.services, sphere_id=call.data.sphere_id, body=call.data
        )


class _UpdateAnnouncementInput(_AnnouncementContentInput):
    announcement_id: int


class UpdateAnnouncementTool(Tool[_UpdateAnnouncementInput]):
    name = "update_announcement"
    description = "Update an announcement's title, content or published flag."
    scope = ToolScope.MAINTAINER
    input_model = _UpdateAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_UpdateAnnouncementInput]) -> str:
        return _update_announcement(
            services=call.services,
            sphere_id=call.data.sphere_id,
            announcement_id=call.data.announcement_id,
            body=call.data,
        )


class _DeleteAnnouncementInput(_SphereInput):
    announcement_id: int


class DeleteAnnouncementTool(Tool[_DeleteAnnouncementInput]):
    name = "delete_announcement"
    description = "Delete an announcement permanently."
    scope = ToolScope.MAINTAINER
    input_model = _DeleteAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_DeleteAnnouncementInput]) -> str:
        return _delete_announcement(
            services=call.services,
            sphere_id=call.data.sphere_id,
            announcement_id=call.data.announcement_id,
        )


def _announcement_data(body: _AnnouncementBody) -> AnnouncementData:
    return AnnouncementData(
        title=body.title, content=body.content, is_published=body.is_published
    )


def _actor_sphere(actor: ActorContext) -> int:
    if actor.sphere_id is None:
        raise ToolError("Token carries no sphere scope")
    return actor.sphere_id


class OrganizerGetSphereTool(Tool[_EmptyInput]):
    name = "get_sphere"
    description = "Read your sphere's settings and configuration."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        return _render_sphere(call.services, _actor_sphere(call.actor))


class OrganizerListEventsTool(Tool[_ListEventsBody]):
    name = "list_events"
    description = "List your sphere's events with their status and session counts."
    scope = ToolScope.ORGANIZER
    input_model = _ListEventsBody

    @staticmethod
    def handle(call: ToolCall[_ListEventsBody]) -> str:
        return _render_events(
            services=call.services,
            sphere_id=_actor_sphere(call.actor),
            include_unpublished=call.data.include_unpublished,
        )


class OrganizerListAnnouncementsTool(Tool[_EmptyInput]):
    name = "list_announcements"
    description = "List your sphere's announcements, published and drafts."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        return _render_announcements(call.services, _actor_sphere(call.actor))


class OrganizerCreateAnnouncementTool(Tool[_AnnouncementBody]):
    name = "create_announcement"
    description = "Create an announcement in your sphere (draft by default)."
    scope = ToolScope.ORGANIZER
    input_model = _AnnouncementBody

    @staticmethod
    def handle(call: ToolCall[_AnnouncementBody]) -> str:
        return _create_announcement(
            services=call.services, sphere_id=_actor_sphere(call.actor), body=call.data
        )


class _OrgUpdateAnnouncementInput(_AnnouncementBody):
    announcement_id: int


class OrganizerUpdateAnnouncementTool(Tool[_OrgUpdateAnnouncementInput]):
    name = "update_announcement"
    description = "Update an announcement's title, content or published flag."
    scope = ToolScope.ORGANIZER
    input_model = _OrgUpdateAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_OrgUpdateAnnouncementInput]) -> str:
        return _update_announcement(
            services=call.services,
            sphere_id=_actor_sphere(call.actor),
            announcement_id=call.data.announcement_id,
            body=call.data,
        )


class _OrgDeleteAnnouncementInput(BaseModel):
    announcement_id: int


class OrganizerDeleteAnnouncementTool(Tool[_OrgDeleteAnnouncementInput]):
    name = "delete_announcement"
    description = "Delete an announcement from your sphere permanently."
    scope = ToolScope.ORGANIZER
    input_model = _OrgDeleteAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_OrgDeleteAnnouncementInput]) -> str:
        return _delete_announcement(
            services=call.services,
            sphere_id=_actor_sphere(call.actor),
            announcement_id=call.data.announcement_id,
        )


def _all_tools() -> tuple[ToolProtocol, ...]:
    return (
        ListSpheresTool(),
        GetSphereTool(),
        ListEventsTool(),
        GetEventTool(),
        ListAnnouncementsTool(),
        CreateAnnouncementTool(),
        UpdateAnnouncementTool(),
        DeleteAnnouncementTool(),
        OrganizerGetSphereTool(),
        OrganizerListEventsTool(),
        OrganizerListAnnouncementsTool(),
        OrganizerCreateAnnouncementTool(),
        OrganizerUpdateAnnouncementTool(),
        OrganizerDeleteAnnouncementTool(),
    )


def build_registry(scope: ToolScope) -> ToolRegistry:
    return ToolRegistry([tool for tool in _all_tools() if tool.scope == scope])
