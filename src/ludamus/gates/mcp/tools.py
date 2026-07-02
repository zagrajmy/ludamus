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
from ludamus.pacts.legacy import EventDTO, EventListItemDTO, SphereDTO
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    SphereListItemDTO,
)

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolCall, ToolProtocol
    from ludamus.pacts.mcp import ActorContext

_SPHERE_LIST = TypeAdapter(list[SphereListItemDTO])
_EVENT_LIST = TypeAdapter(list[EventListItemDTO])
_ANNOUNCEMENT_LIST = TypeAdapter(list[AnnouncementDTO])


class _EmptyInput(BaseModel):
    pass


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
        sphere: SphereDTO = call.services.sphere_panel.read(call.data.sphere_id)
        return sphere.model_dump_json(indent=2)


class _ListEventsInput(_SphereInput):
    include_unpublished: bool = Field(
        default=True, description="Include events that are not published yet"
    )


class ListEventsTool(Tool[_ListEventsInput]):
    name = "list_events"
    description = "List a sphere's events with their status and session counts."
    scope = ToolScope.MAINTAINER
    input_model = _ListEventsInput

    @staticmethod
    def handle(call: ToolCall[_ListEventsInput]) -> str:
        events = call.services.events.list_for_sphere(
            call.data.sphere_id, include_unpublished=call.data.include_unpublished
        )
        return _EVENT_LIST.dump_json(events, indent=2).decode()


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
        items = call.services.announcements.list_for_sphere(call.data.sphere_id)
        return _ANNOUNCEMENT_LIST.dump_json(items, indent=2).decode()


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
        created = call.services.announcements.create(
            call.data.sphere_id, _announcement_data(call.data)
        )
        return created.model_dump_json(indent=2)


class _UpdateAnnouncementInput(_AnnouncementContentInput):
    announcement_id: int


class UpdateAnnouncementTool(Tool[_UpdateAnnouncementInput]):
    name = "update_announcement"
    description = "Update an announcement's title, content or published flag."
    scope = ToolScope.MAINTAINER
    input_model = _UpdateAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_UpdateAnnouncementInput]) -> str:
        updated = call.services.announcements.update(
            call.data.sphere_id,
            call.data.announcement_id,
            _announcement_data(call.data),
        )
        return updated.model_dump_json(indent=2)


class _DeleteAnnouncementInput(_SphereInput):
    announcement_id: int


class DeleteAnnouncementTool(Tool[_DeleteAnnouncementInput]):
    name = "delete_announcement"
    description = "Delete an announcement permanently."
    scope = ToolScope.MAINTAINER
    input_model = _DeleteAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_DeleteAnnouncementInput]) -> str:
        call.services.announcements.delete(
            call.data.sphere_id, call.data.announcement_id
        )
        result: dict[str, int] = {"deleted": call.data.announcement_id}
        return json.dumps(result)


def _announcement_data(body: _AnnouncementBody) -> AnnouncementData:
    return AnnouncementData(
        title=body.title, content=body.content, is_published=body.is_published
    )


def _actor_sphere(actor: ActorContext) -> int:
    if actor.sphere_id is None:
        raise ToolError("Token carries no sphere scope")
    return actor.sphere_id


class _OrgListEventsInput(BaseModel):
    include_unpublished: bool = Field(
        default=True, description="Include events that are not published yet"
    )


class OrganizerGetSphereTool(Tool[_EmptyInput]):
    name = "get_sphere"
    description = "Read your sphere's settings and configuration."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        sphere: SphereDTO = call.services.sphere_panel.read(_actor_sphere(call.actor))
        return sphere.model_dump_json(indent=2)


class OrganizerListEventsTool(Tool[_OrgListEventsInput]):
    name = "list_events"
    description = "List your sphere's events with their status and session counts."
    scope = ToolScope.ORGANIZER
    input_model = _OrgListEventsInput

    @staticmethod
    def handle(call: ToolCall[_OrgListEventsInput]) -> str:
        events = call.services.events.list_for_sphere(
            _actor_sphere(call.actor), include_unpublished=call.data.include_unpublished
        )
        return _EVENT_LIST.dump_json(events, indent=2).decode()


class OrganizerListAnnouncementsTool(Tool[_EmptyInput]):
    name = "list_announcements"
    description = "List your sphere's announcements, published and drafts."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        items = call.services.announcements.list_for_sphere(_actor_sphere(call.actor))
        return _ANNOUNCEMENT_LIST.dump_json(items, indent=2).decode()


class OrganizerCreateAnnouncementTool(Tool[_AnnouncementBody]):
    name = "create_announcement"
    description = "Create an announcement in your sphere (draft by default)."
    scope = ToolScope.ORGANIZER
    input_model = _AnnouncementBody

    @staticmethod
    def handle(call: ToolCall[_AnnouncementBody]) -> str:
        created = call.services.announcements.create(
            _actor_sphere(call.actor), _announcement_data(call.data)
        )
        return created.model_dump_json(indent=2)


class _OrgUpdateAnnouncementInput(_AnnouncementBody):
    announcement_id: int


class OrganizerUpdateAnnouncementTool(Tool[_OrgUpdateAnnouncementInput]):
    name = "update_announcement"
    description = "Update an announcement's title, content or published flag."
    scope = ToolScope.ORGANIZER
    input_model = _OrgUpdateAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_OrgUpdateAnnouncementInput]) -> str:
        updated = call.services.announcements.update(
            _actor_sphere(call.actor),
            call.data.announcement_id,
            _announcement_data(call.data),
        )
        return updated.model_dump_json(indent=2)


class _OrgDeleteAnnouncementInput(BaseModel):
    announcement_id: int


class OrganizerDeleteAnnouncementTool(Tool[_OrgDeleteAnnouncementInput]):
    name = "delete_announcement"
    description = "Delete an announcement from your sphere permanently."
    scope = ToolScope.ORGANIZER
    input_model = _OrgDeleteAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_OrgDeleteAnnouncementInput]) -> str:
        call.services.announcements.delete(
            _actor_sphere(call.actor), call.data.announcement_id
        )
        result: dict[str, int] = {"deleted": call.data.announcement_id}
        return json.dumps(result)


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
