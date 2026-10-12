"""MCP tool set for both tiers.

A hand-curated surface, not an auto-export of every service: each tool is a
deliberate operation. Organizer tools are written once and serve maintainers
too, through `MaintainerTool`. All calls go through `ServicesProtocol`, so
business invariants hold for MCP callers exactly as they do for views.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from ludamus.gates.mcp.inputs import (
    SLUG_MAX_LENGTH,
    EmptyInput,
    NonBlankName,
    require_aware_datetime,
    validate_slug,
)
from ludamus.gates.mcp.konwencik_tools import (
    OrganizerGetKonwencikSettingsTool,
    OrganizerUpdateKonwencikStylesTool,
)
from ludamus.gates.mcp.organizer_context import MaintainerTool, actor_sphere
from ludamus.gates.mcp.programme_tools import programme_tools
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError, ToolRegistry
from ludamus.pacts.event import (
    EventDatesInvalidError,
    EventPublicationInvalidError,
    EventSlugConflictError,
)
from ludamus.pacts.legacy import EventDTO, EventListItemDTO
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    SphereListItemDTO,
)

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import OrganizerToolProtocol, ToolProtocol
    from ludamus.pacts.services import ServicesProtocol

_SPHERE_LIST = TypeAdapter(list[SphereListItemDTO])
_EVENT_LIST = TypeAdapter(list[EventListItemDTO])
_ANNOUNCEMENT_LIST = TypeAdapter(list[AnnouncementDTO])


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


class ListSpheresTool(Tool[EmptyInput]):
    name = "list_spheres"
    description = (
        "List every sphere (community site) with its id, name and domain. "
        "Call this first to discover sphere ids used by the other tools."
    )
    scope = ToolScope.MAINTAINER
    input_model = EmptyInput

    @staticmethod
    def handle(call: ToolCall[EmptyInput]) -> str:
        spheres = call.services.sites.list_spheres()
        return _SPHERE_LIST.dump_json(spheres, indent=2).decode()


class _ListEventsBody(BaseModel):
    include_unpublished: bool = Field(
        default=True, description="Include events that are not published yet"
    )


class _AnnouncementBody(BaseModel):
    title: str = Field(max_length=255, description="Headline shown in the list")
    content: str = Field(
        max_length=50000,
        description="Body text; line breaks are kept, Markdown is not rendered",
    )
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


class OrganizerGetSphereTool(Tool[EmptyInput]):
    name = "get_sphere"
    description = "Read the sphere's settings and configuration."
    scope = ToolScope.ORGANIZER
    input_model = EmptyInput

    @staticmethod
    def handle(call: ToolCall[EmptyInput]) -> str:
        sphere = call.services.sphere_panel.read(actor_sphere(call.actor))
        return sphere.model_dump_json(indent=2)


class OrganizerListEventsTool(Tool[_ListEventsBody]):
    name = "list_events"
    description = "List the sphere's events with their status and session counts."
    scope = ToolScope.ORGANIZER
    input_model = _ListEventsBody

    @staticmethod
    def handle(call: ToolCall[_ListEventsBody]) -> str:
        events = call.services.events.list_for_sphere(
            actor_sphere(call.actor), include_unpublished=call.data.include_unpublished
        )
        return _EVENT_LIST.dump_json(events, indent=2).decode()


class OrganizerListAnnouncementsTool(Tool[EmptyInput]):
    name = "list_announcements"
    description = "List the sphere's announcements, published and drafts."
    scope = ToolScope.ORGANIZER
    input_model = EmptyInput

    @staticmethod
    def handle(call: ToolCall[EmptyInput]) -> str:
        items = call.services.announcements.list_for_sphere(actor_sphere(call.actor))
        return _ANNOUNCEMENT_LIST.dump_json(items, indent=2).decode()


class _EventSlugInput(BaseModel):
    slug: str = Field(description="Event slug (see list_events)")


class OrganizerGetEventTool(Tool[_EventSlugInput]):
    name = "get_event"
    description = "Read one event in the sphere by slug."
    scope = ToolScope.ORGANIZER
    input_model = _EventSlugInput

    @staticmethod
    def handle(call: ToolCall[_EventSlugInput]) -> str:
        event: EventDTO = call.services.events.read_by_slug(
            actor_sphere(call.actor), call.data.slug
        )
        return event.model_dump_json(indent=2)


class _CreateEventBody(BaseModel):
    # SAFETY: unknown fields are refused, not dropped: an organizer's sphere
    # comes from the token, and a sphere_id sent anyway must not look accepted.
    # (A maintainer's sphere_id is taken off before this model sees it.)
    model_config = ConfigDict(extra="forbid")

    name: NonBlankName = Field(description="Public event name")
    slug: str = Field(
        max_length=SLUG_MAX_LENGTH, description="URL slug; unique within the sphere"
    )
    description: str = Field(default="", description="Public event description")
    start_time: datetime = Field(
        description="Timezone-aware ISO-8601 start (naive values are rejected)"
    )
    end_time: datetime = Field(
        description="Timezone-aware ISO-8601 end; must be after start_time"
    )
    publication_time: datetime | None = Field(
        default=None,
        description=(
            "Timezone-aware; must not be after start_time. "
            "None keeps the event unpublished"
        ),
    )
    auto_confirm_sessions: bool = Field(
        default=False,
        description="Confirm sessions when first assigned to the timetable",
    )

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, value: str) -> str:
        return validate_slug(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_event_datetimes(cls, value: datetime) -> datetime:
        return require_aware_datetime(value)

    @field_validator("publication_time")
    @classmethod
    def _aware_publication_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware_datetime(value)


class OrganizerCreateEventTool(Tool[_CreateEventBody]):
    name = "create_event"
    description = (
        "Create another event in your sphere. The token stays bound to its "
        "own event: to write the new event's programme, connect again and "
        "pick the new event."
    )
    maintainer_description = "Create an event in a sphere."
    scope = ToolScope.ORGANIZER
    input_model = _CreateEventBody

    @staticmethod
    def handle(call: ToolCall[_CreateEventBody]) -> str:
        body = call.data
        try:
            event = call.services.events.create(
                sphere_id=actor_sphere(call.actor),
                data={
                    "name": body.name,
                    "slug": body.slug,
                    "description": body.description,
                    "start_time": body.start_time,
                    "end_time": body.end_time,
                    "publication_time": body.publication_time,
                    "auto_confirm_sessions": body.auto_confirm_sessions,
                },
            )
        except EventDatesInvalidError as error:
            raise ToolError("end_time must be after start_time") from error
        except EventPublicationInvalidError as error:
            raise ToolError("publication_time must not be after start_time") from error
        except EventSlugConflictError as error:
            message = f"Slug already taken: {body.slug}"
            raise ToolError(message) from error
        return event.model_dump_json(indent=2)


def _organizer_tools() -> tuple[OrganizerToolProtocol, ...]:
    return (
        OrganizerGetSphereTool(),
        OrganizerListEventsTool(),
        OrganizerGetEventTool(),
        *programme_tools(),
        OrganizerCreateEventTool(),
        OrganizerGetKonwencikSettingsTool(),
        OrganizerUpdateKonwencikStylesTool(),
        OrganizerListAnnouncementsTool(),
    )


def _all_tools() -> tuple[ToolProtocol, ...]:
    organizer_tools = _organizer_tools()
    return (
        ListSpheresTool(),
        CreateAnnouncementTool(),
        UpdateAnnouncementTool(),
        DeleteAnnouncementTool(),
        # Maintainers outrank organizers, so they get every organizer tool,
        # run by the same code, with the sphere and event as arguments.
        *(MaintainerTool(tool) for tool in organizer_tools),
        *organizer_tools,
    )


def build_registry(scope: ToolScope) -> ToolRegistry:
    return ToolRegistry([tool for tool in _all_tools() if tool.scope == scope])
