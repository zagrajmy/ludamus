"""Maintainer MCP tool set.

A hand-curated surface, not an auto-export of every service: each tool is a
deliberate maintainer operation. All calls go through `ServicesProtocol`, so
business invariants hold for MCP callers exactly as they do for views.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter, field_validator

from ludamus.gates.mcp.organizer_context import actor_sphere
from ludamus.gates.mcp.programme_tools import programme_tools
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError, ToolRegistry
from ludamus.pacts.legacy import EventDTO, EventListItemDTO
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    EventDatesInvalidError,
    EventPublicationInvalidError,
    EventSlugConflictError,
    SphereListItemDTO,
)

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.services import ServicesProtocol

_SPHERE_LIST = TypeAdapter(list[SphereListItemDTO])
_EVENT_LIST = TypeAdapter(list[EventListItemDTO])
_ANNOUNCEMENT_LIST = TypeAdapter(list[AnnouncementDTO])
type _NonBlankName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class _EmptyInput(BaseModel):
    pass


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        message = f"{field} must be timezone-aware"
        raise ValueError(message)
    return value


def _validate_slug(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(r"[-a-zA-Z0-9_]+", stripped) is None:
        raise ValueError(
            "slug must contain only letters, numbers, hyphens, or underscores"
        )
    return stripped


class _AwareDatetimeRange(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_datetimes(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field="datetime")


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


class OrganizerGetSphereTool(Tool[_EmptyInput]):
    name = "get_sphere"
    description = "Read your sphere's settings and configuration."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        return _render_sphere(call.services, actor_sphere(call.actor))


class OrganizerListEventsTool(Tool[_ListEventsBody]):
    name = "list_events"
    description = "List your sphere's events with their status and session counts."
    scope = ToolScope.ORGANIZER
    input_model = _ListEventsBody

    @staticmethod
    def handle(call: ToolCall[_ListEventsBody]) -> str:
        return _render_events(
            services=call.services,
            sphere_id=actor_sphere(call.actor),
            include_unpublished=call.data.include_unpublished,
        )


class OrganizerListAnnouncementsTool(Tool[_EmptyInput]):
    name = "list_announcements"
    description = "List your sphere's announcements, published and drafts."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        return _render_announcements(call.services, actor_sphere(call.actor))


class _EventSlugInput(BaseModel):
    slug: str = Field(description="Event slug (see list_events)")


class OrganizerGetEventTool(Tool[_EventSlugInput]):
    name = "get_event"
    description = "Read one event in your sphere by slug."
    scope = ToolScope.ORGANIZER
    input_model = _EventSlugInput

    @staticmethod
    def handle(call: ToolCall[_EventSlugInput]) -> str:
        event: EventDTO = call.services.events.read_by_slug(
            actor_sphere(call.actor), call.data.slug
        )
        return event.model_dump_json(indent=2)


class _CreateEventInput(_SphereInput):
    name: _NonBlankName
    slug: str = Field(max_length=50, description="URL slug; unique within the sphere")
    description: str = ""
    start_time: datetime
    end_time: datetime
    publication_time: datetime | None = Field(
        default=None, description="None keeps the event unpublished"
    )
    auto_confirm_sessions: bool = Field(
        default=False,
        description="Confirm sessions when first assigned to the timetable",
    )

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_event_datetimes(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field="datetime")

    @field_validator("publication_time")
    @classmethod
    def _aware_publication_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware_datetime(value, field="publication_time")


class CreateEventTool(Tool[_CreateEventInput]):
    name = "create_event"
    description = "Create an event in a sphere."
    scope = ToolScope.MAINTAINER
    input_model = _CreateEventInput

    @staticmethod
    def handle(call: ToolCall[_CreateEventInput]) -> str:
        try:
            event = call.services.events.create(
                sphere_id=call.data.sphere_id,
                data={
                    "name": call.data.name,
                    "slug": call.data.slug,
                    "description": call.data.description,
                    "start_time": call.data.start_time,
                    "end_time": call.data.end_time,
                    "publication_time": call.data.publication_time,
                    "auto_confirm_sessions": call.data.auto_confirm_sessions,
                },
            )
        except EventDatesInvalidError as error:
            raise ToolError("end_time must be after start_time") from error
        except EventPublicationInvalidError as error:
            raise ToolError("publication_time must not be after start_time") from error
        except EventSlugConflictError as error:
            message = f"Slug already taken: {call.data.slug}"
            raise ToolError(message) from error
        return event.model_dump_json(indent=2)


def _all_tools() -> tuple[ToolProtocol, ...]:
    return (
        ListSpheresTool(),
        GetSphereTool(),
        ListEventsTool(),
        GetEventTool(),
        CreateEventTool(),
        ListAnnouncementsTool(),
        CreateAnnouncementTool(),
        UpdateAnnouncementTool(),
        DeleteAnnouncementTool(),
        OrganizerGetSphereTool(),
        OrganizerListEventsTool(),
        OrganizerGetEventTool(),
        *programme_tools(),
        OrganizerListAnnouncementsTool(),
    )


def build_registry(scope: ToolScope) -> ToolRegistry:
    return ToolRegistry([tool for tool in _all_tools() if tool.scope == scope])
